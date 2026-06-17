"""向量检索：查询 embedding → 向量搜索 → 距离转相似度 → 上下文。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.providers.base import EmbeddingProvider
from mdgraph.store.vector_store import VectorStore


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
    def __init__(self, vector_store: VectorStore, embedder: EmbeddingProvider) -> None:
        self.vector_store = vector_store
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 8) -> RetrievalResult:
        if not query.strip():
            return RetrievalResult()
        qvec = self.embedder.embed([query])[0]
        rows = self.vector_store.search(qvec, k=k)
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
