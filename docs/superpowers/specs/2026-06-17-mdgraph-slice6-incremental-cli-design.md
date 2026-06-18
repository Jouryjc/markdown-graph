# mdgraph 切片 6：增量索引 + 孤儿回收 + CLI — 设计文档

- 日期：2026-06-17
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 切片顺序第 6 项）
- 前置：切片 1~5 均已合并 main（核心「图+向量双引擎检索」已交付）

## 1. 目标与范围

把引擎从「每次全量重建」升级为可**增量运营**，回收删文件后残留的孤儿语义节点，消除检索热路径的 N+1，并补上**命令行入口**——项目收尾切片。

### 不在本切片范围（YAGNI）

- 真实 Voyage/Claude provider —— 仍是单独小切片。CLI 通过 dotted-path 动态加载 provider，自己不绑定任何具体实现。
- 增量的「邻居变更即时重解析链接」——unchanged doc 的链接解析状态在它自身变更前不更新（标准 dirty-set 取舍，见 §4 已知边界）。
- 图可视化前端 / `graph export` 的渲染——只产出 JSON，渲染留给消费方。
- 并发/文件监听（watch 模式）——一次性 `index` 即可，watch 缓做。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| CLI provider | **provider 无关**：CLI 不内置任何真实 provider；embedder/llm 经 dotted-path `pkg.mod:attr` 动态加载（`importlib`）。真实 provider 切片只需新增模块，CLI 零改动 |
| 增量判定 | 按 `content-hash`：`stored hash == 当前 hash` 即 unchanged，跳过该 doc 的 build/link/embed/extract；所有 doc 仍 parse 以喂链接解析索引 |
| 增量默认 | `incremental=True`（默认）；`--full` / `incremental=False` 强制全量重建 |
| 孤儿回收 | 每次 `index()` 末尾自动跑（与 removed-doc reconcile 同属存储卫生）；谓词见 §5 |
| 回收时机 | 在 reconcile + build + extract **之后**，确保不误删「刚 `delete_document` 待重建」的实体 |
| N+1 | 新增 `GraphStore.get_chunks(ids) -> dict`，批量替换 `_dual` 的逐节点 `get_chunk` |
| CLI 框架 | typer（已在 pyproject 依赖）；入口 `[project.scripts] mdgraph = "mdgraph.cli:app"` |
| `graph export` | 无 seeds 导全图、有 seeds 走 `expand`+`subgraph`；输出 `subgraph()` 的 `{nodes, edges}` JSON |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `GraphStore.get_chunks`（加） | `get_chunks(ids: list[str]) -> dict[str, Chunk]`：一条 `WHERE id IN (...)` 批量取，缺失 id 不在 dict | sqlite |
| `GraphStore.reclaim_orphans`（加） | 删无 MENTIONS 入边的 ENTITY、无 TAGGED 入边的 TAG，连带删以它们为端点的边；返回回收节点数 | sqlite |
| `GraphStore.export_graph`（加） | `export_graph() -> {"nodes": [...], "edges": [...]}`：全图导出（node 带 `{id,type,meta}`、edge 带 `{src,dst,type}`，确定性排序），供 CLI 无 seeds 的 `graph export` | sqlite |
| `indexer.index`（扩展） | `incremental: bool = True`；unchanged doc 跳过；built docs 才 embed/extract；末尾 `reclaim_orphans()`；`IndexReport` 加 `unchanged`/`reclaimed` | graph_store |
| `retrieve._dual`（改） | 用 `get_chunks` 批量取图独有 chunk；按 doc_id 去重批量取 document 补 source_path | graph_store |
| `engine.MarkdownGraph.build`（扩展） | 透传 `incremental` | indexer |
| `src/mdgraph/cli.py`（新） | typer app：`index` / `query` / `stats` / `graph export`；dotted-path 加载 provider | engine, typer |

## 4. 增量索引数据流（`index(paths, ..., incremental=True)`）

1. `discover` + `read_file` + `parse_document` **所有** 发现的 doc；建 `title_index`/`path_index`/`slug_index`（不变，供链接解析）。
2. `stored = dict(self.store.list_documents())`；对每个 doc：`unchanged = incremental and stored.get(did) == doc.hash`。
   - unchanged doc 进 `unchanged_ctxs`，`report.unchanged += 1`；
   - 其余进 `built_ctxs`（new/changed）。
