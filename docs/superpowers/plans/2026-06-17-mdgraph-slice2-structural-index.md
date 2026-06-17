# mdgraph 切片 2：端到端结构索引 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把任意数量 markdown 文件解析、分块、建成结构图谱（Document/Section/Chunk/Tag 节点 + CONTAINS/LINKS_TO/TAGGED 边）并落 GraphStore，提供 `MarkdownGraph.build()` 门面，全部带通过的测试。

**Architecture:** 纯结构、无 LLM。`ids`/`ingest`/`parse`/`chunk` 是无副作用的纯函数模块；`StructuralIndexer` 用两遍法编排（pass1 发现+解析+建 title/path/anchor 索引，pass2 逐文档在事务内建点建边）；`MarkdownGraph` 门面包 GraphStore + indexer。GraphStore 增补事务/批量提交与按文档读访问器。

**Tech Stack:** Python 3.11+、markdown 解析用正则+行扫描（标题/链接/标签，代码块屏蔽）、PyYAML（frontmatter）、pydantic 模型、networkx（已有）、pytest。

> 父 spec：`docs/superpowers/specs/2026-06-17-mdgraph-slice2-structural-index-design.md`。基于切片 1（已在 main）。

---

## 文件结构

- `src/mdgraph/ids.py` — 确定性 ID 生成（无引号）。
- `src/mdgraph/ingest.py` — 发现/读取 md + content-hash。
- `src/mdgraph/parse.py` — `parse_document` → `ParsedDoc`（frontmatter + sections + links + tags）。
- `src/mdgraph/chunk.py` — `chunk_sections` → `list[Chunk]`。
- `src/mdgraph/indexer.py` — `StructuralIndexer` + `IndexReport`。
- `src/mdgraph/engine.py` — `MarkdownGraph` 门面。
- `src/mdgraph/store/graph_store.py` — 增补 `transaction()`、`commit` 参数、`list_chunks_by_doc`、`list_documents`。
- `src/mdgraph/__init__.py` — 导出 `MarkdownGraph`。
- `pyproject.toml` — 增 `pyyaml` 依赖。
- 对应 `tests/`。

---

## Task 1: ids.py 确定性 ID

**Files:**
- Create: `src/mdgraph/ids.py`
- Test: `tests/test_ids.py`

- [ ] **Step 1: 写失败测试** — `tests/test_ids.py`:

```python
import re

from mdgraph.ids import chunk_id, doc_id, section_id, tag_id

_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


def test_doc_id_is_deterministic_and_quote_free():
    a = doc_id("notes/a.md")
    assert a == doc_id("notes/a.md")
    assert a != doc_id("notes/b.md")
    assert a.startswith("d_")
    assert _SAFE.match(a)


def test_section_and_chunk_id_format():
    d = doc_id("a.md")
    assert section_id(d, 2) == f"{d}_s2"
    assert chunk_id(d, 2, 0) == f"{d}_s2_c0"
    assert _SAFE.match(chunk_id(d, 2, 0))


def test_tag_id_is_case_insensitive_and_quote_free():
    assert tag_id("Foo") == tag_id("foo")
    assert tag_id("foo").startswith("t_")
    assert _SAFE.match(tag_id("foo/bar"))
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_ids.py -v` → FAIL (No module named 'mdgraph.ids').

- [ ] **Step 3: 写实现** — `src/mdgraph/ids.py`:

