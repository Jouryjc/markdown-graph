"""Pydantic response/request models — the SINGLE SOURCE OF TRUTH for the API contract.

The frontend file `webapp/frontend/src/api/types.ts` mirrors these models EXACTLY
(field names + types). Do not rename or retype fields without updating both sides.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared graph primitives
# ---------------------------------------------------------------------------
class GraphNode(BaseModel):
    id: str
    type: str
    meta: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    src: str
    dst: str
    type: str


class Subgraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------
class Stats(BaseModel):
    documents: int = 0
    sections: int = 0
    chunks: int = 0
    entities: int = 0
    tags: int = 0
    nodes: int = 0
    edges: int = 0
    vectors: int = 0


# ---------------------------------------------------------------------------
# /api/query
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    query: str
    k: int = Field(default=8, ge=1)
    mode: Literal["dual", "vector"] = "dual"
    graph_weight: float = 0.5
    per_doc_cap: int | None = 2
    hops: int = 2


class Context(BaseModel):
    chunk_id: str
    text: str
    score: float
    doc_id: str = ""
    source_path: str = ""
    heading_path: str = ""
    from_graph: bool = False


class QueryResponse(BaseModel):
    contexts: list[Context] = Field(default_factory=list)
    subgraph: Subgraph = Field(default_factory=Subgraph)


# ---------------------------------------------------------------------------
# /api/graph and /api/graph/expand
# ---------------------------------------------------------------------------
class GraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    truncated: bool = False
    total_nodes: int = 0


# ---------------------------------------------------------------------------
# /api/node/{node_id}
# ---------------------------------------------------------------------------
class NeighborRef(BaseModel):
    id: str
    type: str
    meta: dict[str, Any] = Field(default_factory=dict)
    edge_type: str
    direction: Literal["out", "in"]


class NodeDetail(BaseModel):
    node: GraphNode
    neighbors: list[NeighborRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/documents and /api/document/{doc_id}
# ---------------------------------------------------------------------------
class DocumentSummary(BaseModel):
    id: str
    path: str
    chunk_count: int


class DocumentChunk(BaseModel):
    id: str
    section_path: str
    text: str


class DocumentMeta(BaseModel):
    id: str
    path: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)


class DocumentDetail(BaseModel):
    document: DocumentMeta
    chunks: list[DocumentChunk] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/entities
# ---------------------------------------------------------------------------
class EntitySummary(BaseModel):
    id: str
    name: str
    type: str = ""
    mentions: int = 0


# ---------------------------------------------------------------------------
# /api/index
# ---------------------------------------------------------------------------
class IndexRequest(BaseModel):
    paths: list[str]
    full: bool = False


class IndexReport(BaseModel):
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    reclaimed: int = 0
    entities: int = 0
    errors: list[list[str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
class Health(BaseModel):
    status: str = "ok"
