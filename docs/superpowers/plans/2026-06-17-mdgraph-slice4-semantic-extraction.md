# mdgraph 切片 4：LLM 语义抽取（实体 + 关系）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对每个 chunk 调注入的 LLMProvider 抽取实体/关系，按规范化名合并成 Entity 节点，建 MENTIONS(Chunk→Entity) 与 RELATES_TO(Entity→Entity) 边写入 GraphStore，全部带通过的测试。

**Architecture:** provider 依赖注入（测试用 MockLLMProvider）。`ids` 加 `normalize_name`/`entity_id`；`extract.py` 纯函数聚合（逐 chunk 抽取、按 entity_id 合并、收集 mentions/relations/failed_chunks）；`StructuralIndexer` 扩展为持可选 `llm`，在结构/向量之后跑 `_extract_and_store` post-pass；`MarkdownGraph` 加 `llm` 注入参数。只建图，不碰向量库。

**Tech Stack:** Python 3.11+、pydantic、pytest。无新增第三方依赖（NodeType.ENTITY / EdgeType.MENTIONS / EdgeType.RELATES_TO / LLMProvider / MockLLMProvider 均在切片 1 已就绪）。

> 父 spec：`docs/superpowers/specs/2026-06-17-mdgraph-slice4-semantic-extraction-design.md`。基于切片 1+2+3（已在 main）。`llm=None` 时一切退化为切片 3 行为。环境：`python -m pip install -e ".[dev]" -q`，用 `python -m pytest`。

---

## 文件结构

- `src/mdgraph/ids.py`（改）：加 `normalize_name(raw)` + `entity_id(name)`。
- `src/mdgraph/extract.py`（新）：`EntityRecord`/`ExtractionBundle` + `extract_graph(chunks, llm)`。
- `src/mdgraph/indexer.py`（改）：`llm` 注入、`IndexReport.entities`、`_extract_and_store` post-pass。
- `src/mdgraph/engine.py`（改）：`MarkdownGraph(store_dir, embedder=None, llm=None)`。
- 对应 `tests/`。

---

## Task 1: ids.py — normalize_name + entity_id

**Files:**
- Modify: `src/mdgraph/ids.py`
- Test: `tests/test_ids.py`

- [ ] **Step 1: 追加失败测试** — 在 `tests/test_ids.py` 末尾追加:

```python
def test_normalize_name_lowercases_and_collapses():
    from mdgraph.ids import normalize_name

    assert normalize_name("Foo, Bar") == "foo bar"
    assert normalize_name("foo   bar") == "foo bar"
    assert normalize_name("  Baz!  ") == "baz"


def test_entity_id_normalizes_and_is_quote_free():
    from mdgraph.ids import entity_id

    assert entity_id("Foo Bar") == entity_id("foo,  bar")
    assert entity_id("X").startswith("e_")
    assert _SAFE.match(entity_id("foo bar"))
    assert entity_id("a") != entity_id("b")
```
(`_SAFE = re.compile(r"^[A-Za-z0-9_]+$")` is already defined at the top of this test file.)

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_ids.py -k "normalize or entity_id" -v` → FAIL (no `normalize_name`/`entity_id`).

- [ ] **Step 3: 实现** — 在 `src/mdgraph/ids.py` 中：在文件顶部 import 区加 `import re`（在 `import hashlib` 之后）；在文件末尾追加:

```python
_NORM_RE = re.compile(r"\W+")


def normalize_name(name: str) -> str:
    """小写 + 把非单词字符（标点/空白，Unicode 友好）连续段折成单个空格 + 首尾 strip。"""
    return _NORM_RE.sub(" ", name.lower()).strip()


def entity_id(name: str) -> str:
    return "e_" + _h(normalize_name(name))
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_ids.py -v` → PASS（全部）。再跑 `python -m pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/ids.py tests/test_ids.py
git commit -m "feat: add normalize_name and entity_id helpers"
```

---

## Task 2: extract.py — 实体/关系聚合

**Files:**
- Create: `src/mdgraph/extract.py`
- Test: `tests/test_extract.py`

- [ ] **Step 1: 写失败测试** — `tests/test_extract.py`:

```python
from mdgraph.extract import EntityRecord, ExtractionBundle, extract_graph
from mdgraph.ids import entity_id
from mdgraph.providers.base import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)
from mdgraph.providers.mock import MockLLMProvider


