"""GET /api/entities — top entities by MENTIONS in-degree.

Contract: GET /api/entities?limit=20 -> list[EntitySummary] top entities by
MENTIONS in-degree desc then id. name from node.meta.get("name") or id.
type from node.meta.get("type","").
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Query

from mdgraph.models import EdgeType, NodeType

from ..engine_provider import get_engine
from ..schemas import EntitySummary

router = APIRouter(prefix="/api", tags=["entities"])


@router.get("/entities", response_model=list[EntitySummary])
def list_entities(limit: int = Query(default=20, ge=0)) -> list[EntitySummary]:
    engine = get_engine()
    graph = engine.graph_store.export_graph()

    # MENTIONS in-degree per entity (mentions edges go chunk -> entity).
    mention_counts: Counter[str] = Counter(
        e["dst"] for e in graph["edges"] if e["type"] == EdgeType.MENTIONS.value
    )

    summaries: list[EntitySummary] = []
    for n in graph["nodes"]:
        if n["type"] != NodeType.ENTITY.value:
            continue
        meta = n.get("meta", {})
        summaries.append(
            EntitySummary(
                id=n["id"],
                name=meta.get("name") or n["id"],
                type=meta.get("type", ""),
                mentions=mention_counts.get(n["id"], 0),
            )
        )

    # in-degree desc, then id asc.
    summaries.sort(key=lambda s: (-s.mentions, s.id))
    return summaries[:limit]