```python
"""确定性 ID 生成：全部由 hex / 下划线 / 数字组成，无引号。"""

from __future__ import annotations

import hashlib


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def doc_id(relpath: str) -> str:
    return "d_" + _h(relpath)


def section_id(doc_id: str, sec_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}"


def chunk_id(doc_id: str, sec_idx: int, chunk_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}_c{chunk_idx}"


def tag_id(name: str) -> str:
    return "t_" + _h(name.lower())
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_ids.py -v` → PASS (3 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/ids.py tests/test_ids.py
git commit -m "feat: add deterministic id helpers"
```

---

## Task 2: GraphStore 事务/批量 + 读访问器

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`
- Test: `tests/test_graph_store_batch.py`

- [ ] **Step 1: 写失败测试** — `tests/test_graph_store_batch.py`:

```python
import pytest

from mdgraph.models import Chunk, Document, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_transaction_commits_once_on_success(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    with store.transaction():
        store.upsert_document(
            Document(id="d1", path="a.md", hash="h", mtime=1.0), commit=False
        )
        store.upsert_node(Node(id="n1", type=NodeType.CHUNK, doc_id="d1"), commit=False)
    assert store.get_document("d1") is not None
    assert store.get_node("n1") is not None
    store.close()


def test_transaction_rolls_back_on_exception(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_document(
                Document(id="d1", path="a.md", hash="h", mtime=1.0), commit=False
            )
            raise RuntimeError("boom")
    assert store.get_document("d1") is None
    store.close()


def test_list_chunks_by_doc(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_chunk(Chunk(id="d1_s0_c0", doc_id="d1", section_path="A", text="x", char_start=0, char_end=1))
    store.upsert_chunk(Chunk(id="d1_s0_c1", doc_id="d1", section_path="A", text="y", char_start=1, char_end=2))
    store.upsert_chunk(Chunk(id="d2_s0_c0", doc_id="d2", section_path="B", text="z", char_start=0, char_end=1))
    got = store.list_chunks_by_doc("d1")
    assert [c.id for c in got] == ["d1_s0_c0", "d1_s0_c1"]
    store.close()


def test_list_documents_returns_id_and_hash(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_document(Document(id="d1", path="a.md", hash="h1", mtime=1.0))
    store.upsert_document(Document(id="d2", path="b.md", hash="h2", mtime=1.0))
    assert sorted(store.list_documents()) == [("d1", "h1"), ("d2", "h2")]
    store.close()
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_graph_store_batch.py -v` → FAIL (transaction/commit kw/list_* 不存在)。

- [ ] **Step 3a: 给 5 个写方法加 `commit` 参数** — 在 `src/mdgraph/store/graph_store.py` 中做这些精确替换：

`upsert_document`:
```python
    def upsert_document(self, doc: Document, commit: bool = True) -> None:
```
其方法体末尾：
```python
        if commit:
            self.conn.commit()
```
（替换原来无条件的 `self.conn.commit()`）

`upsert_node`:
```python
    def upsert_node(self, node: Node, commit: bool = True) -> None:
```
末尾改为：
```python
        if commit:
            self.conn.commit()
```

`upsert_edge`:
```python
    def upsert_edge(self, edge: Edge, commit: bool = True) -> None:
```
末尾改为：
```python
        if commit:
            self.conn.commit()
```

`upsert_chunk`:
```python
    def upsert_chunk(self, chunk: Chunk, commit: bool = True) -> None:
```
末尾改为：
```python
        if commit:
            self.conn.commit()
```

`delete_document`:
```python
    def delete_document(self, doc_id: str, commit: bool = True) -> None:
```
其方法体末尾的 `self.conn.commit()` 改为：
```python
        if commit:
            self.conn.commit()
```

- [ ] **Step 3b: 加 import 与新方法** — 在 `graph_store.py` 顶部 import 区加：

```python
from contextlib import contextmanager
```

在 `stats` 方法之前插入：

```python
    @contextmanager
    def transaction(self):
        """批量写：块内用 commit=False，退出时一次提交；异常回滚。"""
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def list_chunks_by_doc(self, doc_id: str) -> list[Chunk]:
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY id", (doc_id,)
        ).fetchall()
        return [
            Chunk(
                id=r["id"],
                doc_id=r["doc_id"],
                section_path=r["section_path"],
                text=r["text"],
                char_start=r["char_start"],
                char_end=r["char_end"],
            )
            for r in rows
        ]

    def list_documents(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT id, hash FROM documents ORDER BY id"
        ).fetchall()
        return [(r["id"], r["hash"]) for r in rows]
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_graph_store_batch.py -v` → PASS (4 个)。再跑全套 `pytest -v` 确认旧测试不受影响（commit 默认 True 向后兼容）。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_batch.py
git commit -m "feat: add GraphStore transaction/batch commit and list accessors"
```

---

## Task 3: ingest.py 发现与读取

**Files:**
- Create: `src/mdgraph/ingest.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: 写失败测试** — `tests/test_ingest.py`:

```python
from mdgraph.ingest import discover, read_file


def test_discover_finds_md_recursively_sorted(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
    found = discover([tmp_path])
    names = [p.name for p in found]
    assert names == ["a.md", "b.md"]


def test_discover_dedupes_and_accepts_files(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("a", encoding="utf-8")
    found = discover([f, f, tmp_path])
    assert len([p for p in found if p.name == "a.md"]) == 1


def test_read_file_returns_text_hash_mtime(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")
    text, h, mtime = read_file(f)
    assert text == "hello"
    assert len(h) == 64  # sha256 hex
    assert h == read_file(f)[1]  # stable
    assert isinstance(mtime, float)
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_ingest.py -v` → FAIL (No module named 'mdgraph.ingest').

- [ ] **Step 3: 写实现** — `src/mdgraph/ingest.py`:

```python
"""发现与读取 markdown 文件。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def discover(paths: list[str | Path]) -> list[Path]:
    """递归收集 .md 文件，按路径排序、去重（按 resolve 后的真实路径）。"""
    out: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    out.append(f)
        elif p.is_file() and p.suffix == ".md":
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append(p)
    return out


def read_file(path: str | Path) -> tuple[str, str, float]:
    """返回 (text, sha256_hex, mtime)。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    mtime = path.stat().st_mtime
    return text, h, mtime
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_ingest.py -v` → PASS (3 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/ingest.py tests/test_ingest.py
git commit -m "feat: add markdown file discovery and reading"
```

---

## Task 4: parse.py 结构（frontmatter + sections）

**Files:**
- Modify: `pyproject.toml`（加 `pyyaml` 依赖）
- Create: `src/mdgraph/parse.py`
- Test: `tests/test_parse_structure.py`

- [ ] **Step 1: 加依赖并安装** — 在 `pyproject.toml` 的 `dependencies` 列表里加一行 `"pyyaml>=6.0",`（在 `"pyarrow>=14.0",` 之后）。然后运行 `pip install -e ".[dev]"`（装上 pyyaml）。

- [ ] **Step 2: 写失败测试** — `tests/test_parse_structure.py`:

```python
from mdgraph.parse import SECTION_PATH_SEP, parse_document


def test_headings_build_sections_with_path_and_parent():
    text = "# A\n\nhello\n\n## B\n\nworld\n"
    pd = parse_document("a.md", text)
    assert [s.heading_path for s in pd.sections] == ["A", f"A{SECTION_PATH_SEP}B"]
    b = pd.sections[1]
    assert b.level == 2
    assert b.parent_idx == 0
    assert "world" in b.text


def test_preamble_before_first_heading_becomes_level0_section():
    text = "intro text\n\n# A\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.sections[0].level == 0
    assert pd.sections[0].heading_path == ""
    assert "intro text" in pd.sections[0].text


def test_heading_inside_fenced_code_is_not_a_section():
    text = "# Real\n\n```\n# not a heading\n```\n\nafter\n"
    pd = parse_document("a.md", text)
    assert [s.heading_path for s in pd.sections] == ["Real"]


def test_frontmatter_parsed_and_excluded_from_body():
    text = "---\ntitle: T\ntags:\n  - x\n  - y\n---\n# H\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.frontmatter["title"] == "T"
    assert pd.frontmatter["tags"] == ["x", "y"]
    assert [s.heading_path for s in pd.sections] == ["H"]


def test_broken_frontmatter_is_ignored_with_warning():
    text = "---\n: : bad: [\n---\n# H\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.frontmatter == {}
    assert pd.warnings
```

- [ ] **Step 3: 运行确认失败** — `pytest tests/test_parse_structure.py -v` → FAIL (No module named 'mdgraph.parse').

- [ ] **Step 4: 写实现** — `src/mdgraph/parse.py`（本任务含 `_extract_links`/`_extract_tags` 的**空桩**，Task 5 再填充）:

```python
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
```

- [ ] **Step 5: 运行确认通过** — `pytest tests/test_parse_structure.py -v` → PASS (5 个)。

- [ ] **Step 6: 提交**:

```bash
git add pyproject.toml src/mdgraph/parse.py tests/test_parse_structure.py
git commit -m "feat: parse markdown frontmatter and heading sections"
```

---

## Task 5: parse.py 链接与标签提取

**Files:**
- Modify: `src/mdgraph/parse.py`（替换 `_extract_links` 与 `_extract_tags` 桩，加正则与 `_mask_code`）
- Test: `tests/test_parse_links_tags.py`

- [ ] **Step 1: 写失败测试** — `tests/test_parse_links_tags.py`:

```python
from mdgraph.parse import parse_document


def _links(pd):
    out = []
    for s in pd.sections:
        out.extend(s.links)
    return out


def test_wiki_links_with_alias_and_anchor():
    text = "# H\n\nsee [[Other Note]] and [[Doc#Sec|alias]] here\n"
    pd = parse_document("a.md", text)
    links = _links(pd)
    wiki = [l for l in links if l.kind == "wiki"]
    assert (wiki[0].target, wiki[0].anchor) == ("Other Note", None)
    assert (wiki[1].target, wiki[1].anchor) == ("Doc", "Sec")


def test_md_links_local_only_and_anchor_split():
    text = "# H\n\n[a](b/c.md) [x](https://e.com) [s](d.md#part)\n"
    pd = parse_document("a.md", text)
    md = [l for l in _links(pd) if l.kind == "md"]
    assert [(l.target, l.anchor) for l in md] == [("b/c.md", None), ("d.md", "part")]


def test_links_inside_code_are_ignored():
    text = "# H\n\nreal [[Real]] but `[[code]]` and\n```\n[[fenced]](x.md)\n```\n"
    pd = parse_document("a.md", text)
    targets = [l.target for l in _links(pd)]
    assert targets == ["Real"]


def test_tags_extracted_excluding_code():
    text = "# H\n\n#alpha and #beta/sub not `#code`\n"
    pd = parse_document("a.md", text)
    tags = []
    for s in pd.sections:
        tags.extend(s.tags)
    assert tags == ["alpha", "beta/sub"]


def test_link_pos_is_absolute_offset():
    text = "# H\n\nXX [[T]]\n"
    pd = parse_document("a.md", text)
    link = _links(pd)[0]
    assert text[link.pos : link.pos + 5] == "[[T]]"
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_parse_links_tags.py -v` → FAIL (桩返回 [])。

- [ ] **Step 3: 替换桩函数实现** — 在 `src/mdgraph/parse.py` 中，把 `_extract_links` 与 `_extract_tags` 两个桩替换为下面内容（并在文件中新增这些模块级正则常量，放在 `_FENCE_RE` 之后）：

```python
_WIKI_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
_MD_RE = re.compile(r"\[([^\]\n]*)\]\(([^)\n]+)\)")
_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9][\w/-]*)")
_SKIP_URL_PREFIXES = ("http://", "https://", "mailto:", "ftp://")


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
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_parse_links_tags.py -v` → PASS (5 个)。再跑 `pytest tests/test_parse_structure.py -v` 确认结构测试仍过。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/parse.py tests/test_parse_links_tags.py
git commit -m "feat: extract wiki/md links and tags from markdown"
```

