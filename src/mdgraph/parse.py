"""markdown → ParsedDoc：frontmatter + 标题层级 sections。链接/标签见同文件后续函数。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

SECTION_PATH_SEP = " > "

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

_WIKI_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
_MD_RE = re.compile(r"\[([^\]\n]*)\]\(([^)\n]+)\)")
_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9][\w/-]*)")
_SKIP_URL_PREFIXES = ("http://", "https://", "mailto:", "ftp://")


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


def _mask_code(s: str) -> str:
    """把 fenced/inline 代码替换为等长空格，保持偏移不变。"""
    out = list(s)
    for m in re.finditer(r"```.*?```|~~~.*?~~~", s, re.DOTALL):
        for i in range(m.start(), m.end()):
            out[i] = " "
    masked = "".join(out)
    out2 = list(masked)
    for m in re.finditer(r"`[^`\n]+`", masked):
        for i in range(m.start(), m.end()):
            out2[i] = " "
    return "".join(out2)


def _extract_links(body: str, base: int) -> list[ParsedLink]:
    masked = _mask_code(body)
    links: list[ParsedLink] = []
    for m in _WIKI_RE.finditer(masked):
        target_part = m.group(1).split("|", 1)[0]
        if "#" in target_part:
            target, anchor = target_part.split("#", 1)
        else:
            target, anchor = target_part, None
        links.append(
            ParsedLink(
                raw=m.group(0),
                target=target.strip(),
                anchor=anchor.strip() if anchor else None,
                kind="wiki",
                pos=base + m.start(),
            )
        )
    for m in _MD_RE.finditer(masked):
        url = m.group(2).strip()
        if url.lower().startswith(_SKIP_URL_PREFIXES):
            continue
        if "#" in url:
            target, anchor = url.split("#", 1)
        else:
            target, anchor = url, None
        links.append(
            ParsedLink(
                raw=m.group(0),
                target=target.strip(),
                anchor=anchor.strip() if anchor else None,
                kind="md",
                pos=base + m.start(),
            )
        )
    links.sort(key=lambda l: l.pos)
    return links


def _extract_tags(body: str) -> list[str]:
    masked = _mask_code(body)
    seen: list[str] = []
    for m in _TAG_RE.finditer(masked):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen
