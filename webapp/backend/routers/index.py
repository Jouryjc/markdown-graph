"""POST /api/index — synchronous (MVP) build over the configured store.

Contract: body {paths:[str], full:bool=false} -> IndexReport {indexed,unchanged,
removed,reclaimed,entities,errors:[[path,msg]]}. Requires embedder configured.
On error return 4xx/5xx with detail.

The engine's IndexReport.errors entries are tuples; we map each to a list so the
response is JSON-serializable per the schema.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..engine_provider import EngineUnavailable, require_embedder
from ..schemas import IndexReport, IndexRequest

router = APIRouter(prefix="/api", tags=["index"])


@router.post("/index", response_model=IndexReport)
def run_index(body: IndexRequest) -> IndexReport:
    try:
        engine = require_embedder()
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        report = engine.build(body.paths, incremental=not body.full)
    except Exception as exc:  # noqa: BLE001 — surface as HTTP error, do not crash
        raise HTTPException(status_code=500, detail=f"index failed: {exc}") from exc

    errors = [list(e) for e in report.errors]
    return IndexReport(
        indexed=report.indexed,
        unchanged=report.unchanged,
        removed=report.removed,
        reclaimed=report.reclaimed,
        entities=report.entities,
        errors=errors,
    )