3. **reconcile removed**（不变）：stored 里但本次未发现的 doc → `_purge_vectors` + `delete_document`，`report.removed += 1`。
4. **build**：仅对 `built_ctxs` 跑 `_build_doc`（`report.indexed += 1`，失败入 `report.errors`）。
5. **Pass 3 链接**：仅对 `built_ctxs`（无错的）重建 LINKS_TO（unchanged doc 的链接原样保留）。
6. **embed**：`_embed_and_store(built_ctxs, report)`（仅 built）。
7. **extract**：`_extract_and_store(built_ctxs, report)`（仅 built）。
8. **reclaim**：`report.reclaimed = self.store.reclaim_orphans()`。
9. 返回 `report`。

`incremental=False` → 所有发现的 doc 都进 `built_ctxs`（退化为切片 5 的全量行为；unchanged 恒为 0）。

### 已知边界（文档化，非缺陷）

- unchanged doc 链接到的目标这次才新增/消失，**不会**更新该 unchanged doc 的链接解析状态，直到该 doc 自身变更——标准增量 dirty-set 取舍。需要修正时用 `--full` 全量重建。
- unchanged doc 的向量/实体原样保留（这正是增量收益）：embedder/llm 配置或模型版本变更后，对未变文件需 `--full` 才会重嵌/重抽。
- 跨文档共享的 Entity 的 meta（type/description/aliases）按「当前重建批次」聚合：若某实体的富 meta 来自一个**未变更**文档，而本次只重建了另一个裸提及它的文档，增量重抽取会把该实体 meta 覆盖为裸值（MENTIONS 边不受影响，检索仍能命中该实体）。这与上文 staleness 同属 dirty-set 取舍——`--full` 全量重建可恢复。正确的增量实体 meta 重聚合需要 per-doc 来源追踪，留给后续「真实 LLM provider」切片（mock provider 下实体 meta 恒为空，无可见影响）。

## 5. 孤儿回收谓词（`reclaim_orphans`）

```
orphan_entities = ENTITY 节点 id 中，不出现在任何 MENTIONS 边 dst 的
orphan_tags     = TAG 节点 id 中，不出现在任何 TAGGED 边 dst 的
orphans = orphan_entities ∪ orphan_tags
删除 nodes WHERE id IN orphans
删除 edges WHERE src IN orphans OR dst IN orphans   # 连带清悬挂 RELATES_TO 等
返回 len(orphans)
```

- 一个事务内完成。`ENTITY`/`TAG` 节点 `doc_id=None`，`delete_document` 不动它们，故回收是唯一清理途径。
- 幂等：连续两次 `reclaim_orphans()`，第二次返回 0。
- 与检索解耦：`_dual` 本就靠 `get_chunk is not None` 过滤，孤儿 Entity 永不进 Context；回收纯属存储卫生，不改检索语义。

## 6. `get_chunks` 与 `_dual` 改写

`get_chunks(ids: list[str]) -> dict[str, Chunk]`：空 ids → `{}`；否则 `SELECT * FROM chunks WHERE id IN (?,...)`，组装 `{id: Chunk}`。

`_dual` 改写：
- `dist = expand(...)`；`chunk_map = get_chunks(list(dist))`；`graph_chunks = [n for n in dist if n in chunk_map]`（替掉 N 次 `get_chunk`）。
- 最终 `ordered` 里图独有的 chunk：text/heading 从 `chunk_map[cid]` 取；source_path 从 `get_document(doc_id)` 取——先按 `chunk_map` 里图独有 chunk 的 `doc_id` 去重，批量 `get_document`（数量 ≤ 命中文档数，少量；不引入新批量方法）。
- 行为不变，仅查询次数从 `O(扩展节点数)` 降到常数级。

## 7. CLI 设计（`mdgraph`）

dotted-path 加载器 `_load(dotted: str)`：`mod, _, attr = dotted.partition(":")`；`obj = getattr(import_module(mod), attr)`；`obj()` 构造实例（attr 为零参工厂或无参类）；失败 → `typer.BadParameter` 友好报错。