def test_extract_aggregates_entities_mentions_relations():
    chunks = [("c1", "Alpha relates Beta"), ("c2", "Alpha and Gamma")]
    bundle = extract_graph(chunks, MockLLMProvider())
    assert isinstance(bundle, ExtractionBundle)
    ids = {e.id for e in bundle.entities}
    assert {entity_id("Alpha"), entity_id("Beta"), entity_id("Gamma")} <= ids
    assert len(bundle.entities) == 3  # Alpha merged across chunks
    alpha = entity_id("Alpha")
    assert ("c1", alpha) in bundle.mentions
    assert ("c2", alpha) in bundle.mentions
    assert (entity_id("Alpha"), entity_id("Beta"), "related_to") in bundle.relations
    assert (entity_id("Alpha"), entity_id("Gamma"), "related_to") in bundle.relations


def test_extract_dedupes_mentions_and_relations():
    chunks = [("c1", "Alpha Beta"), ("c1", "Alpha Beta")]
    bundle = extract_graph(chunks, MockLLMProvider())
    assert len(bundle.mentions) == len(set(bundle.mentions))
    assert len(bundle.relations) == len(set(bundle.relations))


def test_extract_records_failed_chunks():
    class FailingLLM(LLMProvider):
        def extract(self, text):
            if "boom" in text:
                raise RuntimeError("boom")
            return ExtractionResult(entities=[ExtractedEntity(name="Ok")], relations=[])

    bundle = extract_graph([("c1", "boom here"), ("c2", "Ok stuff")], FailingLLM())
    assert bundle.failed_chunks == ["c1"]
    assert any(e.name == "Ok" for e in bundle.entities)


def test_extract_collects_aliases_canonical_is_first():
    class AliasLLM(LLMProvider):
        def __init__(self):
            self.i = 0

        def extract(self, text):
            self.i += 1
            name = "Foo Bar" if self.i == 1 else "foo, bar"
            return ExtractionResult(entities=[ExtractedEntity(name=name)], relations=[])

    bundle = extract_graph([("c1", "x"), ("c2", "y")], AliasLLM())
    assert len(bundle.entities) == 1
    e = bundle.entities[0]
    assert e.name == "Foo Bar"
    assert "foo, bar" in e.aliases


def test_relation_dropped_when_endpoint_not_an_entity():
    class RelLLM(LLMProvider):
        def extract(self, text):
            return ExtractionResult(
                entities=[ExtractedEntity(name="Solo")],
                relations=[ExtractedRelation(source="Solo", target="Ghost", type="x")],
            )

    bundle = extract_graph([("c1", "z")], RelLLM())
    assert bundle.relations == []
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_extract.py -v` → FAIL (No module named 'mdgraph.extract').

- [ ] **Step 3: 实现** — `src/mdgraph/extract.py`:

```python
"""LLM 语义抽取与聚合：chunk → 实体/关系（按规范化名合并）。纯函数，可单测。"""

from __future__ import annotations

from dataclasses import dataclass, field

from mdgraph.ids import entity_id
from mdgraph.providers.base import LLMProvider


@dataclass
class EntityRecord:
    id: str
    name: str
    type: str
    description: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractionBundle:
    entities: list[EntityRecord] = field(default_factory=list)
    mentions: list[tuple[str, str]] = field(default_factory=list)
    relations: list[tuple[str, str, str]] = field(default_factory=list)
    failed_chunks: list[str] = field(default_factory=list)


