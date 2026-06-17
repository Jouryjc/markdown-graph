# mdgraph 切片 3：embedding 管道 + 纯向量检索 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chunk 算向量并集成进 `build()` 写入 VectorStore，提供 `MarkdownGraph.retrieve(query, k)` 做纯向量召回，并保证图库/向量库跨存储一致，全部带通过的测试。

**Architecture:** provider 依赖注入（测试用确定性 mock）。`embed.py` 批量嵌入；`retrieve.py` 查询→向量搜索→距离转相似度→上下文；`StructuralIndexer` 扩展为持可选 `vector_store`+`embedder`，在删除/reconcile/重建时同步清向量、结构建完后批量嵌入写入；`MarkdownGraph` 扩展构造参数 `embedder`、新增 `retrieve()`、`stats()` 加向量计数。

**Tech Stack:** Python 3.11+、pydantic、LanceDB（已有）、pytest。无新增第三方依赖。

> 父 spec：`docs/superpowers/specs/2026-06-17-mdgraph-slice3-vector-retrieval-design.md`。基于切片 1+2（已在 main）。`embedder=None` 时一切退化为切片 2 行为。

---

## 文件结构

- `src/mdgraph/store/vector_store.py`（改）：`search()` 返回键 `score` → `distance`。
- `src/mdgraph/embed.py`（新）：`embed_texts(embedder, texts, batch_size)`。
- `src/mdgraph/retrieve.py`（新）：`Context` / `RetrievalResult` 模型 + `Retriever`。
- `src/mdgraph/indexer.py`（改）：跨存储删除同步 + 批量嵌入写入。
- `src/mdgraph/engine.py`（改）：`embedder` 注入、`retrieve()`、`stats()` 向量计数、`close()` 关向量库。
- 对应 `tests/`。

环境：用 `python -m pytest`（裸 `pytest` 在本机可能解析到缺 lancedb 的解释器）；动手前 `python -m pip install -e ".[dev]" -q`。

---

## Task 1: VectorStore `search` 返回 `distance`

**Files:**
- Modify: `src/mdgraph/store/vector_store.py`
- Modify: `tests/test_vector_store.py`

- [ ] **Step 1: 改测试（先让它失败）** — 在 `tests/test_vector_store.py` 的 `test_search_returns_closest_first` 中，把这一行：

```python
    assert "score" in results[0]
```
替换为：
```python
    assert "distance" in results[0]
    assert "score" not in results[0]
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_vector_store.py::test_search_returns_closest_first -v` → FAIL（当前返回的是 `score` 键）。

- [ ] **Step 3: 改实现** — 在 `src/mdgraph/store/vector_store.py` 的 `search` 方法中，把返回字典里的 `"score": r["_distance"]` 改为 `"distance": r["_distance"]`。改完后该方法体应为：

```python
    def search(self, query_vector: list[float], k: int = 8) -> list[dict]:
        results = self.table.search(query_vector).limit(k).to_list()
        return [
            {
                "chunk_id": r["chunk_id"],
                "text": r["text"],
                "distance": r["_distance"],
                "meta": json.loads(r["meta_json"]),
            }
            for r in results
        ]
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_vector_store.py -v` → PASS（全部，含改动的那个）。再跑 `python -m pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/store/vector_store.py tests/test_vector_store.py
git commit -m "refactor: VectorStore.search returns 'distance' (lower=closer) instead of 'score'"
```

---

## Task 2: embed.py 批量嵌入

**Files:**
- Create: `src/mdgraph/embed.py`
- Test: `tests/test_embed.py`

- [ ] **Step 1: 写失败测试** — `tests/test_embed.py`:

```python
import pytest

from mdgraph.embed import embed_texts
from mdgraph.providers.mock import DeterministicEmbeddingProvider


class CountingEmbedder(DeterministicEmbeddingProvider):
    def __init__(self, dim=8):
        super().__init__(dim=dim)
        self.batch_sizes = []

    def embed(self, texts):
        self.batch_sizes.append(len(texts))
        return super().embed(texts)


def test_embed_texts_empty_returns_empty():
    emb = DeterministicEmbeddingProvider(dim=8)
    assert embed_texts(emb, []) == []


def test_embed_texts_splits_into_batches():
    emb = CountingEmbedder(dim=8)
    texts = [f"t{i}" for i in range(10)]
    vecs = embed_texts(emb, texts, batch_size=4)
    assert len(vecs) == 10
    assert all(len(v) == 8 for v in vecs)
    assert emb.batch_sizes == [4, 4, 2]


def test_embed_texts_preserves_order():
    emb = DeterministicEmbeddingProvider(dim=8)
    texts = ["alpha", "beta", "gamma"]
    assert embed_texts(emb, texts, batch_size=1) == emb.embed(texts)


def test_embed_texts_rejects_bad_batch_size():
    emb = DeterministicEmbeddingProvider(dim=8)
    with pytest.raises(ValueError):
        embed_texts(emb, ["a"], batch_size=0)
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_embed.py -v` → FAIL (No module named 'mdgraph.embed').

- [ ] **Step 3: 写实现** — `src/mdgraph/embed.py`:

```python
"""批量 embedding：按 provider 批上限分批调用，拼接结果。"""

from __future__ import annotations

from mdgraph.providers.base import EmbeddingProvider


def embed_texts(
    embedder: EmbeddingProvider, texts: list[str], batch_size: int = 64
) -> list[list[float]]:
    """对 texts 分批调用 embedder.embed，返回与输入等长、顺序一致的向量列表。"""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(embedder.embed(texts[i : i + batch_size]))
    return out
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_embed.py -v` → PASS (4 个)。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/embed.py tests/test_embed.py
git commit -m "feat: add batched embed_texts helper"
```

---

## Task 3: retrieve.py 向量检索

**Files:**
- Create: `src/mdgraph/retrieve.py`
- Test: `tests/test_retrieve.py`

- [ ] **Step 1: 写失败测试** — `tests/test_retrieve.py`:

```python
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.retrieve import Context, RetrievalResult, Retriever
from mdgraph.store.vector_store import VectorStore


