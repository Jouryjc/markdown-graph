"""MarkdownGraph：结构索引 + 向量检索 + 语义抽取门面。"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from mdgraph.ids import entity_id, normalize_name, sag_event_id
from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.providers.base import EmbeddingProvider, LLMProvider
from mdgraph.retrieve import RetrievalResult, Retriever
from mdgraph.sag_retrieve import SAGResult, SAGRetriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.sag_store import SAGStore
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
        self.sag_store = SAGStore(self.store_dir / "sag.db")
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

    def build_sag_index(
        self,
        extractor=None,
        embedder: EmbeddingProvider | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        full: bool = False,
    ) -> dict:
        """遍历既有 chunk 抽 SAG 事件/实体层，落到 store_dir/sag.db。

        embedder 可选（无 embedder 时事件不存向量，检索退化为实体匹配 + 重叠排序）。
        提取失败的 chunk 计入 failed，不抛、不影响其余。full=True 先清空全表（重建）。
        返回 {events, entities, links, failed}。
        """
        if extractor is None:
            from mdgraph.providers.sag_extractor import SAGExtractor

            extractor = SAGExtractor()
        embedder = embedder if embedder is not None else self.embedder

        if full:
            self.sag_store.clear()

        docs = self.graph_store.list_documents()
        doc_chunks: list[tuple[str, str, list]] = []
        total = 0
        for doc_id, _hash in docs:
            doc = self.graph_store.get_document(doc_id)
            title = Path(doc.path).stem if doc is not None else ""
            chunks = self.graph_store.list_chunks_by_doc(doc_id)
            doc_chunks.append((doc_id, title, chunks))
            total += len(chunks)

        failed = 0
        done = 0
        if progress is not None:
            progress("sag", done, total)
        for doc_id, title, chunks in doc_chunks:
            for chunk in chunks:
                ev = extractor.extract_event(
                    chunk.text, heading=chunk.section_path, doc_title=title
                )
                if ev is None:
                    failed += 1
                    done += 1
                    if progress is not None:
                        progress("sag", done, total)
                    continue
                event_id = sag_event_id(chunk.id)
                embedding = (
                    embedder.embed([ev.content])[0]
                    if embedder is not None and ev.content
                    else None
                )
                with self.sag_store.transaction():
                    # 增量先清旧（按 chunk_id），再写新事件。
                    self.sag_store.delete_event_by_chunk(chunk.id, commit=False)
                    self.sag_store.upsert_event(
                        id=event_id,
                        doc_id=doc_id,
                        chunk_id=chunk.id,
                        title=ev.title,
                        summary=ev.summary,
                        content=ev.content,
                        category=ev.category,
                        keywords=ev.keywords,
                        embedding=embedding,
                        commit=False,
                    )
                    seen_eids: set[str] = set()
                    for ent in ev.entities:
                        eid = entity_id(ent.name)
                        if eid in seen_eids:
                            continue
                        seen_eids.add(eid)
                        self.sag_store.upsert_entity(
                            id=eid,
                            type=ent.type,
                            name=ent.name,
                            normalized_name=normalize_name(ent.name),
                            description=ent.description,
                            commit=False,
                        )
                        self.sag_store.link(event_id, eid, commit=False)
                done += 1
                if progress is not None:
                    progress("sag", done, total)

        counts = self.sag_store.counts()
        return {
            "events": counts["events"],
            "entities": counts["entities"],
            "links": counts["links"],
            "failed": failed,
        }

    def retrieve_sag(
        self,
        query: str,
        k: int = 8,
        max_hops: int = 2,
        retriever=None,
    ) -> SAGResult:
        """SAG 事件/实体检索；空 store → 空结果；补 source_path/heading_path。"""
        if self.sag_store.counts()["events"] == 0:
            return SAGResult()
        if retriever is None:
            retriever = SAGRetriever(self.sag_store, embedder=self.embedder)
        result = retriever.retrieve(query, k=k, max_hops=max_hops)
        # 补源 chunk 元信息：source_path(doc.path)、heading_path(chunk.section_path)。
        chunk_ids = [hit.chunk_id for hit in result.events if hit.chunk_id]
        chunk_map = self.graph_store.get_chunks(chunk_ids)
        doc_paths: dict[str, str] = {}
        for hit in result.events:
            ch = chunk_map.get(hit.chunk_id)
            if ch is None:
                continue
            if ch.doc_id not in doc_paths:
                doc = self.graph_store.get_document(ch.doc_id)
                doc_paths[ch.doc_id] = doc.path if doc is not None else ""
            hit.source_path = doc_paths[ch.doc_id]
            hit.heading_path = ch.section_path
            if not hit.content:
                hit.content = ch.text
        return result

    def stats(self) -> dict[str, int]:
        s = self.graph_store.stats()
        if self.vector_store is not None:
            s["vectors"] = self.vector_store.count()
        return s

    def close(self) -> None:
        self.graph_store.close()
        self.sag_store.close()
        if self.vector_store is not None:
            self.vector_store.close()