---

## Task 6: chunk.py 分块

**Files:**
- Create: `src/mdgraph/chunk.py`
- Test: `tests/test_chunk.py`

- [ ] **Step 1: 写失败测试** — `tests/test_chunk.py`:

```python
from mdgraph.chunk import chunk_sections
from mdgraph.ids import doc_id
from mdgraph.parse import parse_document


def test_section_becomes_single_chunk_when_small():
    pd = parse_document("a.md", "# A\n\nshort body\n")
    chunks = chunk_sections(pd)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.doc_id == doc_id("a.md")
    assert c.id == f"{doc_id('a.md')}_s0_c0"
    assert "short body" in c.text
    # char range maps back to original
    assert pd.sections[0].text == c.text


def test_empty_section_produces_no_chunk():
    pd = parse_document("a.md", "# A\n## B\n\nbody\n")
    # section A has no body text (immediately followed by ##) -> no chunk
    chunks = chunk_sections(pd)
    paths = {c.section_path for c in chunks}
    assert "A" not in paths  # A had no body


def test_oversized_section_splits_with_overlap():
    para1 = "x" * 40
    para2 = "y" * 40
    pd = parse_document("a.md", f"# A\n\n{para1}\n\n{para2}\n")
    chunks = chunk_sections(pd, max_chars=50, overlap=10)
    assert len(chunks) >= 2
    # windows are contiguous slices of the section body (offsets exact)
    body = pd.sections[0].text
    for c in chunks:
        local_start = c.char_start - pd.sections[0].char_start
        assert body[local_start : local_start + len(c.text)] == c.text


def test_oversized_single_paragraph_hard_splits():
    big = "z" * 130
    pd = parse_document("a.md", f"# A\n\n{big}\n")
    chunks = chunk_sections(pd, max_chars=50, overlap=0)
    assert len(chunks) == 3  # 130 / 50 -> 50,50,30
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_chunk.py -v` → FAIL (No module named 'mdgraph.chunk').

