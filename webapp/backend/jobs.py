"""Background build-job registry + runner for the upload flow.

A single global BUILD LOCK guarantees at most one build runs at a time (the
router maps a busy lock to HTTP 409). Jobs live in a module-level dict guarded by
its own Lock so the serving threads can poll ``get_job`` while a daemon thread
mutates state.

The runner extracts the uploaded archive into a fresh temp dir, counts markdown
files, then builds with an ISOLATED engine (a brand-new MarkdownGraph with its
own sqlite connection + freshly built embedder/llm) so the build never shares the
serving singleton across threads. On success it closes that engine and calls
``reset_engine()`` so the serving singleton reopens against the new data. The
temp extract dir and the temp archive file are always cleaned up.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from mdgraph import MarkdownGraph

from .archive import ArchiveError, ExtractLimits, extract_markdown_archive
from .engine_provider import _build_embedder, _build_llm, reset_engine
from .schemas import IndexReport, JobStatus
from .settings import get_settings

# --- registry -------------------------------------------------------------
_jobs: dict[str, JobStatus] = {}
_jobs_lock = threading.Lock()

# At most one build at a time. Non-blocking acquire in start_build_job; the
# router checks is_build_active() first to return 409 cleanly.
_build_lock = threading.Lock()

# Phase name (from the engine progress callback) -> JobStatus.state.
_PHASE_TO_STATE = {
    "indexing": "indexing",
    "embedding": "embedding",
    "extracting_entities": "extracting_entities",
    "sag": "sag_indexing",
}


def create_job() -> str:
    """Register a fresh pending job and return its id."""
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = JobStatus(job_id=job_id, state="pending")
    return job_id


def get_job(job_id: str) -> JobStatus | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        # Return a copy so callers can't mutate registry state.
        return job.model_copy(deep=True)


def is_build_active() -> bool:
    """True if a build is currently holding the global build lock."""
    if _build_lock.acquire(blocking=False):
        _build_lock.release()
        return False
    return True


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        _jobs[job_id] = job.model_copy(update=fields)


def _report_to_schema(report) -> IndexReport:
    return IndexReport(
        indexed=report.indexed,
        unchanged=report.unchanged,
        removed=report.removed,
        reclaimed=report.reclaimed,
        entities=report.entities,
        errors=[list(e) for e in report.errors],
    )


def start_build_job(archive_path: Path, full: bool) -> str:
    """Create a job and spawn a daemon thread to run the build.

    The caller (router) is responsible for the 409 pre-check via
    ``is_build_active()``; this still acquires the build lock inside the thread
    and releases it in a finally so the lock can never leak.
    """
    job_id = create_job()
    thread = threading.Thread(
        target=_run_build,
        args=(job_id, Path(archive_path), full),
        name=f"mdgraph-build-{job_id}",
        daemon=True,
    )
    thread.start()
    return job_id


def _run_build(job_id: str, archive_path: Path, full: bool) -> None:
    # Acquire the build lock for the whole run; release in finally.
    _build_lock.acquire()
    extract_dir: Path | None = None
    engine: MarkdownGraph | None = None
    try:
        settings = get_settings()
        limits = ExtractLimits(
            max_archive_bytes=settings.max_archive_bytes,
            max_entries=settings.max_entries,
            max_total_uncompressed=settings.max_total_uncompressed,
            max_file_bytes=settings.max_file_bytes,
        )

        # 1. extract
        _update_job(job_id, state="extracting", phase="extracting")
        extract_dir = Path(tempfile.mkdtemp(prefix="mdgraph-extract-"))
        try:
            md_count = extract_markdown_archive(
                archive_path, extract_dir, limits=limits
            )
        except ArchiveError as exc:
            _update_job(job_id, state="error", error=str(exc))
            return
        if md_count == 0:
            _update_job(
                job_id,
                state="error",
                error="archive contains no markdown (.md/.markdown) files",
            )
            return
        _update_job(job_id, markdown_files=md_count)

        # 2. build with an ISOLATED engine (own sqlite conn + fresh providers)
        embedder = _build_embedder(settings)
        llm = _build_llm(settings)
        engine = MarkdownGraph(settings.store_dir, embedder=embedder, llm=llm)

        def _progress(phase: str, current: int, total: int) -> None:
            state = _PHASE_TO_STATE.get(phase)
            if state is None:
                return
            _update_job(
                job_id,
                state=state,
                phase=phase,
                processed=current,
                total=total,
            )

        report = engine.build(
            [extract_dir],
            root=extract_dir,
            incremental=not full,
            progress=_progress,
        )

        engine.close()
        engine = None
        # Reopen the serving singleton against the freshly written store.
        reset_engine()

        _update_job(
            job_id,
            state="done",
            phase="done",
            report=_report_to_schema(report),
        )
    except Exception as exc:  # noqa: BLE001 — surface as job error, never crash thread
        _update_job(job_id, state="error", error=str(exc))
    finally:
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass
        _build_lock.release()


def start_sag_build_job(full: bool) -> str:
    """Create a job and spawn a daemon thread to build the SAG index.

    SAG indexing runs over the EXISTING store chunks (no upload); it shares the
    same global build lock as the upload build so the two never write at once.
    The caller (router) does the 409 pre-check via ``is_build_active()``; this
    still acquires the lock inside the thread and releases it in a finally.
    """
    job_id = create_job()
    thread = threading.Thread(
        target=_run_sag_build,
        args=(job_id, full),
        name=f"mdgraph-sag-build-{job_id}",
        daemon=True,
    )
    thread.start()
    return job_id


def _run_sag_build(job_id: str, full: bool) -> None:
    # Share the build lock with the upload build to serialize writes; release in
    # finally so it can never leak.
    _build_lock.acquire()
    engine: MarkdownGraph | None = None
    try:
        settings = get_settings()

        # Build with an ISOLATED engine (own sqlite conn + fresh providers) so
        # the SAG build never shares the serving singleton across threads.
        embedder = _build_embedder(settings)
        llm = _build_llm(settings)
        engine = MarkdownGraph(settings.store_dir, embedder=embedder, llm=llm)

        def _progress(phase: str, current: int, total: int) -> None:
            state = _PHASE_TO_STATE.get(phase)
            if state is None:
                return
            _update_job(
                job_id,
                state=state,
                phase=phase,
                processed=current,
                total=total,
            )

        engine.build_sag_index(progress=_progress, full=full)

        engine.close()
        engine = None
        # Reopen the serving singleton against the freshly written sag.db.
        reset_engine()

        # report stays None; final counts are served by /api/sag/status.
        _update_job(job_id, state="done", phase="done")
    except Exception as exc:  # noqa: BLE001 — surface as job error, never crash thread
        _update_job(job_id, state="error", error=str(exc))
    finally:
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass
        _build_lock.release()
