"""Document + node detail endpoints.

Contract:
- GET /api/documents -> list[DocumentSummary] sorted by id.
- GET /api/document/{doc_id} -> DocumentDetail {document, chunks, links}.
  404 if missing. links = LINKS_TO out-edges from this document node (or its
  sections/chunks) to OTHER document ids.
- GET /api/node/{node_id} -> NodeDetail {node, neighbors}. 404 if missing.
  Derive neighbors from to_networkx() out/in edges (1 hop).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from mdgraph.models import EdgeType, NodeType

from ..engine_provider import get_engine
from ..schemas import (
    DocumentChunk,
    DocumentDetail,
    DocumentMeta,
    DocumentSummary,
    GraphNode,
    NeighborRef,
    NodeDetail,
)

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    engine = get_engine()
    store = engine.graph_store
    out: list[DocumentSummary] = []
    for doc_id, _hash in store.list_documents():  # already ORDER BY id
        doc = store.get_document(doc_id)
        path = doc.path if doc is not None else ""
        chunk_count = len(store.list_chunks_by_doc(doc_id))
        out.append(
            DocumentSummary(id=doc_id, path=path, chunk_count=chunk_count)
        )
    return out


@router.get("/document/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str) -> DocumentDetail:
    engine = get_engine()
    store = engine.graph_store
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {doc_id}")

    chunks = [
        DocumentChunk(id=c.id, section_path=c.section_path, text=c.text)
        for c in store.list_chunks_by_doc(doc_id)
    ]

    # LINKS_TO out-edges originating from this document's nodes (the document
    # node itself, or its sections/chunks — their ids are prefixed with doc_id)
    # whose destination is a DIFFERENT document id. export_graph() is id-sorted.
    graph = store.export_graph()
    known_doc_ids = {n["id"] for n in graph["nodes"] if n["type"] == NodeType.DOCUMENT.value}

    def _belongs(node_id: str) -> bool:
        return node_id == doc_id or node_id.startswith(f"{doc_id}_")

    links: list[str] = []
    seen: set[str] = set()
    for e in graph["edges"]:
        if e["type"] != EdgeType.LINKS_TO.value:
            continue
        if not _belongs(e["src"]):
            continue
        dst = e["dst"]
        if dst in known_doc_ids and dst != doc_id and dst not in seen:
            seen.add(dst)
            links.append(dst)
    links.sort()

    return DocumentDetail(
        document=DocumentMeta(id=doc.id, path=doc.path, frontmatter=doc.frontmatter),
        chunks=chunks,
        links=links,
    )


@router.get("/node/{node_id}", response_model=NodeDetail)
def get_node(node_id: str) -> NodeDetail:
    engine = get_engine()
    store = engine.graph_store
    node = store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"node not found: {node_id}")

    g = store.to_networkx()
    neighbors: list[NeighborRef] = []
    if node_id in g:
        for _src, dst, key in g.out_edges(node_id, keys=True):
            attrs = g.nodes[dst]
            neighbors.append(
                NeighborRef(
                    id=dst,
                    type=attrs.get("type", ""),
                    meta=attrs.get("meta", {}),
                    edge_type=key,
                    direction="out",
                )
            )
        for src, _dst, key in g.in_edges(node_id, keys=True):
            attrs = g.nodes[src]
            neighbors.append(
                NeighborRef(
                    id=src,
                    type=attrs.get("type", ""),
                    meta=attrs.get("meta", {}),
                    edge_type=key,
                    direction="in",
                )
            )
    neighbors.sort(key=lambda n: (n.direction, n.id, n.edge_type))

    return NodeDetail(
        node=GraphNode(id=node.id, type=node.type.value, meta=node.meta),
        neighbors=neighbors,
    )
