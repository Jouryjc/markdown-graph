# mdgraph 切片 9：缓解双引擎 hub 偏置（加权 RRF + 每文档限流）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 RRF 融合加权（图权重 < 向量）并对每个 source_path 限流，消除图独有 hub chunk 挤掉纯向量精准命中、同文档霸榜 top5 的问题。

**Architecture:** `fusion.reciprocal_rank_fusion` 加可选 `weights`（默认等权、向后兼容）；`Retriever` 加 `vector_weight=1.0`/`graph_weight=0.5`/`per_doc_cap=2` 三参数，`_dual` 用加权 RRF + 贪心每文档限流选 top-k。纯向量路径与 `MarkdownGraph.retrieve` 签名不变。

**Tech Stack:** 纯 Python，无新依赖。

## Global Constraints

- 运行测试一律用 `python -m pytest`（裸 `pytest` 在本机可能解析到缺 lancedb 的解释器）。
- `fusion.reciprocal_rank_fusion` 的 `weights` 默认 `None`=等权——既有 `test_fusion` 等权数学**不得破**。
- `test_retrieve_dual` 既有断言不得破（已验算：默认 `graph_weight=0.5` 下 `c1=1.0×1/61` 第一、`c2=0.5×1/61` 被拉入、不同 source_path 不触 cap）。
- 纯向量路径（`_vector_only`/`graph_store=None`）与 `MarkdownGraph.retrieve` 签名**完全不变**。
- 限流语义：**严格上限**，达 cap 的文档其余块跳过（结果不足 k 也不回填）。
- 提交信息正文用中文；commit 结尾必须是：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 面向用户输出/思考用中文，代码/标识符/路径原文。
- 全套回归：若某既有 engine/retrieve 测试因新默认（`graph_weight=0.5`/`per_doc_cap=2`）改变结果，须在报告中显式标出（行为变更，由审查/控制者裁定），不得静默改既有断言来"过测试"。

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `src/mdgraph/fusion.py` | RRF 加权 | 改 `reciprocal_rank_fusion` 加 `weights=None` |
| `src/mdgraph/retrieve.py` | `_dual` 加权融合 + 每文档限流 | 改 `Retriever.__init__`、`_dual`、`Context` docstring |
| `tests/test_fusion.py` / `tests/test_retrieve_dual.py` | 加权 / 限流测试 | 追加 |

---

### Task 1: `fusion.reciprocal_rank_fusion` 加权重

**Files:**
- Modify: `src/mdgraph/fusion.py`
- Test: `tests/test_fusion.py`（追加）

**Interfaces:**
- Produces: `reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60, weights: list[float] | None = None) -> dict[str, float]`。`weights[i]` 为第 i 路 ranking 权重；`None` → 全 `1.0`。

- [ ] **Step 1: 追加失败测试** — 在 `tests/test_fusion.py` 末尾加：

```python
def test_rrf_weights_scale_contribution():
    equal = reciprocal_rank_fusion([["a"], ["a"]])
    weighted = reciprocal_rank_fusion([["a"], ["a"]], weights=[1.0, 3.0])
    assert weighted["a"] > equal["a"]


def test_rrf_weight_can_reorder():
    # b 在高权重路第一、a 在低权重路第一 → b 反超
    r = reciprocal_rank_fusion([["a"], ["b"]], weights=[0.1, 1.0])
    assert r["b"] > r["a"]


def test_rrf_weights_none_equals_equal_weight():
    assert reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == reciprocal_rank_fusion(
        [["a", "b"], ["b", "c"]], weights=[1.0, 1.0]
    )
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_fusion.py -v`
Expected: FAIL（`reciprocal_rank_fusion() got an unexpected keyword argument 'weights'`）

- [ ] **Step 3: 实现** — 把 `src/mdgraph/fusion.py` 的函数替换为：

```python
def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60, weights: list[float] | None = None
) -> dict[str, float]:
    """对多个排名列表做（可加权）RRF：score(item) = Σ w_i × 1/(k + rank)，rank 从 1 开始。

    weights 为每路 ranking 的权重；None → 全 1.0（等权，向后兼容）。
    """
    scores: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else weights[i]
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + w * (1.0 / (k + rank))
    return scores
```

- [ ] **Step 4: 运行确认通过 + 等权回归**

Run: `python -m pytest tests/test_fusion.py -v`
Expected: PASS（既有 4 个等权测试 + 新增 3 个全绿）

- [ ] **Step 5: Commit**

