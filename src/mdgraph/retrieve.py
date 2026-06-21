"""向量检索 + 图扩展融合：query → 向量召回 →（可选）图扩展 + RRF → 上下文 + 子图。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.fusion import reciprocal_rank_fusion
from mdgraph.ids import doc_id_from_chunk
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
    """一条检索命中。

    score 在 dual（图+向量）模式下是**加权** RRF 融合值（图权重 < 向量权重，
    抑制 hub 节点过度放大），在纯向量模式下是 1/(1+距离) 相似度——同字段不同
    量纲，二者都「越大越相关」，仅用于排序。
    """

    chunk_id: str
    text: str
    score: float
    doc_id: str = ""
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
        vector_weight: float = 1.0,
        graph_weight: float = 0.5,
        per_doc_cap: int | None = 2,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self.per_doc_cap = per_doc_cap

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
                doc_id=doc_id_from_chunk(r["chunk_id"]),
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
        chunk_map = self.graph_store.get_chunks(list(dist))  # 一次批量取，消 N+1
        graph_chunks = [n for n in dist if n in chunk_map]
        graph_ranking = sorted(graph_chunks, key=lambda n: (dist[n], n))
        fused = reciprocal_rank_fusion(
            [vector_ranking, graph_ranking],
            weights=[self.vector_weight, self.graph_weight],
        )
        # 所有图独有候选的 source_path（用于每文档限流 + 装配），按 doc_id 去重批量取
        doc_ids = {
            chunk_map[cid].doc_id
            for cid in fused
            if cid not in row_by_id and cid in chunk_map
        }
        doc_paths: dict[str, str] = {}
        for did in doc_ids:
            doc = self.graph_store.get_document(did)
            doc_paths[did] = doc.path if doc is not None else ""

        def _source(cid: str) -> str:
            if cid in row_by_id:
                return row_by_id[cid]["meta"].get("source_path", "")
            ch = chunk_map.get(cid)
            return doc_paths.get(ch.doc_id, "") if ch is not None else ""

        # 按融合分降序贪心选 top-k，每个 source_path 最多 per_doc_cap 块（严格上限）
        ordered: list[str] = []
        per_doc: dict[str, int] = {}
        for cid in sorted(fused, key=lambda c: (-fused[c], c)):
            if len(ordered) >= k:
                break
            src = _source(cid)
            if self.per_doc_cap is not None and per_doc.get(src, 0) >= self.per_doc_cap:
                continue
            ordered.append(cid)
            per_doc[src] = per_doc.get(src, 0) + 1

        contexts = [
            self._context(cid, fused[cid], row_by_id, chunk_map, doc_paths)
            for cid in ordered
        ]
        subgraph = self.graph_store.subgraph(ordered)
        return RetrievalResult(contexts=contexts, subgraph=subgraph)

    def _context(
        self,
        chunk_id: str,
        score: float,
        row_by_id: dict,
        chunk_map: dict,
        doc_paths: dict,
    ) -> Context:
        if chunk_id in row_by_id:
            r = row_by_id[chunk_id]
            return Context(
                chunk_id=chunk_id,
                text=r["text"],
                score=score,
                doc_id=doc_id_from_chunk(chunk_id),
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
        ch = chunk_map.get(chunk_id)
        if ch is None:
            return Context(
                chunk_id=chunk_id,
                text="",
                score=score,
                doc_id=doc_id_from_chunk(chunk_id),
            )
        return Context(
            chunk_id=chunk_id,
            text=ch.text,
            score=score,
            doc_id=ch.doc_id,
            source_path=doc_paths.get(ch.doc_id, ""),
            heading_path=ch.section_path,
        )