def make(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    return emb, vs


def test_retrieve_empty_query_returns_empty(tmp_path):
    emb, vs = make(tmp_path)
    res = Retriever(vs, emb).retrieve("   ")
    assert isinstance(res, RetrievalResult)
    assert res.contexts == []


def test_retrieve_empty_index_returns_empty(tmp_path):
    emb, vs = make(tmp_path)
    assert Retriever(vs, emb).retrieve("alpha").contexts == []


def test_retrieve_ranks_closest_first_with_meta(tmp_path):
    emb, vs = make(tmp_path)
    texts = ["alpha alpha", "beta beta", "gamma gamma"]
    metas = [
        {"source_path": "a.md", "heading_path": "A"},
        {"source_path": "b.md", "heading_path": "B"},
        {"source_path": "c.md", "heading_path": "C"},
    ]
    vs.add(["c1", "c2", "c3"], emb.embed(texts), texts, metas)
    res = Retriever(vs, emb).retrieve("beta beta", k=3)
    assert isinstance(res.contexts[0], Context)
    assert res.contexts[0].chunk_id == "c2"
    assert res.contexts[0].source_path == "b.md"
    assert res.contexts[0].heading_path == "B"
    scores = [c.score for c in res.contexts]
    assert scores == sorted(scores, reverse=True)
    assert 0.0 < res.contexts[0].score <= 1.0
    assert res.subgraph == {"nodes": [], "edges": []}


def test_retrieve_exact_match_scores_near_one(tmp_path):
    emb, vs = make(tmp_path)
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{}])
    res = Retriever(vs, emb).retrieve("alpha", k=1)
    assert res.contexts[0].score > 0.99
    assert res.contexts[0].source_path == ""  # empty meta -> default
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_retrieve.py -v` → FAIL (No module named 'mdgraph.retrieve').

- [ ] **Step 3: 写实现** — `src/mdgraph/retrieve.py`:

```python
"""向量检索：查询 embedding → 向量搜索 → 距离转相似度 → 上下文。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.providers.base import EmbeddingProvider
from mdgraph.store.vector_store import VectorStore


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
    def __init__(self, vector_store: VectorStore, embedder: EmbeddingProvider) -> None:
        self.vector_store = vector_store
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 8) -> RetrievalResult:
        if not query.strip():
            return RetrievalResult()
        qvec = self.embedder.embed([query])[0]
        rows = self.vector_store.search(qvec, k=k)
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
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_retrieve.py -v` → PASS (4 个)。再跑 `python -m pytest -v` 确认无回归。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/retrieve.py tests/test_retrieve.py
git commit -m "feat: add Retriever (vector recall -> contexts, distance->similarity)"
```

---

## Task 4: indexer 跨存储同步 + 批量嵌入写入

**Files:**
- Modify: `src/mdgraph/indexer.py`
- Test: `tests/test_indexer_embed.py`

- [ ] **Step 1: 写失败测试** — `tests/test_indexer_embed.py`:

```python
from mdgraph.indexer import StructuralIndexer
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def make_indexer(tmp_path):
    gs = GraphStore(tmp_path / "g.db")
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    return gs, vs, StructuralIndexer(gs, vector_store=vs, embedder=emb)


def test_index_embeds_all_chunks(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha body\n\n## Sub\n\nmore text\n")
    write(src, "b.md", "# B\n\nbeta body\n")
    gs, vs, idx = make_indexer(tmp_path)
    idx.index([src], root=src)
    assert vs.count() == gs.stats()["chunks"]
    assert vs.count() >= 3
    gs.close()


def test_rebuild_does_not_duplicate_vectors(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha body\n")
    gs, vs, idx = make_indexer(tmp_path)
    idx.index([src], root=src)
    n1 = vs.count()
    idx.index([src], root=src)
    assert vs.count() == n1  # no duplicate rows across rebuilds
    gs.close()


def test_indexer_without_vector_store_is_structure_only(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nbody\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs)  # no vector_store / embedder
    report = idx.index([src], root=src)
    assert report.indexed == 1
    assert gs.stats()["chunks"] >= 1
    gs.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_indexer_embed.py -v` → FAIL (`StructuralIndexer.__init__` 不接受 `vector_store`/`embedder`)。

- [ ] **Step 3a: 改构造函数与 import** — 在 `src/mdgraph/indexer.py` 顶部 import 区加：

```python
from mdgraph.embed import embed_texts
```

把 `StructuralIndexer.__init__` 改为：

```python
    def __init__(self, store: GraphStore, vector_store=None, embedder=None) -> None:
        self.store = store
        self.vector_store = vector_store
        self.embedder = embedder
```

- [ ] **Step 3b: reconcile 同步清向量** — 在 `index` 方法的 reconcile 循环中，把：

```python
        discovered = {ctx.did for ctx in docs}
        for stored_id, _ in self.store.list_documents():
            if stored_id not in discovered:
                self.store.delete_document(stored_id)
                report.removed += 1
```
改为：
```python
        discovered = {ctx.did for ctx in docs}
        for stored_id, _ in self.store.list_documents():
            if stored_id not in discovered:
                self._purge_vectors(stored_id)
                self.store.delete_document(stored_id)
                report.removed += 1
```

- [ ] **Step 3c: pass-3 后批量嵌入** — 在 `index` 方法 `return report` 之前（pass-3 链接循环之后）插入：

```python
        if self.vector_store is not None and self.embedder is not None:
            self._embed_and_store(docs, report)
```

- [ ] **Step 3d: 重建前清旧向量** — 在 `_build_doc` 方法体最开头（`did, pd, chunks = ...` 之后、`with self.store.transaction():` 之前）插入：

```python
        self._purge_vectors(did)
```

- [ ] **Step 3e: 新增两个方法** — 在 `_build_links` 方法之后（类内）新增：

```python
    def _purge_vectors(self, doc_id: str) -> None:
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
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_indexer_embed.py -v` → PASS (3 个)。再跑 `python -m pytest -v`（含切片 2 的 indexer 测试，应无回归——`vector_store=None` 时全部新逻辑短路）。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/indexer.py tests/test_indexer_embed.py
git commit -m "feat: indexer embeds chunks to VectorStore and syncs deletes across stores"
```

---

## Task 5: engine 注入 embedder + retrieve + stats

**Files:**
- Modify: `src/mdgraph/engine.py`
- Test: `tests/test_engine_retrieve.py`

- [ ] **Step 1: 写失败测试** — `tests/test_engine_retrieve.py`:

```python
import pytest

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.mock import DeterministicEmbeddingProvider


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_build_and_retrieve_end_to_end(tmp_path):
    write(tmp_path, "notes/alpha.md", "# Alpha\n\nalpha content about cats\n")
    write(tmp_path, "notes/beta.md", "# Beta\n\nbeta content about dogs\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path / "notes"])
    assert mg.stats()["vectors"] == mg.stats()["chunks"]
    res = mg.retrieve("alpha content about cats", k=3)
    assert res.contexts
    assert res.contexts[0].source_path == "alpha.md"
    assert res.contexts[0].heading_path == "Alpha"
    mg.close()


def test_retrieve_without_embedder_raises(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no embedder
    mg.build([tmp_path])
    with pytest.raises(RuntimeError):
        mg.retrieve("x")
    assert "vectors" not in mg.stats()
    mg.close()


def test_removed_doc_purges_its_vectors(tmp_path):
    write(tmp_path, "a.md", "# A\n\nalpha\n")
    write(tmp_path, "b.md", "# B\n\nbeta\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path])
    v1 = mg.stats()["vectors"]
    (tmp_path / "b.md").unlink()
    mg.build([tmp_path])
    v2 = mg.stats()["vectors"]
    assert v2 < v1
    assert v2 == mg.stats()["chunks"]
    mg.close()


def test_rebuild_idempotent_with_vectors(tmp_path):
    write(tmp_path, "a.md", "# A\n\nalpha\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path])
    s1 = mg.stats()
    mg.build([tmp_path])
    s2 = mg.stats()
    assert s1 == s2
    mg.close()
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_engine_retrieve.py -v` → FAIL (`MarkdownGraph.__init__` 不接受 `embedder` / 无 `retrieve`)。

- [ ] **Step 3: 改实现** — `src/mdgraph/engine.py`（完整新内容）:

```python
"""MarkdownGraph：结构索引 + 向量检索门面。"""

from __future__ import annotations

from pathlib import Path

from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.providers.base import EmbeddingProvider
from mdgraph.retrieve import RetrievalResult, Retriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


class MarkdownGraph:
    def __init__(self, store_dir: str | Path, embedder: EmbeddingProvider | None = None) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.graph_store = GraphStore(self.store_dir / "graph.db")
        self.embedder = embedder
        self.vector_store: VectorStore | None = None
        if embedder is not None:
            self.vector_store = VectorStore(
                self.store_dir / "vectors", model_name=embedder.name, dim=embedder.dim
            )
        self.indexer = StructuralIndexer(
            self.graph_store, vector_store=self.vector_store, embedder=embedder
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

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_engine_retrieve.py -v` → PASS (4 个)。再跑全套 `python -m pytest -v`（切片 2 的 `tests/test_indexer_structure.py` 用 `MarkdownGraph(tmp_path)` 无 embedder → 行为不变，应无回归）；报告总数。

- [ ] **Step 5: 提交**:

```bash
git add src/mdgraph/engine.py tests/test_engine_retrieve.py
git commit -m "feat: MarkdownGraph embedder injection + retrieve() + vector stats"
```

---

## 完成标准（切片 3）

- `python -m pytest -v` 全绿（切片 1+2 旧测试 + 本切片新测试）。
- `python -c "from mdgraph import MarkdownGraph; from mdgraph.retrieve import RetrievalResult"` 无报错。
- 端到端：`MarkdownGraph(dir, embedder=mock).build([dir])` 后 `stats()["vectors"] == stats()["chunks"]`；`retrieve("...")` 返回按 score 降序的上下文块（带 source_path/heading_path）；删文件重建后该文档向量被清；重建幂等无重复；`embedder=None` 时 `retrieve()` 抛 `RuntimeError` 且 `build()` 仍纯结构。
- 切片 4（Entity 抽取）/ 切片 5（图扩展 + RRF）在此之上构建：`embed_texts` 可复用，`Retriever` 是扩展落点，`RetrievalResult.subgraph` 已占位。