```bash
git add src/mdgraph/fusion.py tests/test_fusion.py
git commit -m "$(cat <<'EOF'
feat: weighted reciprocal rank fusion (optional per-ranking weights)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `_dual` 加权融合 + 每文档限流 + Retriever 参数

**Files:**
- Modify: `src/mdgraph/retrieve.py`
- Test: `tests/test_retrieve_dual.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `reciprocal_rank_fusion(..., weights=)`。
- Produces: `Retriever(vector_store, embedder, graph_store=None, vector_weight=1.0, graph_weight=0.5, per_doc_cap=2)`；`_dual` 用加权 RRF + 每文档限流。

- [ ] **Step 1: 追加失败测试** — 在 `tests/test_retrieve_dual.py` 末尾加（顶部已 import Chunk/Document/Edge/EdgeType/Node/NodeType、DeterministicEmbeddingProvider、Retriever、GraphStore、VectorStore）：

```python
def test_graph_weight_demotes_graph_only_chunk(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    # 向量命中 c1(先), c2(后)；图里 c1 LINKS_TO c3（c3 图独有 1 跳）
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    gs.upsert_node(Node(id="c3", type=NodeType.CHUNK, doc_id="d3"))
    gs.upsert_document(Document(id="d3", path="c.md", hash="h", mtime=1.0))
    gs.upsert_chunk(Chunk(id="c3", doc_id="d3", section_path="C", text="graph only", char_start=0, char_end=10))
    gs.upsert_edge(Edge(src="c1", dst="c3", type=EdgeType.LINKS_TO))
    vs.add(["c1", "c2"], emb.embed(["alpha topic", "beta topic"]),
           ["alpha topic", "beta topic"],
           [{"source_path": "a.md"}, {"source_path": "b.md"}])

    def ids(gw):
        r = Retriever(vs, emb, graph_store=gs, graph_weight=gw, per_doc_cap=None).retrieve(
            "alpha topic", k=8, hops=1)
        return [c.chunk_id for c in r.contexts]

    hi = ids(1.0)   # 高图权重：图独有 c3 排在向量命中 c2 之前
    lo = ids(0.1)   # 低图权重：c3 被压到 c2 之后
    assert hi.index("c3") < hi.index("c2")
    assert lo.index("c3") > lo.index("c2")
    gs.close()


def test_per_doc_cap_limits_same_source(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    for cid, did, path in [("c2", "d2", "b.md"), ("c3", "d2", "b.md"), ("c4", "d4", "c.md")]:
        gs.upsert_document(Document(id=did, path=path, hash="h", mtime=1.0))
        gs.upsert_node(Node(id=cid, type=NodeType.CHUNK, doc_id=did))
        gs.upsert_chunk(Chunk(id=cid, doc_id=did, section_path="S", text=cid, char_start=0, char_end=2))
        gs.upsert_edge(Edge(src="c1", dst=cid, type=EdgeType.LINKS_TO))
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{"source_path": "a.md"}])

    capped = Retriever(vs, emb, graph_store=gs, per_doc_cap=1).retrieve("alpha", k=8, hops=1)
    cap_src = [c.source_path for c in capped.contexts]
    assert cap_src.count("b.md") <= 1     # b.md 被限到 1 块
    assert "c.md" in cap_src              # 其它文档得以进入

    uncapped = Retriever(vs, emb, graph_store=gs, per_doc_cap=None).retrieve("alpha", k=8, hops=1)
    un_src = [c.source_path for c in uncapped.contexts]
    assert un_src.count("b.md") == 2      # 不限流时 b.md 两块都在
    gs.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_retrieve_dual.py -v`
Expected: FAIL（`Retriever.__init__() got an unexpected keyword argument 'graph_weight'`）

- [ ] **Step 3: 改 `Retriever.__init__`** — `src/mdgraph/retrieve.py` 第 41-49 行替换为：

```python
    def __init__(
        self,
        vector_store: VectorStore,
        embedder: EmbeddingProvider,
        graph_store: GraphStore | None = None,
        vector_weight: float = 1.0,
        graph_weight: float = 0.5,
        per_doc_cap: int | None = 2,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_store = graph_store
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self.per_doc_cap = per_doc_cap
```

- [ ] **Step 4: 改 `_dual`** — `src/mdgraph/retrieve.py` 第 74-98 行（`_dual` 方法）整体替换为：

