# mdgraph 切片 5：图扩展 + RRF 融合（双引擎检索）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把纯向量 `Retriever` 升级为图+向量双引擎：向量召回种子 → `GraphStore.expand` 多源 BFS 扩展 → RRF 融合向量排名与图邻近度排名 → 返回融合排序的上下文块 + 诱导子图。

**Architecture:** 新增 `GraphStore.expand`（一次建图多源 BFS，返回 `{node_id: 最小跳距}`）与 `GraphStore.subgraph`（诱导子图）；新增纯函数 `fusion.reciprocal_rank_fusion`；`Retriever` 增可选 `graph_store`，有则走双引擎、无则退化为切片 3 纯向量；`engine` 把 `graph_store` 传进 `Retriever`。

**Tech Stack:** Python 3.11+、networkx（已有，用于 expand/subgraph）、pydantic、pytest。

## Global Constraints

- Python 3.11+；**不引入新的第三方依赖**。
- 测试用 `python -m pytest`（裸 `pytest` 可能解析到缺 lancedb 的解释器）；动手前 `python -m pip install -e ".[dev]" -q`。
- 全程离线确定性：mock provider（`DeterministicEmbeddingProvider` / `MockLLMProvider`），无网络。
- 所有 id 为 hex/下划线/数字，无引号（既有约束）。
- `graph_store=None` 时 `Retriever` 行为必须与切片 3 完全一致（切片 3 的 `tests/test_retrieve.py` 不可破）。

> 父 spec：`docs/superpowers/specs/2026-06-17-mdgraph-slice5-graph-rrf-design.md`。基于切片 1~4（已在 main）。

---

## Task 1: GraphStore.expand 多源 BFS

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`
- Test: `tests/test_graph_store_expand.py`

**Interfaces:**
- Consumes: 既有 `GraphStore.to_networkx()`、`upsert_node`/`upsert_edge`；`mdgraph.models.EdgeType`/`NodeType`/`Node`/`Edge`。
- Produces: `GraphStore.expand(self, seed_ids: list[str], edge_types: list[EdgeType] | None = None, hops: int = 1) -> dict[str, int]` —— 多源无向 BFS，返回 `{node_id: 最小跳距}`，不含种子自身，忽略不在图中的种子。

- [ ] **Step 1: 写失败测试** — `tests/test_graph_store_expand.py`:

```python
from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def build_chain(store):
    # a -CONTAINS-> b -LINKS_TO-> c -MENTIONS-> e ; d 孤立
    for nid in ["a", "b", "c", "e", "d"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="b", dst="c", type=EdgeType.LINKS_TO))
    store.upsert_edge(Edge(src="c", dst="e", type=EdgeType.MENTIONS))


def test_expand_multi_source_distances(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["a"], hops=2) == {"b": 1, "c": 2}
    store.close()


