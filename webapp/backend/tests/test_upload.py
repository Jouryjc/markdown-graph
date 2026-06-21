"""Upload-flow backend tests — fully offline (Mock providers, no network).

Covers POST /api/upload + GET /api/jobs/{job_id}:
  * happy path: 202 {job_id} -> poll job to state=done; report.indexed matches
    the markdown files in the crafted zip.
  * a zip-slip / path-traversal archive -> the build job ends in state=error.
  * a non-archive extension -> 400 (rejected before any work).
  * no embedder configured -> 503.
  * a second upload while a build is active -> 409.

Archives are crafted in-memory with zipfile + io.BytesIO; the build is driven to
completion deterministically by polling get_job() with a bounded loop (the worker
is a daemon thread; we never sleep on the foreground beyond tiny bounded waits).

IRON RULE: no real models / network. The background build job builds an ISOLATED
engine via get_settings()+_build_embedder/_build_llm, so we point the relevant
env vars at the Mock providers and a fresh tmp store before uploading.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdgraph import MarkdownGraph
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)

from webapp.backend import engine_provider, jobs
from webapp.backend.app import app

_MOCK_EMBEDDER = "mdgraph.providers.mock:DeterministicEmbeddingProvider"
_MOCK_LLM = "mdgraph.providers.mock:MockLLMProvider"

_DOC_ONE = """# One

One mentions Two and connects to [Two](two.md).
"""

_DOC_TWO = """# Two

Two references One. See [One](one.md) for context.
"""

_DOC_NESTED = """# Nested

A nested note inside a subdirectory.
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _zip_bytes(entries: dict[str, str]) -> bytes:
    """Build an in-memory zip from {arcname: text}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, text in entries.items():
            zf.writestr(arcname, text)
    return buf.getvalue()


def _poll_job(client: TestClient, job_id: str, *, timeout: float = 30.0):
    """Poll GET /api/jobs/{id} until the job reaches a terminal state."""
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not terminate; last={body!r}")


@pytest.fixture()
def isolated_build_env(tmp_path: Path, monkeypatch) -> Path:
    """Point the build job at a fresh tmp store + Mock providers, and install a
    serving engine over that same store so require_embedder() passes (503 gate).

    Returns the store dir. The background job calls get_settings() fresh, so the
    env vars steer its ISOLATED engine to the Mock providers / tmp store.
    """
    store = tmp_path / "store"
    monkeypatch.setenv("MDGRAPH_STORE", str(store))
    monkeypatch.setenv("MDGRAPH_EMBEDDER", _MOCK_EMBEDDER)
    monkeypatch.setenv("MDGRAPH_LLM", _MOCK_LLM)

    # Serving engine over the (initially empty) store so the upload endpoint's
    # require_embedder() succeeds. The job calls reset_engine() on success, so
    # subsequent reads reopen against the freshly built store.
    eng = MarkdownGraph(
        store,
        embedder=DeterministicEmbeddingProvider(),
        llm=MockLLMProvider(),
    )
    engine_provider.set_engine(eng)
    yield store
    engine_provider.reset_engine()


@pytest.fixture()
def upload_client(isolated_build_env: Path) -> TestClient:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #
def test_upload_success_drives_job_to_done(upload_client: TestClient) -> None:
    data = _zip_bytes(
        {
            "one.md": _DOC_ONE,
            "two.md": _DOC_TWO,
            "notes/nested.markdown": _DOC_NESTED,  # .markdown -> .md, nested dir
            "ignore.txt": "not markdown, skipped",
        }
    )
    resp = upload_client.post(
        "/api/upload",
        files={"file": ("corpus.zip", data, "application/zip")},
        data={"full": "true"},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    assert job_id

    body = _poll_job(upload_client, job_id)
    assert body["state"] == "done", body
    assert body["job_id"] == job_id
    assert body["error"] is None
    assert body["markdown_files"] == 3  # txt skipped, .markdown counted
    assert body["report"] is not None
    assert body["report"]["indexed"] == 3


# --------------------------------------------------------------------------- #
# zip-slip / path traversal -> job ends in error
# --------------------------------------------------------------------------- #
def test_upload_zip_slip_ends_in_error(upload_client: TestClient) -> None:
    data = _zip_bytes({"../escape.md": "# pwned\n"})
    resp = upload_client.post(
        "/api/upload",
        files={"file": ("evil.zip", data, "application/zip")},
        data={"full": "false"},
    )
    # Accepted for processing; the extractor rejects the traversal in the worker.
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    body = _poll_job(upload_client, job_id)
    assert body["state"] == "error", body
    assert body["error"]
    assert "escape" in body["error"].lower() or ".." in body["error"]
    assert body["report"] is None


# --------------------------------------------------------------------------- #
# bad extension -> 400 (rejected before any work)
# --------------------------------------------------------------------------- #
def test_upload_bad_extension_400(upload_client: TestClient) -> None:
    resp = upload_client.post(
        "/api/upload",
        files={"file": ("notes.txt", b"# hello\n", "text/plain")},
        data={"full": "false"},
    )
    assert resp.status_code == 400, resp.text
    assert "unsupported" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# no embedder -> 503
# --------------------------------------------------------------------------- #
def test_upload_no_embedder_503(no_embedder_client: TestClient) -> None:
    data = _zip_bytes({"one.md": _DOC_ONE})
    resp = no_embedder_client.post(
        "/api/upload",
        files={"file": ("corpus.zip", data, "application/zip")},
        data={"full": "false"},
    )
    assert resp.status_code == 503, resp.text


# --------------------------------------------------------------------------- #
# concurrent build -> 409
# --------------------------------------------------------------------------- #
def test_upload_conflict_when_build_active(upload_client: TestClient) -> None:
    data = _zip_bytes({"one.md": _DOC_ONE})

    # Deterministically force "a build is in progress" by holding the global
    # build lock ourselves (the same lock the worker thread acquires).
    acquired = jobs._build_lock.acquire(blocking=False)
    assert acquired, "build lock unexpectedly held at test start"
    try:
        resp = upload_client.post(
            "/api/upload",
            files={"file": ("corpus.zip", data, "application/zip")},
            data={"full": "false"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "a build is already in progress"
    finally:
        jobs._build_lock.release()


# --------------------------------------------------------------------------- #
# unknown job id -> 404
# --------------------------------------------------------------------------- #
def test_get_unknown_job_404(upload_client: TestClient) -> None:
    resp = upload_client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404, resp.text
