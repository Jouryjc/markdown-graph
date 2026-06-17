"""StructuralIndexer：两遍法把 markdown 索引成结构图（无 LLM）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mdgraph.chunk import chunk_sections
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
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def index(self, paths, root=None, max_chars: int = 1200, overlap: int = 150) -> IndexReport:
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

        for ctx in docs:
            try:
                self._build_doc(ctx, report)
                report.indexed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append((ctx.relpath, repr(exc)))
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
            self._build_links(ctx, chunks_by_sec, report)

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

    def _build_links(self, ctx: _DocCtx, chunks_by_sec: dict[int, list[Chunk]], report: IndexReport) -> None:
        # 链接在 Task 8 实现
        return
