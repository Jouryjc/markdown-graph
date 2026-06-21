"""GET /api/stats — index/graph statistics.

Contract: return Stats with keys documents, sections, chunks, entities, tags,
nodes, edges, vectors (missing keys default 0). Must work even without embedder.

``engine.stats()`` only reports documents/nodes/edges/chunks (+vectors when an
embedder is configured). sections/entities/tags are NOT in that dict, so we
derive them from the node-type histogram of ``export_graph()`` to give the
frontend real counts (the Stats model still defaults any missing key to 0).
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter

from ..engine_provider import get_engine
from ..schemas import Stats

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=Stats)
def get_stats() -> Stats:
    engine = get_engine()
    raw = engine.stats()  # documents/nodes/edges/chunks (+vectors if embedder)

    # Derive sections/entities/tags from node types (engine.stats omits them).
    type_counts: Counter[str] = Counter(
        n["type"] for n in engine.graph_store.export_graph()["nodes"]
    )

    return Stats(
        documents=raw.get("documents", 0),
        sections=type_counts.get("section", 0),
        chunks=raw.get("chunks", 0),
        entities=type_counts.get("entity", 0),
        tags=type_counts.get("tag", 0),
        nodes=raw.get("nodes", 0),
        edges=raw.get("edges", 0),
        vectors=raw.get("vectors", 0),
    )
