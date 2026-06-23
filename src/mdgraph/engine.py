"""MarkdownGraph：结构索引 + 向量检索 + 语义抽取门面。"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.providers.base import EmbeddingProvider, LLMProvider
from mdgraph.retrieve import RetrievalResult, Retriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore

logger = logging.getLogger(__name__)


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
        # 索引时排除 store_dir/source（持久化的源副本）：避免 store 嵌在被索引根目录内时，
        # 源副本被 discover 反复纳入索引而污染图。
        self.indexer = StructuralIndexer(
            self.graph_store,
            vector_store=self.vector_store,
            embedder=embedder,
            llm=llm,
            exclude_dir=self.store_dir / "source",
        )

    def build(
        self,
        paths,
        root=None,
        max_chars: int = 1200,
        overlap: int = 150,
        incremental: bool = True,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> IndexReport:
        paths = [Path(p) for p in paths]
        if root is None and len(paths) == 1 and paths[0].is_dir():
            root = paths[0]
        report = self.indexer.index(
            paths,
            root=root,
            max_chars=max_chars,
            overlap=overlap,
            incremental=incremental,
            progress=progress,
        )
        self._persist_source(paths, root, incremental)
        return report

    def _persist_source(self, paths, root, incremental: bool) -> None:
        """把本次索引的源 .md 落到 store_dir/source/（供 File 检索在真实文件上检索）。

        与索引同一 .md 集合（复用 ingest.discover）；按相对 root 布局。
        full（incremental=False）先清空 source/ 再全量复制；incremental 覆盖写
        （删除的文件不剪枝，--full 重同步）。复制失败只记日志、不影响索引主流程。
        """
        try:
            from mdgraph.ingest import discover

            source_dir = self.store_dir / "source"
            root_path = Path(root).resolve() if root else None
            if not incremental:
                shutil.rmtree(source_dir, ignore_errors=True)
            # 与索引同一集合，且排除已持久化的源副本本身（防止 store 嵌在根内时自我复制）。
            for f in discover(paths, exclude=[source_dir]):
                try:
                    rel = f.resolve().relative_to(root_path) if root_path else Path(f.name)
                except ValueError:
                    rel = Path(f.name)
                dst = source_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        except Exception:  # noqa: BLE001 - 源持久化失败不影响索引返回；File 检索退化为空
            logger.warning("persist source markdown failed", exc_info=True)

    def retrieve_file(
        self,
        query: str,
        k: int = 8,
        retriever=None,
    ) -> RetrievalResult:
        """在 store_dir/source 上用 LLM 文件检索（独立于向量/图，不要求 embedder）。

        无 source/ 目录 → 返回空 RetrievalResult（上层据此提示重建索引）。
        """
        source_dir = self.store_dir / "source"
        if not source_dir.is_dir():
            return RetrievalResult()
        if retriever is None:
            from mdgraph.providers.file_llm_retriever import FileLLMRetriever

            retriever = FileLLMRetriever()
        return RetrievalResult(
            contexts=retriever.retrieve(query, source_dir, k=k),
            subgraph={"nodes": [], "edges": []},
        )

    def retrieve(self, query: str, k: int = 8) -> RetrievalResult:
        if self.embedder is None or self.vector_store is None:
            raise RuntimeError("no embedder configured")
        return Retriever(
            self.vector_store, self.embedder, graph_store=self.graph_store
        ).retrieve(query, k=k)

    def stats(self) -> dict[str, int]:
        s = self.graph_store.stats()
        if self.vector_store is not None:
            s["vectors"] = self.vector_store.count()
        return s

    def close(self) -> None:
        self.graph_store.close()
        if self.vector_store is not None:
            self.vector_store.close()