def test_expand_excludes_seeds(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    dist = store.expand(["a", "b"], hops=1)
    assert "a" not in dist and "b" not in dist
    assert dist.get("c") == 1
    store.close()


def test_expand_filters_edge_types(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["a"], edge_types=[EdgeType.CONTAINS], hops=2) == {"b": 1}
    store.close()


def test_expand_missing_seed_ignored(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["nope"], hops=2) == {}
    store.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_graph_store_expand.py -v` → FAIL (`GraphStore` 无 `expand`)。

- [ ] **Step 3: 实现** — 在 `src/mdgraph/store/graph_store.py` 中，在 `neighbors` 方法之后新增（`nx`/`EdgeType` 已 import）:

```python
    def expand(
        self,
        seed_ids: list[str],
        edge_types: list[EdgeType] | None = None,
        hops: int = 1,
    ) -> dict[str, int]:
        """多源无向 BFS：一次建图，从所有种子一起扩 hops 跳。

        返回 {node_id: 最小跳距}，不含种子自身，忽略不在图中的种子。
        """
        g = self.to_networkx()
        allowed = {e.value for e in edge_types} if edge_types else None
        frontier = {s for s in seed_ids if s in g}
        visited = set(frontier)
        dist: dict[str, int] = {}
        for h in range(1, hops + 1):
            nxt: set[str] = set()
            for n in frontier:
                for _, d, key in g.out_edges(n, keys=True):
                    if (allowed is None or key in allowed) and d not in visited:
                        nxt.add(d)
                for s, _, key in g.in_edges(n, keys=True):
                    if (allowed is None or key in allowed) and s not in visited:
                        nxt.add(s)
            for node in nxt:
                dist[node] = h
            visited |= nxt
            frontier = nxt
        return dist
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_graph_store_expand.py -v` → PASS (4 个)。再跑 `python -m pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_expand.py
git commit -m "feat: add GraphStore.expand multi-source BFS"
```

---

## Task 2: GraphStore.subgraph 诱导子图

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`
- Test: `tests/test_graph_store_subgraph.py`

**Interfaces:**
- Consumes: 既有 `GraphStore.to_networkx()`。
- Produces: `GraphStore.subgraph(self, node_ids: list[str]) -> dict` —— 给定节点 + 其 1 跳邻居的诱导子图，形如 `{"nodes": [{"id","type","meta"}], "edges": [{"src","dst","type"}]}`，nodes 按 id 排序、edges 按 (src,dst,type) 排序（确定性）。孤立节点也返回。

- [ ] **Step 1: 写失败测试** — `tests/test_graph_store_subgraph.py`:

```python
from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_subgraph_includes_nodes_and_connectors(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    for nid, t in [("c1", NodeType.CHUNK), ("c2", NodeType.CHUNK), ("e1", NodeType.ENTITY)]:
        store.upsert_node(Node(id=nid, type=t, meta={"name": nid}))
    store.upsert_edge(Edge(src="c1", dst="e1", type=EdgeType.MENTIONS))
    store.upsert_edge(Edge(src="c2", dst="e1", type=EdgeType.MENTIONS))
    sg = store.subgraph(["c1", "c2"])
    assert {n["id"] for n in sg["nodes"]} == {"c1", "c2", "e1"}  # e1 是 1 跳连接器
    types = {n["id"]: n["type"] for n in sg["nodes"]}
    assert types["e1"] == NodeType.ENTITY.value
    pairs = {(e["src"], e["dst"], e["type"]) for e in sg["edges"]}
    assert ("c1", "e1", EdgeType.MENTIONS.value) in pairs
    assert ("c2", "e1", EdgeType.MENTIONS.value) in pairs
    store.close()


def test_subgraph_isolated_node(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="x", type=NodeType.CHUNK))
    sg = store.subgraph(["x"])
    assert [n["id"] for n in sg["nodes"]] == ["x"]
    assert sg["edges"] == []
    store.close()


def test_subgraph_deterministic_order(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    for nid in ["b", "a", "c"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    sg = store.subgraph(["a", "b", "c"])
    assert [n["id"] for n in sg["nodes"]] == ["a", "b", "c"]
    store.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_graph_store_subgraph.py -v` → FAIL (`GraphStore` 无 `subgraph`)。

- [ ] **Step 3: 实现** — 在 `src/mdgraph/store/graph_store.py` 中，在 `expand` 方法之后新增:

```python
    def subgraph(self, node_ids: list[str]) -> dict:
        """给定节点 + 其 1 跳邻居的诱导子图（确定性排序）。"""
        g = self.to_networkx()
        keep: set[str] = {n for n in node_ids if n in g}
        for n in list(keep):
            for _, d, _ in g.out_edges(n, keys=True):
                keep.add(d)
            for s, _, _ in g.in_edges(n, keys=True):
                keep.add(s)
        nodes = sorted(
            (
                {"id": n, "type": g.nodes[n]["type"], "meta": g.nodes[n].get("meta", {})}
                for n in keep
            ),
            key=lambda x: x["id"],
        )
        edges = sorted(
            (
                {"src": u, "dst": v, "type": key}
                for u, v, key in g.edges(keys=True)
                if u in keep and v in keep
            ),
            key=lambda e: (e["src"], e["dst"], e["type"]),
        )
        return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_graph_store_subgraph.py -v` → PASS (3 个)。再跑 `python -m pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_subgraph.py
git commit -m "feat: add GraphStore.subgraph induced subgraph"
```

---

## Task 3: fusion.py RRF

**Files:**
- Create: `src/mdgraph/fusion.py`
- Test: `tests/test_fusion.py`

**Interfaces:**
- Produces: `reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]` —— `score(item) = Σ_ranking 1/(k + rank)`，rank 从 1 开始；纯函数、确定性。

- [ ] **Step 1: 写失败测试** — `tests/test_fusion.py`:

```python
from mdgraph.fusion import reciprocal_rank_fusion


def test_rrf_both_rankings_beats_single():
    r = reciprocal_rank_fusion([["a", "b"], ["a", "c"]])
    assert r["a"] > r["b"]
    assert r["a"] > r["c"]


def test_rrf_preserves_rank_order_single():
    r = reciprocal_rank_fusion([["a", "b", "c"]])
    assert r["a"] > r["b"] > r["c"]


def test_rrf_empty():
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[]]) == {}


def test_rrf_k_affects_score():
    assert reciprocal_rank_fusion([["a"]], k=1)["a"] > reciprocal_rank_fusion([["a"]], k=100)["a"]
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_fusion.py -v` → FAIL (No module named 'mdgraph.fusion').

- [ ] **Step 3: 实现** — `src/mdgraph/fusion.py`:

```python
"""倒数排名融合（Reciprocal Rank Fusion）。"""

from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """对多个排名列表做 RRF：score(item) = Σ 1/(k + rank)，rank 从 1 开始。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_fusion.py -v` → PASS (4 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/fusion.py tests/test_fusion.py
git commit -m "feat: add reciprocal rank fusion"
```

---

## Task 4: Retriever 双引擎融合

**Files:**
- Modify: `src/mdgraph/retrieve.py`
- Test: `tests/test_retrieve_dual.py`

**Interfaces:**
- Consumes: `mdgraph.fusion.reciprocal_rank_fusion`；`GraphStore.expand`/`subgraph`/`get_chunk`/`get_document`；`mdgraph.models.EdgeType`/`NodeType`；既有 `Context`/`RetrievalResult`/`VectorStore.search`（返回 `{chunk_id,text,distance,meta}`）。
- Produces: `Retriever(vector_store, embedder, graph_store=None)`；`retrieve(self, query: str, k: int = 8, hops: int = 2) -> RetrievalResult`。`graph_store=None` → 纯向量（切片 3 行为，子图空）；有 `graph_store` → 双引擎融合 + 填充子图。

- [ ] **Step 1: 写失败测试** — `tests/test_retrieve_dual.py`:

```python
from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.retrieve import Retriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


def test_retriever_without_graph_store_is_pure_vector(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    vs.add(["c1", "c2"], emb.embed(["alpha", "beta"]), ["alpha", "beta"],
           [{"source_path": "a.md"}, {"source_path": "b.md"}])
    res = Retriever(vs, emb).retrieve("alpha", k=2)  # graph_store=None
    assert res.contexts[0].chunk_id == "c1"
    assert 0.0 < res.contexts[0].score <= 1.0  # 相似度，不是 RRF
    assert res.subgraph == {"nodes": [], "edges": []}


def test_dual_pulls_graph_only_chunk_with_graph_metadata(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    # 图里有 c1、c2（c1 LINKS_TO c2）；向量库只有 c1
    gs.upsert_document(Document(id="d2", path="notes/b.md", hash="h", mtime=1.0))
    gs.upsert_chunk(Chunk(id="c2", doc_id="d2", section_path="B>Sub", text="graph only text", char_start=0, char_end=15))
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    gs.upsert_node(Node(id="c2", type=NodeType.CHUNK, doc_id="d2"))
    gs.upsert_edge(Edge(src="c1", dst="c2", type=EdgeType.LINKS_TO))
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{"source_path": "a.md", "heading_path": "A"}])
    res = Retriever(vs, emb, graph_store=gs).retrieve("alpha", k=8, hops=1)
    ids = [c.chunk_id for c in res.contexts]
    assert ids[0] == "c1"
    assert "c2" in ids
    c2ctx = next(c for c in res.contexts if c.chunk_id == "c2")
    assert c2ctx.text == "graph only text"
    assert c2ctx.source_path == "notes/b.md"
    assert c2ctx.heading_path == "B>Sub"
    assert any(e["type"] == EdgeType.LINKS_TO.value for e in res.subgraph["edges"])
    gs.close()


def test_dual_empty_query(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    res = Retriever(vs, emb, graph_store=gs).retrieve("   ")
    assert res.contexts == []
    gs.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_retrieve_dual.py -v` → FAIL (`Retriever.__init__` 不接受 `graph_store`)。

- [ ] **Step 3: 实现** — 把 `src/mdgraph/retrieve.py` 替换为（完整新内容）:

```python
"""向量检索 + 图扩展融合：query → 向量召回 →（可选）图扩展 + RRF → 上下文 + 子图。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.fusion import reciprocal_rank_fusion
from mdgraph.models import EdgeType
from mdgraph.providers.base import EmbeddingProvider
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore

_EXPAND_EDGES = [
    EdgeType.CONTAINS,
    EdgeType.LINKS_TO,
    EdgeType.MENTIONS,
    EdgeType.RELATES_TO,
]


class Context(BaseModel):
    chunk_id: str
    text: str
    score: float
    source_path: str = ""
    heading_path: str = ""


class RetrievalResult(BaseModel):
    contexts: list[Context] = Field(default_factory=list)
    subgraph: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})


class Retriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedder: EmbeddingProvider,
        graph_store: GraphStore | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store

    def retrieve(self, query: str, k: int = 8, hops: int = 2) -> RetrievalResult:
        if not query.strip():
            return RetrievalResult()
        qvec = self.embedder.embed([query])[0]
        rows = self.vector_store.search(qvec, k=k)
        if self.graph_store is None:
            return self._vector_only(rows)
        return self._dual(rows, k, hops)

    def _vector_only(self, rows: list[dict]) -> RetrievalResult:
        contexts = [
            Context(
                chunk_id=r["chunk_id"],
                text=r["text"],
                score=1.0 / (1.0 + r["distance"]),
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
            for r in rows
        ]
        contexts.sort(key=lambda c: c.score, reverse=True)
        return RetrievalResult(contexts=contexts)

    def _dual(self, rows: list[dict], k: int, hops: int) -> RetrievalResult:
        vector_ranking = [r["chunk_id"] for r in rows]
        row_by_id = {r["chunk_id"]: r for r in rows}
        dist = self.graph_store.expand(vector_ranking, edge_types=_EXPAND_EDGES, hops=hops)
        graph_chunks = [n for n in dist if self.graph_store.get_chunk(n) is not None]
        graph_ranking = sorted(graph_chunks, key=lambda n: (dist[n], n))
        fused = reciprocal_rank_fusion([vector_ranking, graph_ranking])
        ordered = sorted(fused, key=lambda c: (-fused[c], c))[:k]
        contexts = [self._context(cid, fused[cid], row_by_id) for cid in ordered]
        subgraph = self.graph_store.subgraph(ordered)
        return RetrievalResult(contexts=contexts, subgraph=subgraph)

    def _context(self, chunk_id: str, score: float, row_by_id: dict) -> Context:
        if chunk_id in row_by_id:
            r = row_by_id[chunk_id]
            return Context(
                chunk_id=chunk_id,
                text=r["text"],
                score=score,
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
        ch = self.graph_store.get_chunk(chunk_id)
        source = ""
        if ch is not None:
            doc = self.graph_store.get_document(ch.doc_id)
            source = doc.path if doc is not None else ""
        return Context(
            chunk_id=chunk_id,
            text=ch.text if ch is not None else "",
            score=score,
            source_path=source,
            heading_path=ch.section_path if ch is not None else "",
        )
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_retrieve_dual.py -v` → PASS (3 个)。再跑 `python -m pytest tests/test_retrieve.py -v`（切片 3 纯向量测试，`Retriever(vs, emb)` → graph_store=None → 不破）与全套 `python -m pytest -v`；报告总数。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/retrieve.py tests/test_retrieve_dual.py
git commit -m "feat: dual-engine Retriever (vector recall + graph expand + RRF + subgraph)"
```

---

## Task 5: engine 接入双引擎

**Files:**
- Modify: `src/mdgraph/engine.py`
- Test: `tests/test_engine_dual.py`

**Interfaces:**
- Consumes: `Retriever(vector_store, embedder, graph_store=...)`；既有 `self.graph_store`/`self.vector_store`/`self.embedder`。
- Produces: `MarkdownGraph.retrieve` 现在构造 `Retriever(self.vector_store, self.embedder, graph_store=self.graph_store)`，即走双引擎。

- [ ] **Step 1: 写失败测试** — `tests/test_engine_dual.py`:

```python
from mdgraph.engine import MarkdownGraph
from mdgraph.ids import chunk_id, doc_id, entity_id
from mdgraph.providers.mock import DeterministicEmbeddingProvider, MockLLMProvider


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_dual_engine_surfaces_co_mentioned_chunk_and_subgraph(tmp_path):
    # a、b 都提及 "Shared" -> 经实体共提及（2 跳）相连
    write(tmp_path, "a.md", "# A\n\nalpha content with Shared\n")
    write(tmp_path, "b.md", "# B\n\ntotally unrelated words Shared\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb, llm=MockLLMProvider())
    mg.build([tmp_path])
    res = mg.retrieve("alpha content with Shared", k=8)
    ids = [c.chunk_id for c in res.contexts]
    a_chunk = chunk_id(doc_id("a.md"), 0, 0)
    b_chunk = chunk_id(doc_id("b.md"), 0, 0)
    assert a_chunk in ids
    assert b_chunk in ids
    # 子图含连接两块的 Shared 实体节点
    assert any(n["id"] == entity_id("Shared") for n in res.subgraph["nodes"])
    mg.close()


def test_retrieve_without_embedder_still_raises(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no embedder
    mg.build([tmp_path])
    import pytest

    with pytest.raises(RuntimeError):
        mg.retrieve("x")
    mg.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_engine_dual.py -v` → FAIL（`test_dual_engine_...`：`b_chunk` 未被图召回 / `subgraph` 无 Shared 实体——当前 engine 仍走纯向量、子图空）。

- [ ] **Step 3: 实现** — 在 `src/mdgraph/engine.py` 中，把 `retrieve` 方法的返回行:

```python
        return Retriever(self.vector_store, self.embedder).retrieve(query, k=k)
```
改为:
```python
        return Retriever(
            self.vector_store, self.embedder, graph_store=self.graph_store
        ).retrieve(query, k=k)
```
（其余不变。）

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_engine_dual.py -v` → PASS (2 个)。再跑全套 `python -m pytest -v`（切片 3 的 `tests/test_engine_retrieve.py` 简单语料——无 llm、两文档不互链——精确匹配块仍居首、`retrieve` 不报错，应无回归）；报告总数。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/engine.py tests/test_engine_dual.py
git commit -m "feat: MarkdownGraph.retrieve uses dual-engine (graph + vector + RRF)"
```

---

## 完成标准（切片 5）

- `python -m pytest -v` 全绿（切片 1~4 旧测试 + 本切片新测试）。
- `python -c "from mdgraph import MarkdownGraph; from mdgraph.fusion import reciprocal_rank_fusion"` 无报错。
- 端到端：`MarkdownGraph(dir, embedder, llm).build([dir])` 后 `retrieve()` 走双引擎——向量召回 + 沿 MENTIONS/RELATES_TO/CONTAINS/LINKS_TO 图扩展 + RRF 融合，返回融合排序的上下文块且 `RetrievalResult.subgraph` 填充诱导子图；`graph_store=None`（直接构造 Retriever）退化为切片 3 纯向量。
- 切片 6（增量 + 孤儿回收 + CLI）在此之上：`expand`/`subgraph` 可复用于 `graph export`。
