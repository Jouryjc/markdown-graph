# mdgraph 切片 5：图扩展 + RRF 融合（双引擎检索）— 设计文档

- 日期：2026-06-17
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§6 检索融合、§12 切片顺序第 5 项）
- 前置：切片 1~4 均已合并 main

## 1. 目标与范围

把纯向量 `Retriever` 升级为**图 + 向量双引擎检索**：向量召回种子 chunk → 在图上多源 BFS 扩展（结构 + 语义边）→ **RRF（倒数排名融合）** 融合「向量排名」与「图邻近度排名」→ 返回融合排序的上下文块 + **诱导子图**。这是父 spec §6 设计的双引擎合体。

### 不在本切片范围（YAGNI）

- query → 实体锚定检索（需实体描述向量化）—— 实体作连接器传导即可，锚定缓做。
- rerank 模型（RRF 之后的可选重排）—— 留作扩展。
- 增量索引 / 孤儿回收 / CLI —— 切片 6。
- 真实 provider —— 仍依赖注入，测试用 mock。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| 图引擎 | 向量种子 chunk → 沿 `CONTAINS`/`LINKS_TO`/`MENTIONS`/`RELATES_TO` 扩 `hops` 跳（默认 2，够走 chunk→entity→chunk 同提及）→ 邻居 CHUNK 候选 |
| 遍历性能 | 新增 `GraphStore.expand(seeds, edge_types, hops)`：一次 `to_networkx` + 多源 BFS，返回 `{node_id: 最小跳距}`（不含种子自身），避免逐种子重建全图 |
| 融合 | RRF：`score(c) = Σ_ranking 1/(k_rrf + rank(c))`，`k_rrf=60`，rank 为 1-based；对「向量排名」与「图邻近度排名」两路融合 |
| edge_types 默认 | `[CONTAINS, LINKS_TO, MENTIONS, RELATES_TO]`（不含 TAGGED，避免同标签 chunk 爆炸） |
| 子图 | 最终命中 chunk 的诱导子图，含 1 跳连接器（Entity/Section/链接 chunk），供可解释性 |
| 兼容 | `Retriever(vector_store, embedder, graph_store=None)`：`graph_store=None` 退化为切片 3 纯向量（切片 3 测试不破） |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `GraphStore.expand`（加） | 多源 BFS：一次建图、所有种子一起无向扩 `hops` 跳（按 edge_types 过滤），返回 `{node_id: 最小跳距}`，不含种子、忽略不存在的种子 | networkx |
| `GraphStore.subgraph`（加） | `subgraph(node_ids) -> {"nodes": [...], "edges": [...]}`：给定节点 + 其 1 跳邻居的诱导子图；node 带 `{id,type,meta}`，edge 带 `{src,dst,type}` | networkx |
| `src/mdgraph/fusion.py`（新） | `reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]`，纯函数 | — |
| `src/mdgraph/retrieve.py`（扩展） | `Retriever(vector_store, embedder, graph_store=None)`；retrieve 做双引擎融合 + 装配上下文 + 子图 | fusion, store |
| `src/mdgraph/engine.py`（扩展） | 把 `self.graph_store` 传进 `Retriever` | retrieve |

## 4. 检索数据流 `retrieve(query, k=8) -> RetrievalResult`

1. 空 / 纯空白 query → `RetrievalResult()`（空）。
2. `qvec = embedder.embed([query])[0]`；`rows = vector_store.search(qvec, k)` → **向量候选**（LanceDB 已按距离升序），向量排名 = rows 的 chunk_id 顺序。
3. **graph_store 为 None**：跳过图，直接由向量候选装配 `Context`（score = `1/(1+distance)`，沿用切片 3），subgraph 空 → 返回（切片 3 行为）。
4. **graph_store 存在**（双引擎）：
   - 种子 = 向量候选 chunk_id；`dist = graph_store.expand(种子, edge_types=[CONTAINS,LINKS_TO,MENTIONS,RELATES_TO], hops=2)`；
   - 图候选 = `dist` 中 type 为 CHUNK 的 node，按跳距升序（跳距相同按 node_id 稳定排序）→ **图排名**；
   - `fused = reciprocal_rank_fusion([向量排名, 图排名], k=60)`（候选并集 = 向量候选 ∪ 图候选）；
   - 按 `fused[c]` 降序取 top-k 得最终 chunk_ids；
   - 为每个最终 chunk 装配 `Context{chunk_id, text, score=fused[c], source_path, heading_path}`：向量命中的用 `rows` 的 text/meta；图独有的用 `graph_store.get_chunk(cid)`（text、section_path=heading_path）+ `graph_store.get_document(doc_id).path`（source_path）补全；
   - `subgraph = graph_store.subgraph(最终 chunk_ids)`；
   - 返回 `RetrievalResult{contexts, subgraph}`。

`Context` / `RetrievalResult` 模型沿用切片 3（`subgraph` 由空占位变为实际填充；纯向量路径仍空）。

## 5. 错误处理 / 边界

- 无 embedder → `retrieve()` 抛 `RuntimeError("no embedder configured")`（不变）。
- 空索引 / 向量无命中 → 空 contexts、空子图。
- 有向量命中但图无扩展（孤立块/无 llm 无实体）→ 退化为纯向量排序结果，子图为命中块的诱导子图（可能仅孤立节点 + CONTAINS）。
- `graph_store=None`（直接构造 Retriever）→ 纯向量、子图空。
- `hops`/`edge_types`/`k_rrf` 可配；默认 `hops=2`、`edge_types=[CONTAINS,LINKS_TO,MENTIONS,RELATES_TO]`、`k_rrf=60`。

## 6. 测试策略（TDD）

- **`GraphStore.expand`**：多源 BFS 最小跳距正确、按 edge_types 过滤、结果不含种子、忽略不存在的种子、hops 边界。
- **`GraphStore.subgraph`**：诱导子图含给定节点 + 1 跳连接器、节点带 type/meta、边带 type、孤立节点也返回。
- **`fusion`**：RRF 数学（两路都命中 > 单路命中、单路、空 rankings、确定性、k 影响）。
- **`retrieve`（dual）**：小语料（A 链接 B、A/B 共享实体 mock-llm）→ 断言图连接的 chunk 被 RRF 提升进结果、`subgraph` 非空且含连接节点、source/heading 正确；`graph_store=None` 退化纯向量（沿用切片 3 断言）。
- **`engine`**：`MarkdownGraph(dir, embedder, llm).build` 后 `retrieve()` 走双引擎；切片 3 简单语料（无链接无实体）排序仍合理（精确匹配块居首）。
- **离线确定性**：mock embedder + mock llm，无网络。

## 7. 技术栈

无新增第三方依赖（networkx 已在，用于 expand/subgraph；fusion 纯 Python）。

## 8. 建议的任务切分（写计划时细化）

1. `GraphStore.expand` 多源 BFS + 测试。
2. `GraphStore.subgraph` 诱导子图 + 测试。
3. `fusion.py` RRF + 测试。
4. `Retriever` 双引擎融合（graph_store 可选）+ 测试（含 graph_store=None 退化）。
5. `engine` 把 graph_store 传进 Retriever + 端到端集成测试。

## 9. 给切片 6 的接缝

- 孤儿回收（删文件后无 MENTIONS 的 Entity）+ 增量索引（按 content-hash 跳过未变文件）+ CLI（`mdgraph index/query/stats/graph export`）。
- `expand` / `subgraph` 可直接复用于 CLI 的 `graph export` 与子图可视化。
