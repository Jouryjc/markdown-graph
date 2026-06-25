"""SAG 事件/实体双层检索端点 —— 与 dual/vector/file 完全隔离。

Contract:
- GET  /api/sag/status -> SAGStatus  # get_engine()，永不 503；counts() + has_embedder
- POST /api/sag/build  -> UploadAccepted  # is_build_active()→409；后台 job，phase "sag"→state "sag_indexing"
- POST /api/sag/search -> SAGSearchResponse
   - get_engine()（**不** require_embedder）—— 缺 embedder 也不 503
   - sag_store.counts()["events"]==0 → 409 引导先构建
   - 否则 engine.retrieve_sag(...) 映射；graph dict→Subgraph（复用 query.py 的 _to_subgraph 思路）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import jobs
from ..engine_provider import get_engine
from ..schemas import (
    GraphEdge,
    GraphNode,
    SAGBuildRequest,
    SAGEntityRef,
    SAGEventHit,
    SAGSearchRequest,
    SAGSearchResponse,
    SAGStatus,
    SAGTrace,
    Subgraph,
    UploadAccepted,
)

router = APIRouter(prefix="/api", tags=["sag"])


def _to_subgraph(raw: dict) -> Subgraph:
    return Subgraph(
        nodes=[
            GraphNode(id=n["id"], type=n["type"], meta=n.get("meta", {}))
            for n in raw.get("nodes", [])
        ],
        edges=[
            GraphEdge(src=e["src"], dst=e["dst"], type=e["type"])
            for e in raw.get("edges", [])
        ],
    )


@router.get("/sag/status", response_model=SAGStatus)
def sag_status() -> SAGStatus:
    engine = get_engine()
    counts = engine.sag_store.counts()
    return SAGStatus(
        built=counts["events"] > 0,
        events=counts["events"],
        entities=counts["entities"],
        links=counts["links"],
        has_embedder=engine.embedder is not None,
    )


@router.post("/sag/build", response_model=UploadAccepted, status_code=202)
def sag_build(body: SAGBuildRequest) -> UploadAccepted:
    # Reject if a build (upload or SAG) is already running (409) — both share the
    # global build lock, so SAG indexing serializes with archive builds.
    if jobs.is_build_active():
        raise HTTPException(
            status_code=409, detail="a build is already in progress"
        )
    job_id = jobs.start_sag_build_job(body.full)
    return UploadAccepted(job_id=job_id)


@router.post("/sag/search", response_model=SAGSearchResponse)
def sag_search(body: SAGSearchRequest) -> SAGSearchResponse:
    # NOT require_embedder: SAG works without vectors (entity match + overlap).
    engine = get_engine()
    if engine.sag_store.counts()["events"] == 0:
        raise HTTPException(
            status_code=409,
            detail="尚未构建 SAG 索引，请先在 SAG 页面点击「构建 SAG 索引」",
        )

    result = engine.retrieve_sag(body.query, k=body.k, max_hops=body.max_hops)

    events = [
        SAGEventHit(
            event_id=hit.event_id,
            title=hit.title,
            summary=hit.summary,
            content=hit.content,
            category=hit.category,
            keywords=hit.keywords,
            score=hit.score,
            hop=hit.hop,
            chunk_id=hit.chunk_id,
            source_path=hit.source_path,
            heading_path=hit.heading_path,
            entities=[
                SAGEntityRef(id=e.id, name=e.name, type=e.type) for e in hit.entities
            ],
            connected_via=hit.connected_via,
        )
        for hit in result.events
    ]
    entities = [
        SAGEntityRef(id=e.id, name=e.name, type=e.type) for e in result.entities
    ]
    trace = SAGTrace(
        query_entities=result.trace.query_entities,
        seed_event_ids=result.trace.seed_event_ids,
        expanded_event_ids=result.trace.expanded_event_ids,
        ranked_event_ids=result.trace.ranked_event_ids,
    )
    return SAGSearchResponse(
        events=events,
        entities=entities,
        graph=_to_subgraph(result.graph),
        trace=trace,
    )