```python
    def _dual(self, rows: list[dict], k: int, hops: int) -> RetrievalResult:
        vector_ranking = [r["chunk_id"] for r in rows]
        row_by_id = {r["chunk_id"]: r for r in rows}
        dist = self.graph_store.expand(vector_ranking, edge_types=_EXPAND_EDGES, hops=hops)
        chunk_map = self.graph_store.get_chunks(list(dist))  # 一次批量取，消 N+1
        graph_chunks = [n for n in dist if n in chunk_map]
        graph_ranking = sorted(graph_chunks, key=lambda n: (dist[n], n))
        fused = reciprocal_rank_fusion(
            [vector_ranking, graph_ranking],
            weights=[self.vector_weight, self.graph_weight],
        )
        # 所有图独有候选的 source_path（用于每文档限流 + 装配），按 doc_id 去重批量取
        doc_ids = {
            chunk_map[cid].doc_id
            for cid in fused
            if cid not in row_by_id and cid in chunk_map
        }
        doc_paths: dict[str, str] = {}
        for did in doc_ids:
            doc = self.graph_store.get_document(did)
            doc_paths[did] = doc.path if doc is not None else ""

        def _source(cid: str) -> str:
            if cid in row_by_id:
                return row_by_id[cid]["meta"].get("source_path", "")
            ch = chunk_map.get(cid)
            return doc_paths.get(ch.doc_id, "") if ch is not None else ""

        # 按融合分降序贪心选 top-k，每个 source_path 最多 per_doc_cap 块（严格上限）
        ordered: list[str] = []
        per_doc: dict[str, int] = {}
        for cid in sorted(fused, key=lambda c: (-fused[c], c)):
            if len(ordered) >= k:
                break
            src = _source(cid)
            if self.per_doc_cap is not None and per_doc.get(src, 0) >= self.per_doc_cap:
                continue
            ordered.append(cid)
            per_doc[src] = per_doc.get(src, 0) + 1

        contexts = [
            self._context(cid, fused[cid], row_by_id, chunk_map, doc_paths)
            for cid in ordered
        ]
        subgraph = self.graph_store.subgraph(ordered)
        return RetrievalResult(contexts=contexts, subgraph=subgraph)
```

- [ ] **Step 5: 更新 `Context` docstring** — `src/mdgraph/retrieve.py` 的 `Context` 类 docstring（第 22-26 行）把「dual 模式是 RRF 融合值」改为「**加权** RRF 融合值（图权重 < 向量权重以抑制 hub）」：

```python
class Context(BaseModel):
    """一条检索命中。

    score 在 dual（图+向量）模式下是**加权** RRF 融合值（图权重 < 向量权重，
    抑制 hub 节点过度放大），在纯向量模式下是 1/(1+距离) 相似度——同字段不同
    量纲，二者都「越大越相关」，仅用于排序。
    """
```

- [ ] **Step 6: 运行新测试 + 全套回归**

Run: `python -m pytest tests/test_retrieve_dual.py tests/test_retrieve.py tests/test_engine_dual.py tests/test_engine_retrieve.py -v`
然后 `python -m pytest -q`
Expected: 新增 2 个测试 + 既有 `test_retrieve_dual` 全绿；全套无回归。若某既有测试因默认 `graph_weight=0.5`/`per_doc_cap=2` 改变结果，**在报告中显式标出**（行为变更，待裁定），不要静默改既有断言。

- [ ] **Step 7: Commit**

```bash
git add src/mdgraph/retrieve.py tests/test_retrieve_dual.py
git commit -m "$(cat <<'EOF'
feat: weighted RRF + per-doc cap in _dual to de-bias graph hubs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 真实 demo 验收（手动/workflow，不进 CI）

合并后用 gemma3（`MDGRAPH_LLM_MODEL=gemma3:latest`，Ollama 运行中）构建 `examples/ai_kb` 一次，再用两套 `Retriever` 参数 A/B 查询：
- 旧：`Retriever(vs, emb, graph_store=gs, graph_weight=1.0, per_doc_cap=None)`（等价本切片前）。
- 新：`Retriever(vs, emb, graph_store=gs)`（默认 `graph_weight=0.5, per_doc_cap=2`）。

对「如何提升 RAG 的召回质量」断言：新默认下 top5 含 `reranking` 与/或 `evaluation`、`llm.md` 在 top5 ≤2 块；并打印旧 vs 新 top5 对照。

## 任务依赖与顺序

1. **Task 1**（fusion 加权）— 独立。
2. **Task 2**（`_dual` 加权 + 限流）— 依赖 Task 1。

按 1→2 顺序；demo 验收为合并后执行。

## Self-Review

- **Spec 覆盖**：§2 加权 RRF→Task 1；图权重默认→Task 2 Retriever；每文档限流→Task 2 `_dual`；§5 测试（等权不破、加权效应、per_doc_cap、既有不破）→Task 1/2 测试；§6 demo 验收→末节。✓
- **Placeholder**：无；两任务全代码 + 完整确定性测试。✓
- **类型一致**：`reciprocal_rank_fusion(..., weights=)` Task 1 定义、Task 2 `_dual` 消费；`Retriever(...,vector_weight,graph_weight,per_doc_cap)` Task 2 定义、demo/测试消费。已验算 `test_retrieve_dual` 不破（c1 0.0164 > c2 0.0082、不同 source 不触 cap）。✓