| 命令 | 选项 | 行为 |
|---|---|---|
| `index PATHS...` | `--store DIR`（默认 `.mdgraph`）`--embedder DOTTED` `--llm DOTTED` `--full` `--max-chars N`（默认 1200）`--overlap N`（默认 150） | 构造 `MarkdownGraph(store, embedder?, llm?)` → `build(paths, incremental=not full, ...)` → 打印 `indexed/unchanged/removed/reclaimed/entities/errors` 摘要 |
| `query TEXT` | `--store DIR` `--embedder DOTTED`（必需）`-k N`（默认 8）`--json` | 无 embedder → 报错指引；默认逐条打印 `source_path` `heading_path` `score` + 截断 text；`--json` 输出完整 `RetrievalResult`（contexts + subgraph） |
| `stats` | `--store DIR` `--embedder DOTTED`（可选，仅为挂 vector_store 报 vectors 计数） | 打印 `MarkdownGraph.stats()` |
| `graph export` | `--store DIR` `--seeds id,id` `--hops N`（默认 2）`-o FILE` | 无 seeds → `export_graph()` 全图；有 seeds → `expand(seeds, hops)` 后对结果 + 种子调 `subgraph()`；JSON 到 stdout 或 `-o` |

`graph export` 与 `stats` 不需要 embedder 即可工作（纯图）。`query` 必需 embedder。所有命令默认 `--store .mdgraph`。

## 8. 错误处理 / 边界

- dotted-path 加载失败（模块不存在/attr 不存在/构造异常）→ `typer.BadParameter`，非 traceback。
- `query` 未给 `--embedder` → 退出码非 0 + 「configure an embedding provider via --embedder pkg.mod:attr」。
- 空 store / 无命中 → 空结果，不报错。
- `graph export --seeds` 含图中不存在的 id → 忽略（沿用 `expand`/`subgraph` 既有「忽略不存在」语义）。
- 增量与回收交互：回收在 extract 之后跑，changed doc 的实体先被 `delete_document` 清 MENTIONS 再重建，回收只删最终仍无 MENTIONS 的——不误删。

## 9. 测试策略（TDD，全程离线确定性）

- **`get_chunks`**：批量取多个、含缺失 id（不在 dict）、空 ids → `{}`。
- **`reclaim_orphans`**：删无 MENTIONS 的 ENTITY + 其悬挂 RELATES_TO、删无 TAGGED 的 TAG；保留有 MENTIONS 的 ENTITY；返回计数正确；二次回收返回 0（幂等）。
- **增量（indexer）**：建 → 改一个文件重 build → 只该文件重建（其余 `report.unchanged`，mtime/计数稳定）；新增文件 → indexed；删文件 → removed；`incremental=False` → 全量（unchanged=0）。
- **index 自动回收**：删唯一提及某实体的 doc 重 build → 该 Entity 被回收，`report.reclaimed >= 1`，`get_node(entity_id)` 为 None。
- **`_dual` 批量等价**：改写后检索结果（contexts 顺序/score、subgraph）与切片 5 等价（沿用 `test_retrieve_dual` 断言不破）。
- **`export_graph`**：全图节点/边计数与 stats 一致、形状 `{nodes, edges}`、确定性排序。
- **CLI**：typer `CliRunner` + `--embedder mdgraph.providers.mock:DeterministicEmbeddingProvider`：`index`→`query`→`stats`→`graph export` 端到端跑通；`query` 无 `--embedder` 退出码非 0；dotted-path 错误 → `BadParameter`；`index --llm mdgraph.providers.mock:MockLLMProvider` 建实体、`graph export` 见 ENTITY 节点。

## 10. 技术栈

无新增第三方依赖（typer 已在 `pyproject.toml` 依赖；`importlib`/`sqlite3`/`json` 标准库）。新增 `cli.py` + GraphStore/indexer 扩展。

## 11. 建议的任务切分（写计划时细化）

1. `GraphStore.get_chunks` 批量 + 测试；改写 `retrieve._dual` 用批量（等价测试）。
2. `GraphStore.reclaim_orphans` + `export_graph` + 测试。
3. 增量索引（`indexer.index(incremental)` + `IndexReport.unchanged`、built-only embed/extract、末尾 reclaim + `report.reclaimed`；`engine.build` 透传）+ 测试。
4. CLI `index` + `query`（dotted-path 加载器）+ 测试。
5. CLI `stats` + `graph export` + `[project.scripts]` 入口 + 端到端测试。
6. dual score docstring + 收尾整体测试。

## 12. 收尾

切片 6 合并后，6 切片路线全部完成：引擎可增量索引任意 markdown、建结构+语义图谱与向量、双引擎检索返回上下文+子图、命令行可用。剩余增强（真实 Voyage/Claude provider、watch 模式、图可视化前端、rerank）均为后续独立小切片。