def extract_graph(chunks: list[tuple[str, str]], llm: LLMProvider) -> ExtractionBundle:
    """逐 chunk 调 llm.extract，按 entity_id 聚合实体，收集去重的 mentions/relations。

    chunks: (chunk_id, text) 列表。抽取抛异常的 chunk 记入 failed_chunks 并跳过。
    relations 仅当两端实体都在同一次抽取中出现时保留（避免幽灵实体）。
    """
    agg: dict[str, dict] = {}
    order: list[str] = []
    mentions: list[tuple[str, str]] = []
    seen_mentions: set[tuple[str, str]] = set()
    relations: list[tuple[str, str, str]] = []
    seen_relations: set[tuple[str, str, str]] = set()
    failed: list[str] = []

    for chunk_id, text in chunks:
        try:
            result = llm.extract(text)
        except Exception:  # noqa: BLE001
            failed.append(chunk_id)
            continue
        local_ids: set[str] = set()
        for ent in result.entities:
            eid = entity_id(ent.name)
            local_ids.add(eid)
            if eid not in agg:
                agg[eid] = {
                    "name": ent.name,
                    "type": ent.type,
                    "description": ent.description,
                    "aliases": set(),
                }
                order.append(eid)
            else:
                cur = agg[eid]
                if ent.name != cur["name"]:
                    cur["aliases"].add(ent.name)
                if cur["type"] in ("", "concept") and ent.type:
                    cur["type"] = ent.type
                if not cur["description"] and ent.description:
                    cur["description"] = ent.description
            m = (chunk_id, eid)
            if m not in seen_mentions:
                seen_mentions.add(m)
                mentions.append(m)
        for rel in result.relations:
            sid = entity_id(rel.source)
            tid = entity_id(rel.target)
            if sid in local_ids and tid in local_ids:
                key = (sid, tid, rel.type)
                if key not in seen_relations:
                    seen_relations.add(key)
                    relations.append(key)

    entities = [
        EntityRecord(
            id=eid,
            name=agg[eid]["name"],
            type=agg[eid]["type"],
            description=agg[eid]["description"],
            aliases=sorted(agg[eid]["aliases"]),
        )
        for eid in order
    ]
    return ExtractionBundle(
        entities=entities, mentions=mentions, relations=relations, failed_chunks=failed
    )
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_extract.py -v` → PASS (5 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/extract.py tests/test_extract.py
git commit -m "feat: add extract_graph entity/relation aggregation"
```

---

## Task 3: indexer — 语义 post-pass

**Files:**
- Modify: `src/mdgraph/indexer.py`
- Test: `tests/test_indexer_extract.py`

- [ ] **Step 1: 写失败测试** — `tests/test_indexer_extract.py`:

```python
from mdgraph.ids import entity_id
from mdgraph.indexer import StructuralIndexer
from mdgraph.models import EdgeType, NodeType
from mdgraph.providers.mock import MockLLMProvider
from mdgraph.store.graph_store import GraphStore


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def test_extract_builds_entities_and_edges(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha relates to Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    report = idx.index([src], root=src)
    g = gs.to_networkx()
    ent = {n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value}
    assert entity_id("Alpha") in ent
    assert entity_id("Beta") in ent
    assert report.entities >= 2
    mentions = edges_of(gs, EdgeType.MENTIONS)
    assert any(v == entity_id("Alpha") for _, v in mentions)
    assert (entity_id("Alpha"), entity_id("Beta")) in edges_of(gs, EdgeType.RELATES_TO)
    gs.close()


def test_same_entity_two_docs_one_node_two_mentions(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha here\n")
    write(src, "b.md", "# B\n\nAlpha there\n")
    gs = GraphStore(tmp_path / "g.db")
    StructuralIndexer(gs, llm=MockLLMProvider()).index([src], root=src)
    g = gs.to_networkx()
    alpha = entity_id("Alpha")
    assert alpha in g
    to_alpha = [
        (u, v)
        for u, v, k in g.edges(keys=True)
        if k == EdgeType.MENTIONS.value and v == alpha
    ]
    assert len(to_alpha) == 2
    gs.close()


def test_rebuild_idempotent_with_llm(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha relates to Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    idx.index([src], root=src)
    s1 = gs.stats()
    idx.index([src], root=src)
    s2 = gs.stats()
    assert s1 == s2
    gs.close()


def test_no_llm_no_entities(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    StructuralIndexer(gs).index([src], root=src)  # no llm
    g = gs.to_networkx()
    ent = [n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value]
    assert ent == []
    gs.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_indexer_extract.py -v` → FAIL (`StructuralIndexer.__init__` 不接受 `llm`)。

