# mdgraph 切片 3：embedding 管道 + 纯向量检索 — 设计文档

- 日期：2026-06-17
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 切片顺序第 3 项）
- 前置：切片 1（基础层）、切片 2（结构索引）均已合并 main

## 1. 目标与范围

为 chunk 计算向量并写入 VectorStore（集成进 `build()`），提供 `MarkdownGraph.retrieve(query, k)` 做**纯向量召回**，返回排序上下文块。验证「embedding + 向量检索」链路，并落实图库/向量库的跨存储一致性。

### 不在本切片范围（YAGNI）

- 图扩展 + RRF 融合（切片 5）—— 本切片 `RetrievalResult.subgraph` 留空占位。
- 真实 embedding provider（Voyage / 本地 sentence-transformers）—— 单独小切片；本切片 provider 依赖注入，测试用确定性 mock。
- LLM 语义抽取 Entity（切片 4）。
- CLI（切片 6）。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| Provider | 依赖注入 `EmbeddingProvider`；测试用 `DeterministicEmbeddingProvider`；不锁供应商 |
| 嵌入时机 | 集成进 `build()`：结构建完后跨文档批量 embed，写 VectorStore |
| 检索范围 | 纯向量召回（无图扩展 / 无 RRF）；`subgraph` 留空占位 |
| 跨存储一致 | 文档删除 / reconcile / 重建时同步清除其向量 |
| score 方向 | `score = 1 / (1 + distance)`，越大越好、单调、值域 (0,1]（修正切片 1 的 distance-越小越好 陷阱） |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/embed.py` | `embed_texts(embedder, texts, batch_size=64) -> list[list[float]]`：按批上限分批调用 provider，拼接结果。隔离批处理、可单测 | providers |
| `src/mdgraph/retrieve.py` | `Context`、`RetrievalResult` 数据模型 + `Retriever(vector_store, embedder)`：embed query → 向量搜索 → 距离转相似度 → 组装上下文 | embed, store, providers |
| `src/mdgraph/indexer.py`（扩展） | 持可选 `vector_store` + `embedder`；删除/reconcile/重建时同步清向量；结构建完后批量 embed 新 chunk 写入 | embed, store |
| `src/mdgraph/engine.py`（扩展） | `MarkdownGraph(store_dir, embedder=None)`：有 embedder 则建 VectorStore；build 时嵌入；新增 `retrieve()`；`stats()` 加向量计数 | indexer, retrieve, store |
| `src/mdgraph/store/vector_store.py`（小改） | `search()` 返回键 `score` → `distance`（名实相符），同步更新其测试 | — |

`embedder=None` 时：`build()` 退化为切片 2 纯结构行为（切片 2 测试不受影响，不建 VectorStore）；`retrieve()` 抛 `RuntimeError("no embedder configured")`。

## 4. 数据模型

```
Context {
  chunk_id: str
  text: str
  score: float          # 1/(1+distance)，越大越相关
  source_path: str      # 来源文档相对路径
  heading_path: str     # 章节路径，如 "A > B"
}
RetrievalResult {
  contexts: list[Context]
  subgraph: { "nodes": [], "edges": [] }   # 切片 3 恒为空；切片 5 填充
}
```

用 pydantic 模型，定义在 `retrieve.py`（与产出它们的 Retriever 同处）。

## 5. 数据流

### build（注入了 embedder）

1. `StructuralIndexer.index()` 两遍法建结构图（切片 2 行为不变）。
2. **跨存储同步**（indexer 持 `vector_store` + `embedder` 时）：
   - reconcile 删除「不再被发现」文档时：先 `list_chunks_by_doc(did)` 取其 chunk_ids → `vector_store.delete(chunk_ids)` → 再 `graph delete_document`。
   - 每篇重建（`_build_doc`）前：先取该文档旧 chunk_ids → `vector_store.delete(旧 ids)`（避免 LanceDB add 重复行 / 旧块残留），再重建结构。
3. **批量嵌入**：结构与向量删除完成后，跨文档收集本次所有新 chunk 的 `(chunk_id, text, meta)`，`meta = {"source_path": doc.path, "heading_path": chunk.section_path}`；`embed_texts(embedder, texts)` 批量算向量；`vector_store.add(chunk_ids, vectors, texts, metas)`。

图库与向量库始终同步：删/改/reconcile 都连带向量。

### retrieve(query, k=8) -> RetrievalResult

1. `embedder.embed([query])[0]` → 查询向量；
2. `vector_store.search(qvec, k)` → 行 `(chunk_id, distance, text, meta)`；
3. `score = 1 / (1 + distance)`；按 score 降序；
4. 组装 `Context{chunk_id, text, score, source_path=meta.source_path, heading_path=meta.heading_path}`；
5. 返回 `RetrievalResult{contexts, subgraph={"nodes":[],"edges":[]}}`。

## 6. 错误处理

- 无 embedder 调 `retrieve()` → `RuntimeError("no embedder configured")`。
- 空索引 `retrieve()` → `contexts` 为空列表。
- embed provider 失败 → `build()` 清晰抛错；全量重建幂等，修好后重跑即可。
- 向量库按 `embedder.name + dim` 版本化（切片 1 已有）；换 provider 自动落到新表，不串味。
- 维度不匹配由 VectorStore 既有 schema 约束兜底。

## 7. 测试策略（TDD）

- **`embed`**：mock embedder 分批（batch_size 边界，断言批次切分正确、`len(vectors)==len(texts)`、顺序保持）。
- **`retrieve`**：小语料用 mock embedder `build` → 查 "alpha" → 断言命中 alpha 块、`score` 降序且越大越相关、空 query/空库返回空 contexts、`source_path`/`heading_path` 正确。
- **跨存储同步**：build 后 `vector count == chunk count`；删一个文件重建后该文档向量被清、计数下降；重建幂等（向量数稳定、无重复行）。
- **`engine`**：`embedder=None` 时 `retrieve()` 抛 `RuntimeError`、`build()` 仍纯结构（不建向量库）；`stats()` 含向量计数。
- **VectorStore**：`search()` 返回 `distance` 键（改名）+ 更新切片 1 对应断言。
- **离线确定性**：全程 mock embedder，无网络。

## 8. 技术栈

沿用现有依赖，无新增第三方库（VectorStore=LanceDB 已在；provider 抽象已在）。新增模块均为纯 Python。

## 9. 建议的任务切分（写计划时细化）

1. VectorStore `search` 返回 `distance` 改名 + 更新测试。
2. `embed.py` 批处理 + 测试。
3. `retrieve.py`（Context/RetrievalResult + Retriever）+ 测试（用 VectorStore 直接喂数据，不经 build）。
4. indexer 扩展：跨存储删除同步 + 批量嵌入写入 + 测试。
5. engine 扩展：`embedder` 注入、`retrieve()`、`stats()` 向量计数 + 端到端集成测试。

## 10. 给切片 4/5 的接缝

- 切片 4（Entity 抽取）：可复用 `embed_texts` 给 Entity 描述算向量；Entity 节点入图库。抽取可仿照 `_embed_and_store` 做成「结构之后的一道 post-pass」，沿用相同的 `report.errors` 跳过+`report.warnings` 告警语义。`LLMProvider`/`ExtractionResult`/`MockLLMProvider` 已在 `providers/`。
- 切片 5（图扩展 + RRF）：`Retriever` 已是向量召回的落点，扩展为「向量召回 → 图扩展 → RRF」；`RetrievalResult.subgraph` 在此填充；`score`（越大越好）方向已对齐 RRF。

## 11. 实现期发现 / 后续切片注意事项

切片 3 实现完成后整体审查沉淀：

- **purge-outside-txn 的 orphan-chunk 窗口**：`_build_doc` 在图事务**之前**调 `_purge_vectors(did)`（删旧向量）。若该文档的图事务随后回滚，旧 chunk 仍在图库、但其向量已删 → `vectors < chunks`，下次干净重建自愈。**切片 5 若加一致性/health 校验，须按「chunk→vector」方向 reconcile（给缺向量的图 chunk 补嵌入），不要只做 vector→chunk**。注意不一致来源有两个方向：errored-doc 跳过（chunk 有、vector 无，已告警）与此 rollback 窗口。
- **embed batch_size 配置接缝**：`_embed_and_store` 用 `embed_texts(embedder, texts)` 走默认 `batch_size=64`；真实 provider 有每请求行/token 上限时，切片 4/5 应把 batch_size 从配置透传。
- **`stats()["vectors"]` 条件键**：无 embedder 时无该键，调用方用 `.get("vectors")`；接入更多存储时考虑统一形状。
- 已确认合理、不再 re-litigate 的 carry-forward：provider 注入（真实 Voyage/本地 provider 单独切片）、per-call `Retriever`、facade 无 `__enter__/__exit__`、`list_chunks_by_doc` 字典序、`VectorStore.delete` 字符串谓词（chunk_id 为 hex/下划线/数字、无引号、注入安全）。
