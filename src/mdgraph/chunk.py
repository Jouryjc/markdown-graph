"""章节 → Chunk：章节为块；超 max_chars 才按段落切分 + overlap。"""

from __future__ import annotations

import re

from mdgraph.ids import chunk_id, doc_id as _doc_id
from mdgraph.models import Chunk
from mdgraph.parse import ParsedDoc


def chunk_sections(parsed: ParsedDoc, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    did = _doc_id(parsed.relpath)
    out: list[Chunk] = []
    for sec in parsed.sections:
        if not sec.text.strip():
            continue
        for ci, (w_start, w_text) in enumerate(_split_windows(sec.text, max_chars, overlap)):
            cs = sec.char_start + w_start
            out.append(
                Chunk(
                    id=chunk_id(did, sec.sec_idx, ci),
                    doc_id=did,
                    section_path=sec.heading_path,
                    text=w_text,
                    char_start=cs,
                    char_end=cs + len(w_text),
                )
            )
    return out


def _paragraph_spans(body: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in re.finditer(r"\n[ \t]*\n", body):
        spans.append((pos, m.end()))
        pos = m.end()
    if pos < len(body):
        spans.append((pos, len(body)))
    return spans


def _split_windows(body: str, max_chars: int, overlap: int) -> list[tuple[int, str]]:
    if len(body) <= max_chars:
        return [(0, body)]
    groups: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end: int | None = None
    for (s, e) in _paragraph_spans(body):
        if e - s > max_chars:
            if cur_start is not None:
                groups.append((cur_start, cur_end))
                cur_start = cur_end = None
            t = s
            while t < e:
                groups.append((t, min(t + max_chars, e)))
                t += max_chars
            continue
        if cur_start is None:
            cur_start, cur_end = s, e
        elif e - cur_start <= max_chars:
            cur_end = e
        else:
            groups.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    if cur_start is not None:
        groups.append((cur_start, cur_end))

    windows: list[tuple[int, str]] = []
    for i, (s, e) in enumerate(groups):
        ws = s if i == 0 else max(0, s - overlap)
        windows.append((ws, body[ws:e]))
    return windows
