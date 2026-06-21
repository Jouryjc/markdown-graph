"""GET /api/graph and GET /api/graph/expand.

Contract:
- GET /api/graph?limit=int(optional) -> GraphResponse{nodes,edges,truncated,
  total_nodes}. When truncating keep the first `limit` id-sorted nodes and only
  edges whose both endpoints are kept. export_graph() is already id-sorted.
- GET /api/graph/expand?seeds=a,b,c&hops=2 -> Subgraph over subgraph(seeds +
  expanded ids). seeds is comma-separated.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..engine_provider import get_engine
from ..schemas import GraphEdge, GraphNode, GraphResponse, Subgraph

router = APIRouter(prefix="/api", tags=["graph"])


def _nodes(raw: list[dict]) -> list[GraphNode]:
    return [GraphNode(id=n["id"], type=n["type"], meta=n.get("meta", {})) for n in raw]


def _edges(raw: list[dict]) -> list[GraphEdge]:
    return [GraphEdge(src=e["src"], dst=e["dst"], type=e["type"]) for e in raw]


@router.get("/graph", response_model=GraphResponse)
def get_graph(limit: int | None = Query(default=None, ge=0)) -> GraphResponse:
    engine = get_engine()
    graph = engine.graph_store.export_graph()  # id-sorted nodes + edges
    all_nodes = graph["nodes"]
    all_edges = graph["edges"]
    total_nodes = len(all_nodes)

    if limit is None or total_nodes <= limit:
        return GraphResponse(
            nodes=_nodes(all_nodes),
            edges=_edges(all_edges),
            truncated=False,
            total_nodes=total_nodes,
        )

    kept_nodes = all_nodes[:limit]
    kept_ids = {n["id"] for n in kept_nodes}
    kept_edges = [
        e for e in all_edges if e["src"] in kept_ids and e["dst"] in kept_ids
    ]
    return GraphResponse(
        nodes=_nodes(kept_nodes),
        edges=_edges(kept_edges),
        truncated=True,
        total_nodes=total_nodes,
    )


@router.get("/graph/expand", response_model=Subgraph)
def expand_graph(
    seeds: str = Query(...),
    hops: int = Query(default=2),
) -> Subgraph:
    engine = get_engine()
    seed_ids = [s for s in (part.strip() for part in seeds.split(",")) if s]
    expanded = engine.graph_store.expand(seed_ids, hops=hops)  # {id: dist}, no seeds
    node_ids = seed_ids + list(expanded)
    sub = engine.graph_store.subgraph(node_ids)
    return Subgraph(nodes=_nodes(sub["nodes"]), edges=_edges(sub["edges"]))