- [ ] **Step 3: 写实现** — `src/mdgraph/chunk.py`:

```python
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
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_chunk.py -v` → PASS (4 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/chunk.py tests/test_chunk.py
git commit -m "feat: add heading-aware chunking with oversize splitting"
```

---

## Task 7: indexer 结构建图 + MarkdownGraph 门面

**Files:**
- Create: `src/mdgraph/indexer.py`
- Create: `src/mdgraph/engine.py`
- Modify: `src/mdgraph/__init__.py`（导出 `MarkdownGraph`）
- Test: `tests/test_indexer_structure.py`

本任务建：Document/Section/Chunk/Tag 节点 + CONTAINS + TAGGED 边（**LINKS_TO 在 Task 8**，`_build_links` 先留空桩）。

- [ ] **Step 1: 写失败测试** — `tests/test_indexer_structure.py`:

```python
from mdgraph.engine import MarkdownGraph
from mdgraph.ids import doc_id, tag_id
from mdgraph.models import EdgeType, NodeType


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_build_creates_document_section_chunk_nodes(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n\n## Sub\n\nmore\n")
    store_dir = tmp_path / ".mdgraph"
    mg = MarkdownGraph(store_dir)
    report = mg.build([tmp_path])
    assert report.indexed == 1
    g = mg.graph_store.to_networkx()
    types = sorted({d["type"] for _, d in g.nodes(data=True)})
    assert NodeType.DOCUMENT.value in types
    assert NodeType.SECTION.value in types
    assert NodeType.CHUNK.value in types
    mg.close()


def test_contains_edges_link_doc_section_chunk(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    did = doc_id("a.md")
    contains = edges_of(mg.graph_store, EdgeType.CONTAINS)
    # Document -> Section(0)
    assert (did, f"{did}_s0") in contains
    # Section(0) -> its chunk
    assert (f"{did}_s0", f"{did}_s0_c0") in contains
    mg.close()


def test_frontmatter_and_inline_tags_create_tagged_edges(tmp_path):
    write(tmp_path, "a.md", "---\ntags:\n  - proj\n---\n# A\n\nhas #inline tag\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    did = doc_id("a.md")
    tagged = edges_of(mg.graph_store, EdgeType.TAGGED)
    assert (did, tag_id("proj")) in tagged  # frontmatter tag on document
    assert any(v == tag_id("inline") for _, v in tagged)  # inline tag on a chunk
    mg.close()


def test_rebuild_is_idempotent(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    s1 = mg.stats()
    mg.build([tmp_path])
    s2 = mg.stats()
    assert s1 == s2
    mg.close()
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_indexer_structure.py -v` → FAIL (No module named 'mdgraph.engine').

- [ ] **Step 3a: 写 indexer** — `src/mdgraph/indexer.py`:

```python
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

        # Pass 1: discover + parse
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

        # Pass 2: build graph
        for ctx in docs:
            self._build_doc(ctx, report)
            report.indexed += 1
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
```

- [ ] **Step 3b: 写门面** — `src/mdgraph/engine.py`:

```python
"""MarkdownGraph：结构索引门面（检索能力在后续切片扩展）。"""

from __future__ import annotations

from pathlib import Path

from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.store.graph_store import GraphStore


class MarkdownGraph:
    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.graph_store = GraphStore(self.store_dir / "graph.db")
        self.indexer = StructuralIndexer(self.graph_store)

    def build(self, paths, root=None, max_chars: int = 1200, overlap: int = 150) -> IndexReport:
        paths = [Path(p) for p in paths]
        if root is None and len(paths) == 1 and paths[0].is_dir():
            root = paths[0]
        return self.indexer.index(paths, root=root, max_chars=max_chars, overlap=overlap)

    def stats(self) -> dict[str, int]:
        return self.graph_store.stats()

    def close(self) -> None:
        self.graph_store.close()
```

- [ ] **Step 3c: 导出门面** — 在 `src/mdgraph/__init__.py` 的 import 区加 `from mdgraph.engine import MarkdownGraph`，并把 `"MarkdownGraph"` 加进 `__all__`。

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_indexer_structure.py -v` → PASS (4 个)。再跑全套 `pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/indexer.py src/mdgraph/engine.py src/mdgraph/__init__.py tests/test_indexer_structure.py
git commit -m "feat: structural indexer (nodes, CONTAINS, TAGGED) + MarkdownGraph facade"
```

---

## Task 8: 链接解析（LINKS_TO + anchor + 悬挂）

**Files:**
- Modify: `src/mdgraph/indexer.py`（实现 `_build_links` 及其辅助方法）
- Test: `tests/test_indexer_links.py`

- [ ] **Step 1: 写失败测试** — `tests/test_indexer_links.py`:

```python
from mdgraph.engine import MarkdownGraph
from mdgraph.ids import doc_id, section_id
from mdgraph.models import EdgeType, NodeType


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_wiki_link_resolves_to_target_document(tmp_path):
    write(tmp_path, "a.md", "# A\n\nlink to [[b]]\n")
    write(tmp_path, "b.md", "# B\n\nhi\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    bdid = doc_id("b.md")
    assert any(v == bdid for _, v in links)
    mg.close()


def test_md_relative_link_resolves(tmp_path):
    write(tmp_path, "a.md", "# A\n\nsee [b](sub/b.md)\n")
    write(tmp_path, "sub/b.md", "# B\n\nhi\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    assert any(v == doc_id("sub/b.md") for _, v in links)
    mg.close()


def test_anchor_link_resolves_to_section(tmp_path):
    write(tmp_path, "a.md", "# A\n\ngo [[b#Details]]\n")
    write(tmp_path, "b.md", "# B\n\nintro\n\n## Details\n\ndeep\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    bdid = doc_id("b.md")
    # b.md sections: 0 = "B" (preamble under # B), 1 = "Details"
    assert any(v == section_id(bdid, 1) for _, v in links)
    mg.close()


def test_dangling_link_recorded_in_meta_not_edge(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbroken [[Nonexistent]]\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    report = mg.build([tmp_path])
    assert report.unresolved_links == 1
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    assert links == set()
    # recorded on the source chunk node meta
    g = mg.graph_store.to_networkx()
    metas = [d["meta"].get("unresolved_links") for _, d in g.nodes(data=True) if d["type"] == NodeType.CHUNK.value]
    assert any(m and "[[Nonexistent]]" in m for m in metas)
    mg.close()
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_indexer_links.py -v` → FAIL (LINKS_TO 边为空 / unresolved_links 为 0)。

- [ ] **Step 3: 实现 `_build_links` 及辅助** — 在 `src/mdgraph/indexer.py` 中，把 `_build_links` 桩替换为下面实现，并在类中新增 `_chunk_for_pos`、`_resolve_link`、`_resolve_path`、`_section_for_anchor` 四个方法（顶部 import 区加 `from posixpath import dirname, join, normpath`）：

```python
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
```

- [ ] **Step 4: 运行确认通过** — `pytest tests/test_indexer_links.py -v` → PASS (4 个)。再跑全套 `pytest -v` 确认无回归（包括 Task 7 的结构测试）。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/indexer.py tests/test_indexer_links.py
git commit -m "feat: resolve wiki/md/anchor links into LINKS_TO edges; record dangling"
```

---

## 完成标准（切片 2）

- `pytest -v` 全绿（含切片 1 旧测试 + 本切片新测试）。
- `python -c "from mdgraph import MarkdownGraph"` 无报错。
- 端到端：给一个含互链、anchor、悬挂链接、frontmatter/行内 tag、超长 section 的 markdown 目录，`MarkdownGraph(dir).build([dir])` 产出结构完整、链接正确解析的图谱，`stats()` 可见节点/边计数；`IndexReport` 报告 indexed/errors/unresolved_links。
- 切片 3（embedding + 纯向量检索）在此之上构建。
