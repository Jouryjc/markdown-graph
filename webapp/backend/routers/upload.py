"""POST /api/upload + GET /api/jobs/{job_id} — async archive-upload build flow.

This is the safer PRIMARY build path (the synchronous /api/index stays for
direct/local use). The client uploads an archive (.zip/.tar.gz/.tgz/.tar); we
validate the extension (400), stream-read the bytes enforcing the upload size
cap (413), require an embedder (503), reject if a build is already running
(409), otherwise persist the bytes to a fresh temp file and kick off a
BACKGROUND build job, returning 202 {job_id}.

The actual extraction/build happens in webapp.backend.jobs on a daemon thread
guarded by a single global build lock; this router only does request-side
validation + hand-off, then exposes job state via GET /api/jobs/{job_id}.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..engine_provider import EngineUnavailable, require_embedder
from ..jobs import get_job, is_build_active, start_build_job
from ..schemas import JobStatus, UploadAccepted
from ..settings import get_settings

router = APIRouter(prefix="/api", tags=["upload"])

# Accepted archive extensions (lowercased filename suffix match). Ordered so the
# longest compound suffixes are checked alongside the simple ones.
_ALLOWED_EXTENSIONS = (".zip", ".tar.gz", ".tgz", ".tar")

# Read the upload in bounded chunks so a huge body never lands fully in memory.
_READ_CHUNK = 64 * 1024


def _has_allowed_extension(filename: str | None) -> bool:
    if not filename:
        return False
    lowered = filename.lower()
    return any(lowered.endswith(ext) for ext in _ALLOWED_EXTENSIONS)


def _parse_full(raw: str) -> bool:
    return raw.strip().lower() == "true"


@router.post("/upload", response_model=UploadAccepted, status_code=202)
async def upload_archive(
    file: UploadFile = File(...),
    full: str = Form("false"),
) -> UploadAccepted:
    settings = get_settings()

    # 1. Extension validation (400) — cheap, do it before touching the engine.
    if not _has_allowed_extension(file.filename):
        raise HTTPException(
            status_code=400,
            detail=(
                "unsupported archive type; expected one of "
                ".zip, .tar.gz, .tgz, .tar"
            ),
        )

    # 2. Embedder must be configured (503) — building without it is pointless.
    try:
        require_embedder()
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 3. Reject if a build is already running (409). The lock is also held inside
    # the worker thread, so this is a best-effort fast path; the thread keeps the
    # invariant of at-most-one active build.
    if is_build_active():
        raise HTTPException(
            status_code=409, detail="a build is already in progress"
        )

    # 4. Stream the upload to a fresh temp file, enforcing the size cap (413).
    max_bytes = settings.max_archive_bytes
    tmp = tempfile.NamedTemporaryFile(
        prefix="mdgraph-upload-", suffix=".archive", delete=False
    )
    archive_path = Path(tmp.name)
    total = 0
    try:
        while True:
            chunk = await file.read(_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                tmp.close()
                archive_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"archive exceeds the maximum upload size "
                        f"({max_bytes} bytes)"
                    ),
                )
            tmp.write(chunk)
        tmp.flush()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — clean up temp file, surface 400
        try:
            tmp.close()
        except Exception:
            pass
        archive_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"failed to read upload: {exc}"
        ) from exc
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            await file.close()
        except Exception:
            pass

    # 5. Hand off to the background build job. The job owns the temp file from
    # here and is responsible for deleting it (and the extract dir).
    job_id = start_build_job(archive_path, full=_parse_full(full))
    return UploadAccepted(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def read_job(job_id: str) -> JobStatus:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job id")
    return job
