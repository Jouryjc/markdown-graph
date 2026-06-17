"""MarkdownGraph：结构索引 + 向量检索 + 语义抽取门面。"""

from __future__ import annotations

from pathlib import Path

from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.providers.base import EmbeddingProvider, LLMProvider
from mdgraph.retrieve import RetrievalResult, Retriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


class MarkdownGraph:
    def __init__(
        self,
        store_dir: str | Path,
        embedder: EmbeddingProvider | None = None,
        llm: LLMProvider | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.graph_store = GraphStore(self.store_dir / "graph.db")
        self.embedder = embedder
        self.llm = llm
        self.vector_store: VectorStore | None = None
        if embedder is not None:
            self.vector_store = VectorStore(
                self.store_dir / "vectors", model_name=embedder.name, dim=embedder.dim
            )
        self.indexer = StructuralIndexer(
            self.graph_store, vector_store=self.vector_store, embedder=embedder, llm=llm
        )

    def build(self, paths, root=None, max_chars: int = 1200, overlap: int = 150) -> IndexReport:
        paths = [Path(p) for p in paths]
        if root is None and len(paths) == 1 and paths[0].is_dir():
            root = paths[0]
        return self.indexer.index(paths, root=root, max_chars=max_chars, overlap=overlap)

    def retrieve(self, query: str, k: int = 8) -> RetrievalResult:
        if self.embedder is None or self.vector_store is None:
            raise RuntimeError("no embedder configured")
        return Retriever(self.vector_store, self.embedder).retrieve(query, k=k)

    def stats(self) -> dict[str, int]:
        s = self.graph_store.stats()
        if self.vector_store is not None:
            s["vectors"] = self.vector_store.count()
        return s

    def close(self) -> None:
        self.graph_store.close()
        if self.vector_store is not None:
            self.vector_store.close()
