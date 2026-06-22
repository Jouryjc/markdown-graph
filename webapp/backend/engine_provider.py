"""Lazy singleton engine accessor with graceful degradation.

The engine is a MarkdownGraph instance pointed at the configured store dir.

SQLite / threading
------------------
GraphStore (src/mdgraph/store/graph_store.py) opens its sqlite connection via
``sqlite3.connect(self.db_path)`` WITHOUT ``check_same_thread=False``. FastAPI
runs sync endpoints in an anyio threadpool, so a single shared connection used
across worker threads would raise:

    "SQLite objects created in a thread can only be used in that same thread."

We do NOT modify the engine. Instead, immediately after constructing the engine
we relax that flag on the live connection:

    engine.graph_store.conn.execute(...)  # connection already open

sqlite3 lets you set check_same_thread only at connect() time, so we cannot flip
it on an existing connection. The robust, minimal fix is therefore: after
MarkdownGraph builds the GraphStore, REPLACE its connection with one opened using
check_same_thread=False (re-applying row_factory). Writes are serialized by
sqlite's own connection-level locking; for a read-mostly MVP this is safe.

This keeps the engine library pure/offline-deterministic for pytest while making
the web server thread-safe.

Graceful degradation
---------------------
- If the embedder import / its deps fail, OR the store has no vectors, the engine
  is still constructed (graph_store works). ``query`` / ``index`` then raise
  EngineUnavailable, which routers translate to HTTP 503. stats / graph /
  documents / node continue to work.
"""

from __future__ import annotations

import importlib
import sqlite3
import threading
from typing import Any

from mdgraph import MarkdownGraph
from mdgraph.providers.registry import resolve_embedder

from .settings import Settings, get_settings


class EngineUnavailable(RuntimeError):
    """Raised when an embedder-dependent operation is requested but unavailable."""


_engine: MarkdownGraph | None = None
_embedder_error: str | None = None
_lock = threading.Lock()


def _load_dotted(path: str) -> Any:
    """Load ``module.sub:ClassName`` (or ``module.sub.ClassName``) and return it."""
    if ":" in path:
        module_name, attr = path.split(":", 1)
    else:
        module_name, attr = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _make_thread_safe(engine: MarkdownGraph) -> None:
    """Reopen GraphStore's sqlite connection with check_same_thread=False.

    See module docstring for rationale.
    """
    store = engine.graph_store
    try:
        old = store.conn
        new_conn = sqlite3.connect(store.db_path, check_same_thread=False)
        new_conn.row_factory = sqlite3.Row
        store.conn = new_conn
        try:
            old.close()
        except Exception:
            pass
    except Exception:
        # If anything goes wrong, leave the original connection in place.
        pass


def _build_embedder(settings: Settings):
    """Attempt to construct the configured embedder. Returns None on failure
    and records the error message in the module-level ``_embedder_error``."""
    global _embedder_error
    try:
        return resolve_embedder(settings.embedder_path)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _embedder_error = f"embedder unavailable ({settings.embedder_path}): {exc}"
        return None


def _build_llm(settings: Settings):
    if not settings.llm_path:
        return None
    try:
        cls = _load_dotted(settings.llm_path)
        return cls()
    except Exception:  # noqa: BLE001
        return None


def get_engine() -> MarkdownGraph:
    """Return the lazily-constructed singleton engine.

    Always returns a usable engine for graph/store reads. Embedder-dependent
    operations should call :func:`require_embedder` first.

    The read of ``_engine`` is taken under ``_lock`` so it cannot observe a
    half-swapped singleton during :func:`reset_engine` / :func:`set_engine`.
    Once a caller has the returned reference, the underlying sqlite connection
    stays valid for the life of that reference: reconfiguration swaps in a new
    engine and lets the old one be closed by GC, never closing a connection out
    from under an in-flight reader.
    """
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        settings = get_settings()
        embedder = _build_embedder(settings)
        llm = _build_llm(settings)
        engine = MarkdownGraph(settings.store_dir, embedder=embedder, llm=llm)
        _make_thread_safe(engine)
        _engine = engine
        return _engine


def require_embedder() -> MarkdownGraph:
    """Return the engine, raising EngineUnavailable if no embedder/vector store."""
    engine = get_engine()
    if engine.embedder is None or engine.vector_store is None:
        msg = _embedder_error or (
            "embedder/vector store unavailable; configure MDGRAPH_EMBEDDER and "
            "build a store with vectors"
        )
        raise EngineUnavailable(msg)
    return engine


def set_engine(engine: MarkdownGraph | None) -> None:
    """Override the singleton — used by tests to point at a tmp store.

    Swaps atomically under ``_lock`` and does NOT synchronously close the
    previous engine: any reader that already holds a reference to it keeps a
    valid sqlite connection until it finishes, and the orphaned engine is closed
    by GC. This avoids the use-after-close race described in the module / build
    flow.
    """
    global _engine, _embedder_error
    if engine is not None:
        _make_thread_safe(engine)
    with _lock:
        _engine = engine
        _embedder_error = None


def reset_engine() -> None:
    """Clear the singleton so the next :func:`get_engine` rebuilds it.

    Used on build success (to reopen against freshly written data) and in test
    teardown. We deliberately DO NOT close the outgoing engine here: a reader
    (stats / graph / query / documents / entities) may have captured the
    reference just before this runs and still be mid-query. Closing its sqlite
    connection synchronously would raise ``sqlite3.ProgrammingError: Cannot
    operate on a closed database`` under that reader. Instead we drop the
    reference under ``_lock`` and let the garbage collector close the connection
    once no reader holds it — a swap-then-defer that degrades gracefully.
    """
    global _engine, _embedder_error
    with _lock:
        _engine = None
        _embedder_error = None
