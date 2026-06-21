# mdgraph 切片 9：缓解双引擎 hub 偏置（加权 RRF + 每文档限流）— 设计文档

- 日期：2026-06-21
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§6 检索融合）
- 前置：切片 1~8 均已合并 main；切片 8 真实 demo 验证沉淀了 hub 偏置基准

## 1. 目标与范围

修复双引擎检索的 **hub 偏置**：真实 demo 两次（mock + gemma3）测出中心节点 `llm.md`（`llm` 实体被 24 个 chunk 提及、绝对 hub）被图扩展过度放大——图独有的 hub chunk 在等权 RRF 下挤掉了纯向量的精准命中，且同一文档多块霸榜 top5。

**病根（RRF 数学）**：图独有 hub chunk（图排名第 1）拿 `1/(60+1)=0.0164`；纯向量精准命中（向量排名第 3）拿 `1/(60+3)=0.0159`。等权下 `0.0164 > 0.0159`，hub 挤掉精准命中。

**修法**：① 给 RRF 的图排名**更低权重**（图只补充、不压制）；② **每文档限流**（每个 source_path 在 top-k 最多 N 块），治同文档霸榜。

### 不在本切片范围（YAGNI）

- hub 按节点度数降权（graph-IDF）—— 更原理化但需调参，本切片用更简单的加权 RRF 解决观察到的问题；若不够再升级。
- rerank 模型、query→实体锚定 —— 仍是独立增强。
- chunk 抽取前清洗 markdown（切片 8 发现的 `[[stem]]` 被当实体）—— 独立切片 B。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| 加权融合 | `fusion.reciprocal_rank_fusion(rankings, k=60, weights=None)`：`weights` 每路权重；`None`→全 `1.0`（等权，向后兼容，`test_fusion` 不破）。`score = Σ weights[i]×1/(k+rank)` |
| 权重默认 | `Retriever` 加 `vector_weight=1.0`、`graph_weight=0.5`：图独有 hub `0.5×0.0164=0.0082` < 向量精准命中 `1.0×0.0159=0.0159`，精准命中反超 |
| 每文档限流 | `Retriever` 加 `per_doc_cap=2`：候选按 `fused` 降序贪心选 top-k，每个 `source_path` 最多 `per_doc_cap` 块；`None`→不限流。文档键用 `source_path`（向量命中取自 row meta、图独有取自 `get_document(doc_id).path`） |
| 限流语义 | **严格上限**：达 cap 的文档其余块跳过（即便结果不足 k 也不回填）——多样性优先 |
| 配置 | 三参数均为 `Retriever.__init__` 参数、可配；`MarkdownGraph.retrieve` 用默认、签名不变；纯向量路径（`graph_store=None`）完全不变 |
| 验收 | 真实 gemma3 demo A/B（旧参数 `graph_weight=1.0,per_doc_cap=None` vs 新默认）：断言新默认下「如何提升 RAG 召回」top5 里 `reranking`/`evaluation` 回到前面、`llm.md` ≤ 2 块 |

## 3. 组件

| 模块 | 职责 | 动作 |
|---|---|---|
| `src/mdgraph/fusion.py` | RRF 加权重 | 改 `reciprocal_rank_fusion` 加 `weights=None` |
| `src/mdgraph/retrieve.py` | `_dual` 加权融合 + 每文档限流 | 改 `Retriever.__init__`（加 3 参数）、`_dual`；更新 `Context.score` docstring |

## 4. `_dual` 数据流（改后）

1. `vector_ranking`、`row_by_id`、`dist=expand(...)`、`chunk_map=get_chunks(dist)`、`graph_ranking=sorted(graph_chunks,(dist,id))`（不变）。
2. `fused = reciprocal_rank_fusion([vector_ranking, graph_ranking], weights=[vector_weight, graph_weight])`。
3. 为每个候选算 `source_path`（向量命中取 row meta、图独有取 `get_document(doc_id).path`）。
4. 候选按 `(-fused, id)` 排序；贪心选 top-k，跳过 `source_path` 计数已达 `per_doc_cap` 的；`per_doc_cap=None` 不限。
5. 装配 `Context`、`subgraph(ordered)`（不变）。

## 5. 测试策略（离线确定性）

- `test_fusion`：现有等权数学不破；加 `weights=` 测试（高权重路提升该项、`None` 回退等权、权重影响排序）。
- `test_retrieve_dual`：现有断言不破（`c1` 第一、`c2` 1 跳非 hub 被拉入、subgraph 含 LINKS_TO；已验算 `c1=0.0164 > c2=0.0082`，不同 source_path 不触 cap）。
- **新增加权效应测试**（确定性）：构造 vs 返回 `c1,c2`、gs 中 `c1 LINKS_TO c3`（c3 图独有 1 跳）。`Retriever(graph_weight=1.0, per_doc_cap=None)` → `c3` 排在 `c2` 之前；`Retriever(graph_weight=0.1, per_doc_cap=None)` → `c3` 排在 `c2` 之后。锁定「降图权重压制图独有项」。
- **新增 per_doc_cap 测试**（确定性）：同一 source_path 多个图独有块都高分，`per_doc_cap=1` → top-k 中该文档 ≤1 块、其它文档得以进入；`per_doc_cap=None` → 该文档可多块。
- 全套回归（含 engine 检索测试）：默认 `graph_weight=0.5`/`per_doc_cap=2` 不得破坏既有断言；若某既有测试因新默认改变结果，须在审查中显式裁定（行为变更非缺陷）。

## 6. 验收：真实 demo A/B（手动/workflow，不进 CI）

合并后用 gemma3 构建 20 篇语料一次，再用两套 `Retriever` 参数查询对比：
- 旧：`graph_weight=1.0, per_doc_cap=None`（等价本切片前）。
- 新：默认 `graph_weight=0.5, per_doc_cap=2`。

断言新默认下，对「如何提升 RAG 的召回质量」：`reranking`/`evaluation` 出现在 top5、`llm.md` 在 top5 ≤2 块。

## 7. 给后续的接缝

- 若加权 RRF 仍不足（hub 在更大语料更顽固），升级到 graph-IDF（hub 按桥接节点度数降权）。
- chunk 抽取前清洗 markdown（切片 8 发现）为独立切片。
- 权重/cap 可在 CLI/engine 暴露为检索参数（CLI 增强切片一并做）。
