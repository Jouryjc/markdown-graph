"""向量检索 + 图扩展融合：query → 向量召回 →（可选）图扩展 + RRF → 上下文 + 子图。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.fusion import reciprocal_rank_fusion
from mdgraph.models import EdgeType
from mdgraph.providers.base import EmbeddingProvider
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore

_EXPAND_EDGES = [
    EdgeType.CONTAINS,
    EdgeType.LINKS_TO,
    EdgeType.MENTIONS,
    EdgeType.RELATES_TO,
]


class Context(BaseModel):
    chunk_id: str
    text: str
    score: float
    source_path: str = ""
    heading_path: str = ""


class RetrievalResult(BaseModel):
    contexts: list[Context] = Field(default_factory=list)
    subgraph: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})


class Retriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedder: EmbeddingProvider,
        graph_store: GraphStore | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store

    def retrieve(self, query: str, k: int = 8, hops: int = 2) -> RetrievalResult:
        if not query.strip():
            return RetrievalResult()
        qvec = self.embedder.embed([query])[0]
        rows = self.vector_store.search(qvec, k=k)
        if self.graph_store is None:
            return self._vector_only(rows)
        return self._dual(rows, k, hops)

    def _vector_only(self, rows: list[dict]) -> RetrievalResult:
        contexts = [
            Context(
                chunk_id=r["chunk_id"],
                text=r["text"],
                score=1.0 / (1.0 + r["distance"]),
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
            for r in rows
        ]
        contexts.sort(key=lambda c: c.score, reverse=True)
        return RetrievalResult(contexts=contexts)

    def _dual(self, rows: list[dict], k: int, hops: int) -> RetrievalResult:
        vector_ranking = [r["chunk_id"] for r in rows]
        row_by_id = {r["chunk_id"]: r for r in rows}
        dist = self.graph_store.expand(vector_ranking, edge_types=_EXPAND_EDGES, hops=hops)
        graph_chunks = [n for n in dist if self.graph_store.get_chunk(n) is not None]
        graph_ranking = sorted(graph_chunks, key=lambda n: (dist[n], n))
        fused = reciprocal_rank_fusion([vector_ranking, graph_ranking])
        ordered = sorted(fused, key=lambda c: (-fused[c], c))[:k]
        contexts = [self._context(cid, fused[cid], row_by_id) for cid in ordered]
        subgraph = self.graph_store.subgraph(ordered)
        return RetrievalResult(contexts=contexts, subgraph=subgraph)

    def _context(self, chunk_id: str, score: float, row_by_id: dict) -> Context:
        if chunk_id in row_by_id:
            r = row_by_id[chunk_id]
            return Context(
                chunk_id=chunk_id,
                text=r["text"],
                score=score,
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
        ch = self.graph_store.get_chunk(chunk_id)
        source = ""
        if ch is not None:
            doc = self.graph_store.get_document(ch.doc_id)
            source = doc.path if doc is not None else ""
        return Context(
            chunk_id=chunk_id,
            text=ch.text if ch is not None else "",
            score=score,
            source_path=source,
            heading_path=ch.section_path if ch is not None else "",
        )