- [ ] **Step 3a: import + 构造函数 + IndexReport** — 在 `src/mdgraph/indexer.py`：
顶部 import 区加:
```python
from mdgraph.extract import extract_graph
```
`IndexReport` dataclass 加字段（在 `removed: int = 0` 之后）:
```python
    entities: int = 0
```
`StructuralIndexer.__init__` 改为:
```python
    def __init__(self, store: GraphStore, vector_store=None, embedder=None, llm=None) -> None:
        self.store = store
        self.vector_store = vector_store
        self.embedder = embedder
        self.llm = llm
```

- [ ] **Step 3b: index() 调用 post-pass** — 在 `index` 方法中，把现有的:
```python
        if self.vector_store is not None and self.embedder is not None:
            self._embed_and_store(docs, report)
        return report
```
改为:
```python
        if self.vector_store is not None and self.embedder is not None:
            self._embed_and_store(docs, report)
        if self.llm is not None:
            self._extract_and_store(docs, report)
        return report
```

- [ ] **Step 3c: 新增 `_extract_and_store`** — 在 `_embed_and_store` 方法之后新增:
```python
    def _extract_and_store(self, docs, report) -> None:
        errored = {r[0] for r in report.errors}
        chunks: list[tuple[str, str]] = []
        for ctx in docs:
            if ctx.relpath in errored:
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
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_indexer_extract.py -v` → PASS (4 个)。再跑 `python -m pytest -v` 确认无回归（切片 2/3 的 indexer 测试用 `StructuralIndexer` 不传 llm → `self.llm` None → post-pass 短路）。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/indexer.py tests/test_indexer_extract.py
git commit -m "feat: indexer extracts entities/relations into semantic graph layer"
```

---

## Task 4: engine — llm 注入

**Files:**
- Modify: `src/mdgraph/engine.py`
- Test: `tests/test_engine_extract.py`

- [ ] **Step 1: 写失败测试** — `tests/test_engine_extract.py`:

```python
from mdgraph.engine import MarkdownGraph
from mdgraph.ids import entity_id
from mdgraph.models import EdgeType, NodeType
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def test_build_with_llm_creates_semantic_layer(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha relates to Beta\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph", llm=MockLLMProvider())
    report = mg.build([tmp_path])
    assert report.entities >= 2
    assert (entity_id("Alpha"), entity_id("Beta")) in edges_of(
        mg.graph_store, EdgeType.RELATES_TO
    )
    mg.close()


def test_llm_and_embedder_together(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha content about cats\n")
    mg = MarkdownGraph(
        tmp_path / ".mdgraph",
        embedder=DeterministicEmbeddingProvider(dim=16),
        llm=MockLLMProvider(),
    )
    mg.build([tmp_path])
    # vectors still work
    res = mg.retrieve("Alpha content about cats")
    assert res.contexts
    # entities present
    g = mg.graph_store.to_networkx()
    assert any(d["type"] == NodeType.ENTITY.value for _, d in g.nodes(data=True))
    mg.close()


def test_llm_none_no_entities(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha Beta\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no llm, no embedder
    mg.build([tmp_path])
    g = mg.graph_store.to_networkx()
    assert [n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value] == []
    mg.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_engine_extract.py -v` → FAIL (`MarkdownGraph.__init__` 不接受 `llm`)。

- [ ] **Step 3: 改实现** — `src/mdgraph/engine.py`（完整新内容）:

```python
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
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_engine_extract.py -v` → PASS (3 个)。再跑全套 `python -m pytest -v`（切片 2/3 engine 测试无 llm → 不受影响）；报告总数。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/engine.py tests/test_engine_extract.py
git commit -m "feat: MarkdownGraph llm injection for semantic extraction"
```

---

## 完成标准（切片 4）

- `python -m pytest -v` 全绿（切片 1/2/3 旧测试 + 本切片新测试）。
- `python -c "from mdgraph import MarkdownGraph; from mdgraph.extract import extract_graph"` 无报错。
- 端到端：`MarkdownGraph(dir, llm=mock).build([dir])` 后图中含 ENTITY 节点 + MENTIONS + RELATES_TO 边；同名实体跨文档合并为一个节点多条 mention；不变语料重建幂等；`llm=None` 时无语义层（切片 3 行为）；与 embedder 同时注入时检索与语义层并存。
- 切片 5（图扩展 + RRF）在此之上构建：种子 chunk 沿 MENTIONS→RELATES_TO 扩展；实体描述向量化在彼处。
