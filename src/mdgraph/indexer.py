"""StructuralIndexer：把 markdown 索引成图（结构层 + 可选向量嵌入 + 可选 LLM 实体抽取）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from posixpath import dirname, join, normpath

from mdgraph.chunk import chunk_sections
from mdgraph.embed import embed_texts
from mdgraph.extract import extract_graph
from mdgraph.ids import doc_id as make_doc_id, section_id, tag_id
from mdgraph.ingest import discover, read_file
from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.parse import SECTION_PATH_SEP, ParsedDoc, parse_document
from mdgraph.store.graph_store import GraphStore


@dataclass
class IndexReport:
    indexed: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    unresolved_links: int = 0
    removed: int = 0
    entities: int = 0
    unchanged: int = 0
    reclaimed: int = 0
    warnings: list[str] = field(default_factory=list)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@dataclass
class _DocCtx:
    relpath: str
    did: str
    doc: Document
    pd: ParsedDoc
    chunks: list[Chunk]


class StructuralIndexer:
    def __init__(self, store: GraphStore, vector_store=None, embedder=None, llm=None) -> None:
        self.store = store
        self.vector_store = vector_store
        self.embedder = embedder
        self.llm = llm

    def index(
        self,
        paths,
        root=None,
        max_chars: int = 1200,
        overlap: int = 150,
        incremental: bool = True,
    ) -> IndexReport:
        report = IndexReport()
        root_path = Path(root).resolve() if root else None
        docs: list[_DocCtx] = []
        self.title_index: dict[str, str] = {}
        self.path_index: dict[str, str] = {}
        self.slug_index: dict[str, dict[str, int]] = {}

        for f in discover(paths):
            relpath = self._relpath(f, root_path)
            try:
                text, h, mtime = read_file(f)
                pd = parse_document(relpath, text)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((str(f), repr(exc)))
                continue
            did = make_doc_id(relpath)
            doc = Document(id=did, path=relpath, hash=h, mtime=mtime, frontmatter=pd.frontmatter)
            chunks = chunk_sections(pd, max_chars=max_chars, overlap=overlap)
            report.warnings.extend(pd.warnings)
            stem = Path(relpath).stem.lower()
            if stem in self.title_index:
                report.warnings.append(f"duplicate title stem: {stem}")
            else:
                self.title_index[stem] = did
            self.path_index[relpath] = did
            self.slug_index[did] = {
                _slug(sec.heading_path.split(SECTION_PATH_SEP)[-1]): sec.sec_idx
                for sec in pd.sections
                if sec.heading_path
            }
            docs.append(_DocCtx(relpath, did, doc, pd, chunks))

        # 按 content-hash 分流：unchanged 跳过，built = new/changed（全量模式下全部）
        stored = dict(self.store.list_documents())
        built: list[_DocCtx] = []
        for ctx in docs:
            if incremental and stored.get(ctx.did) == ctx.doc.hash:
                report.unchanged += 1
            else:
                built.append(ctx)

        # reconcile：用全部 discovered（unchanged 不算 removed）
        discovered = {ctx.did for ctx in docs}
        for stored_id, _ in stored.items():
            if stored_id not in discovered:
                self._purge_vectors(stored_id)
                self.store.delete_document(stored_id)
                report.removed += 1

        for ctx in built:
            try:
                self._build_doc(ctx, report)
                report.indexed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append((ctx.relpath, repr(exc)))

        # Pass 3: 仅对 built 解析跨文档链接（unchanged doc 的链接原样保留）
        for ctx in built:
            if any(r for r in report.errors if r[0] == ctx.relpath):
                continue
            try:
                with self.store.transaction():
                    chunks_by_sec = self._make_chunks_by_sec(ctx)
                    self._build_links(ctx, chunks_by_sec, report)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((ctx.relpath, repr(exc)))

        if self.vector_store is not None and self.embedder is not None:
            self._embed_and_store(built, report)
        if self.llm is not None:
            self._extract_and_store(built, report)

        # 孤儿回收：在 reconcile + build + extract 之后，确保不误删待重建的实体
        report.reclaimed = self.store.reclaim_orphans()
        return report

    def _relpath(self, f: Path, root: Path | None) -> str:
        if root:
            try:
                return f.resolve().relative_to(root).as_posix()
            except ValueError:
                return f.as_posix()
        return f.as_posix()

    def _build_doc(self, ctx: _DocCtx, report: IndexReport) -> None:
        did, pd, chunks = ctx.did, ctx.pd, ctx.chunks
        self._purge_vectors(did)
        with self.store.transaction():
            self.store.delete_document(did, commit=False)
            self.store.upsert_document(ctx.doc, commit=False)
            self.store.upsert_node(
                Node(id=did, type=NodeType.DOCUMENT, doc_id=did, meta={"path": ctx.doc.path}),
                commit=False,
            )
            for sec in pd.sections:
                sid = section_id(did, sec.sec_idx)
                self.store.upsert_node(
                    Node(
                        id=sid,
                        type=NodeType.SECTION,
                        doc_id=did,
                        meta={"heading_path": sec.heading_path, "level": sec.level},
                    ),
                    commit=False,
                )
                if sec.parent_idx is None:
                    self.store.upsert_edge(Edge(src=did, dst=sid, type=EdgeType.CONTAINS), commit=False)
                else:
                    self.store.upsert_edge(
                        Edge(src=section_id(did, sec.parent_idx), dst=sid, type=EdgeType.CONTAINS),
                        commit=False,
                    )

            chunks_by_sec: dict[int, list[Chunk]] = {}
            for ch in chunks:
                sidx = self._section_idx_for_pos(pd, ch.char_start)
                self.store.upsert_chunk(ch, commit=False)
                self.store.upsert_node(
                    Node(id=ch.id, type=NodeType.CHUNK, doc_id=did, meta={"section_path": ch.section_path}),
                    commit=False,
                )
                self.store.upsert_edge(
                    Edge(src=section_id(did, sidx), dst=ch.id, type=EdgeType.CONTAINS), commit=False
                )
                chunks_by_sec.setdefault(sidx, []).append(ch)

            self._build_tags(did, pd, chunks_by_sec)

    def _section_idx_for_pos(self, pd: ParsedDoc, pos: int) -> int:
        for sec in pd.sections:
            if sec.char_start <= pos < sec.char_end:
                return sec.sec_idx
        return pd.sections[0].sec_idx if pd.sections else 0

    def _build_tags(self, did: str, pd: ParsedDoc, chunks_by_sec: dict[int, list[Chunk]]) -> None:
        fm_tags = pd.frontmatter.get("tags") or []
        if isinstance(fm_tags, str):
            fm_tags = [fm_tags]
        for t in fm_tags:
            tname = str(t)
            tid = tag_id(tname)
            self.store.upsert_node(Node(id=tid, type=NodeType.TAG, meta={"name": tname}), commit=False)
            self.store.upsert_edge(Edge(src=did, dst=tid, type=EdgeType.TAGGED), commit=False)
        for sec in pd.sections:
            secs = chunks_by_sec.get(sec.sec_idx)
            if not secs:
                continue
            for tname in sec.tags:
                tid = tag_id(tname)
                self.store.upsert_node(Node(id=tid, type=NodeType.TAG, meta={"name": tname}), commit=False)
                self.store.upsert_edge(Edge(src=secs[0].id, dst=tid, type=EdgeType.TAGGED), commit=False)

    def _make_chunks_by_sec(self, ctx: _DocCtx) -> dict[int, list[Chunk]]:
        chunks_by_sec: dict[int, list[Chunk]] = {}
        for ch in ctx.chunks:
            sidx = self._section_idx_for_pos(ctx.pd, ch.char_start)
            chunks_by_sec.setdefault(sidx, []).append(ch)
        return chunks_by_sec

    def _build_links(self, ctx: _DocCtx, chunks_by_sec: dict[int, list[Chunk]], report: IndexReport) -> None:
        for sec in ctx.pd.sections:
            secs = chunks_by_sec.get(sec.sec_idx)
            if not secs:
                continue
            for link in sec.links:
                src = self._chunk_for_pos(secs, link.pos)
                target = self._resolve_link(link, ctx.relpath, ctx.did)
                if target is None:
                    report.unresolved_links += 1
                    node = self.store.get_node(src.id)
                    meta = node.meta if node else {"section_path": src.section_path}
                    meta.setdefault("unresolved_links", []).append(link.raw)
                    self.store.upsert_node(
                        Node(id=src.id, type=NodeType.CHUNK, doc_id=ctx.did, meta=meta), commit=False
                    )
                else:
                    self.store.upsert_edge(
                        Edge(src=src.id, dst=target, type=EdgeType.LINKS_TO), commit=False
                    )

    def _purge_vectors(self, doc_id: str) -> None:
        # Intentionally outside the graph transaction: vectors are a derived
        # index, and the next build re-syncs if a per-doc graph txn rolls back.
        if self.vector_store is None:
            return
        ids = [c.id for c in self.store.list_chunks_by_doc(doc_id)]
        if ids:
            self.vector_store.delete(ids)

    def _embed_and_store(self, docs: list["_DocCtx"], report: IndexReport) -> None:
        errored = {r[0] for r in report.errors}
        chunk_ids: list[str] = []
        texts: list[str] = []
        metas: list[dict] = []
        for ctx in docs:
            if ctx.relpath in errored:
                report.warnings.append(f"skipped embedding for errored doc: {ctx.relpath}")
                continue
            for ch in ctx.chunks:
                chunk_ids.append(ch.id)
                texts.append(ch.text)
                metas.append(
                    {"source_path": ctx.doc.path, "heading_path": ch.section_path}
                )
        if not chunk_ids:
            return
        vectors = embed_texts(self.embedder, texts)
        self.vector_store.add(chunk_ids, vectors, texts, metas)

    def _extract_and_store(self, docs: list["_DocCtx"], report: IndexReport) -> None:
        errored = {r[0] for r in report.errors}
        chunks: list[tuple[str, str]] = []
        for ctx in docs:
            if ctx.relpath in errored:
                report.warnings.append(f"skipped extraction for errored doc: {ctx.relpath}")
                continue
            for ch in ctx.chunks:
                chunks.append((ch.id, ch.text))
        if not chunks:
            return
        bundle = extract_graph(chunks, self.llm)
        for cid in bundle.failed_chunks:
            report.warnings.append(f"entity extraction failed for chunk: {cid}")
        with self.store.transaction():
            for ent in bundle.entities:
                self.store.upsert_node(
                    Node(
                        id=ent.id,
                        type=NodeType.ENTITY,
                        doc_id=None,
                        meta={
                            "name": ent.name,
                            "type": ent.type,
                            "description": ent.description,
                            "aliases": ent.aliases,
                        },
                    ),
                    commit=False,
                )
            for chunk_id, eid in bundle.mentions:
                self.store.upsert_edge(
                    Edge(src=chunk_id, dst=eid, type=EdgeType.MENTIONS), commit=False
                )
            for sid, tid, rtype in bundle.relations:
                self.store.upsert_edge(
                    Edge(src=sid, dst=tid, type=EdgeType.RELATES_TO, meta={"type": rtype}),
                    commit=False,
                )
        report.entities += len(bundle.entities)

    def _chunk_for_pos(self, chunks: list[Chunk], pos: int) -> Chunk:
        for ch in chunks:
            if ch.char_start <= pos < ch.char_end:
                return ch
        return chunks[0]

    def _resolve_link(self, link, src_relpath: str, src_did: str) -> str | None:
        if link.kind == "wiki":
            tdid = src_did if not link.target else self.title_index.get(link.target.lower())
        else:
            tdid = src_did if not link.target else self._resolve_path(link.target, src_relpath)
        if tdid is None:
            return None
        if link.anchor:
            sidx = self._section_for_anchor(tdid, link.anchor)
            if sidx is not None:
                return section_id(tdid, sidx)
            return tdid
        return tdid

    def _resolve_path(self, target: str, src_relpath: str) -> str | None:
        cand = normpath(join(dirname(src_relpath), target))
        if cand in self.path_index:
            return self.path_index[cand]
        return self.path_index.get(normpath(target))

    def _section_for_anchor(self, tdid: str, anchor: str) -> int | None:
        return self.slug_index.get(tdid, {}).get(_slug(anchor))
