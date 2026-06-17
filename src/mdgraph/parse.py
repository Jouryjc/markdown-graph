"""markdown → ParsedDoc：frontmatter + 标题层级 sections。链接/标签见同文件后续函数。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

SECTION_PATH_SEP = " > "

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class ParsedLink:
    raw: str
    target: str
    anchor: str | None
    kind: str  # "wiki" | "md"
    pos: int


@dataclass
class ParsedSection:
    sec_idx: int
    heading_path: str
    level: int
    parent_idx: int | None
    text: str
    char_start: int
    char_end: int
    links: list[ParsedLink] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedDoc:
    relpath: str
    frontmatter: dict
    sections: list[ParsedSection]
    warnings: list[str] = field(default_factory=list)


def parse_document(relpath: str, text: str) -> ParsedDoc:
    frontmatter, body_offset, warnings = _parse_frontmatter(text)
    sections = _split_sections(text, body_offset)
    for sec in sections:
        sec.links = _extract_links(sec.text, sec.char_start)
        sec.tags = _extract_tags(sec.text)
    return ParsedDoc(
        relpath=relpath, frontmatter=frontmatter, sections=sections, warnings=warnings
    )


def _parse_frontmatter(text: str) -> tuple[dict, int, list[str]]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, 0, []
    warnings: list[str] = []
    try:
        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            data = {}
            warnings.append("frontmatter is not a mapping; ignored")
    except yaml.YAMLError:
        data = {}
        warnings.append("frontmatter YAML parse failed; ignored")
    return data, m.end(), warnings


def _split_sections(text: str, body_offset: int) -> list[ParsedSection]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    acc = 0
    for ln in lines:
        offsets.append(acc)
        acc += len(ln)

    headings: list[tuple[int, int, str, int]] = []  # (line_idx, level, htext, char_off)
    fenced = False
    for i, ln in enumerate(lines):
        if offsets[i] < body_offset:
            continue
        if _FENCE_RE.match(ln):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING_RE.match(ln)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip(), offsets[i]))

    sections: list[ParsedSection] = []
    stack: list[tuple[int, int]] = []  # (level, sec_idx)
    htext_by_idx: dict[int, str] = {}
    sec_idx = 0

    first_h_off = headings[0][3] if headings else len(text)
    pre = text[body_offset:first_h_off]
    if pre.strip():
        sections.append(
            ParsedSection(
                sec_idx=sec_idx,
                heading_path="",
                level=0,
                parent_idx=None,
                text=pre,
                char_start=body_offset,
                char_end=body_offset + len(pre),
            )
        )
        htext_by_idx[sec_idx] = ""
        sec_idx += 1

    for hi, (line_idx, level, htext, h_off) in enumerate(headings):
        body_start = offsets[line_idx] + len(lines[line_idx])
        body_end = headings[hi + 1][3] if hi + 1 < len(headings) else len(text)
        body = text[body_start:body_end]
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_idx = stack[-1][1] if stack else None
        path_parts = [htext_by_idx[idx] for (_, idx) in stack] + [htext]
        heading_path = SECTION_PATH_SEP.join(path_parts)
        sections.append(
            ParsedSection(
                sec_idx=sec_idx,
                heading_path=heading_path,
                level=level,
                parent_idx=parent_idx,
                text=body,
                char_start=body_start,
                char_end=body_end,
            )
        )
        htext_by_idx[sec_idx] = htext
        stack.append((level, sec_idx))
        sec_idx += 1

    return sections


def _extract_links(body: str, base: int) -> list[ParsedLink]:
    return []


def _extract_tags(body: str) -> list[str]:
    return []
