# mdgraph 切片 4：LLM 语义抽取（实体 + 关系）— 设计文档

- 日期：2026-06-17
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 切片顺序第 4 项）
- 前置：切片 1（基础层）、切片 2（结构索引）、切片 3（向量检索）均已合并 main

## 1. 目标与范围

对每个 chunk 调用 `LLMProvider` 抽取实体与关系，按规范化名合并成 `Entity` 节点，建立 `MENTIONS`(Chunk→Entity) 与 `RELATES_TO`(Entity→Entity) 边，写入 GraphStore——构建图谱的「语义层」。**只建图，不碰向量库**。

### 不在本切片范围（YAGNI）

- 实体描述向量化 / 实体锚定检索（切片 5：图扩展 + RRF）。
- 真实 LLM provider（Claude/OpenAI）—— provider 依赖注入，测试用 `MockLLMProvider`；真实 provider 单独小切片。
- 孤儿实体/关系回收（删文件后残留）—— 切片 6（增量）。
- CLI（切片 6）。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| Provider | 依赖注入 `LLMProvider`；测试用 `MockLLMProvider`（大写词=实体、相邻实体串成 related_to 关系） |
| 抽取粒度 | 逐 chunk：`llm.extract(chunk.text)`；`MENTIONS` 是 chunk→entity |
| 消歧 | 规范化名 → `entity_id = "e_" + sha256(规范名)[:16]`；同名跨 chunk/文档自动合并 |
| 集成 | post-pass（结构/向量之后），仿 `_embed_and_store`；沿用 errored-doc 跳过 + `report.warnings` |
| 实体向量 | 不做，缓切片 5 |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/ids.py`（加） | `entity_id(name) -> "e_" + sha256(normalize_name(name))[:16]` | hashlib |
| `src/mdgraph/extract.py`（新） | `normalize_name(raw)` + `extract_graph(chunks, llm) -> ExtractionBundle`：逐 chunk 抽取、按 entity_id 聚合、收集 mentions/relations、记 failed_chunks。纯函数 | providers, ids |
| `src/mdgraph/indexer.py`（扩展） | 持可选 `llm`；post-pass `_extract_and_store(docs, report)` | extract |
| `src/mdgraph/engine.py`（扩展） | `MarkdownGraph(store_dir, embedder=None, llm=None)`，透传 llm | indexer |

`llm=None` 时：不建语义层，行为与切片 3 完全一致（切片 1/2/3 测试不受影响）。

## 4. 规范化与 ID

`normalize_name(raw)`：小写 → 把非字母数字（含标点、空白）的连续段替换为单个空格 → 首尾 strip。例：`"Foo, Bar"` 与 `"foo  bar"` 都归一为 `"foo bar"`。

`entity_id(name) = "e_" + sha256(normalize_name(name).encode())[:16]`（hex/下划线/数字，无引号）。

## 5. 数据结构

```
EntityRecord {
  id: str            # entity_id
  name: str          # canonical：首次出现的原始名
  type: str          # 首个非空 type（默认 "concept"）
  description: str    # 首个非空描述（mock 下为空串）
  aliases: list[str]  # 其它出现过的原始名（≠ canonical），排序去重
}
ExtractionBundle {
  entities: list[EntityRecord]
  mentions: list[tuple[str, str]]        # (chunk_id, entity_id)，去重
  relations: list[tuple[str, str, str]]  # (src_entity_id, tgt_entity_id, rel_type)，去重、保留方向
  failed_chunks: list[str]               # 抽取抛异常的 chunk_id
}
```

## 6. 数据流（build，注入了 llm）

结构两遍法 + 向量（若有 embedder）照旧。其后 post-pass `_extract_and_store(docs, report)`：

1. 收集所有**非 errored 文档**的 chunk `(chunk_id, text)` 列表；
2. `extract_graph(chunks, llm)`：
   - 逐 chunk `try: llm.extract(text)`；异常 → `failed_chunks.append(chunk_id)`，continue；
   - 每个抽出实体：`eid = entity_id(name)`，按 eid 聚合（canonical/aliases/type/description），记 `(chunk_id, eid)` 入 mentions；
   - 每条关系：`sid=entity_id(src)`、`tid=entity_id(tgt)`，**仅当 sid、tid 都在本次抽出实体集合中**才加入 relations（避免幽灵实体）；
   - 去重 mentions 与 relations。
3. 事务内写库：
   - 每个 `EntityRecord` → `upsert_node(Node(id, type=ENTITY, doc_id=None, meta={name,type,description,aliases}))`；
   - 每个 mention → `upsert_edge(Edge(src=chunk_id, dst=entity_id, type=MENTIONS))`；
   - 每个 relation → `upsert_edge(Edge(src=sid, dst=tid, type=RELATES_TO, meta={"type": rel_type}))`。
4. `failed_chunks` → 每个追加 `report.warnings`。

`IndexReport` 增 `entities: int = 0`（本次写入的实体数）。

## 7. 重建/删除语义（重要）

- `Entity` 节点 `doc_id=None`（同 Tag），`delete_document` 不删它；重建按规范名 upsert → 幂等。
- `MENTIONS`(src=chunk) 随 `delete_document` 删除并在 post-pass 重建 → 幂等。
- `RELATES_TO`(实体↔实体) 两端 `doc_id=None`，`delete_document` 不删；重建按 `(src,dst,type)` PK upsert → 不重复。
- **孤儿回收缓切片 6**：删文件后，仅在该文档出现过的 Entity / RELATES_TO 会残留（与 Tag 同款）。本切片保证：**不变语料重建幂等**；**删文件不收缩实体计数**（切片 6 处理）。

## 8. 错误处理

- 单 chunk 抽取异常 → 跳过该 chunk + `report.warnings`（降级为纯结构，图仍可用）。
- 结构 pass-2 出错的文档 → 不进抽取（沿用跳过 + 告警）。
- `RELATES_TO` 仅当两端实体都被抽出时建立。

## 9. 测试策略（TDD）

- **`ids.entity_id`**：确定性、规范化（`"Foo, Bar"` 与 `"foo bar"` 同 id）、无引号。
- **`extract`**：MockLLMProvider 确定性 → 跨 chunk 同名实体合并（canonical/aliases）、mentions 去重、relations 去重保向、`failed_chunks`（注入会抛的 fake LLM）。
- **`indexer`**：build(llm) → ENTITY 节点 + MENTIONS + RELATES_TO 边均入图；同一实体出现在两文档 → 1 个 Entity 节点 + 2 条 MENTIONS；不变语料重建幂等（实体/边计数稳定）；`llm=None` → 无语义层（切片 3 行为不变）。
- **`engine`**：`MarkdownGraph(dir, llm=mock).build()` → 实体入图；同时给 embedder 时 `retrieve()` 仍工作；`llm=None` 不受影响。
- **离线确定性**：全程 MockLLMProvider，无网络。

## 10. 技术栈

无新增第三方依赖（`LLMProvider`/`MockLLMProvider`/`Node`/`Edge`/`EdgeType.MENTIONS`/`EdgeType.RELATES_TO`/`NodeType.ENTITY` 均在切片 1 已就绪）。新增模块纯 Python。

## 11. 给切片 5/6 的接缝

- 切片 5（图扩展 + RRF）：语义层已就位——向量召回的种子 chunk 可沿 `MENTIONS` 找实体、再沿 `RELATES_TO`/`MENTIONS` 扩展到相关 chunk；实体描述向量化在此做。`GraphStore.neighbors(node, edge_types, hops)` 已支持按边类型多跳。
- 切片 6（增量 + 孤儿回收）：删文件后回收无 MENTIONS 的孤儿 Entity 及其 RELATES_TO；与跨存储 reconcile 合并实现。

## 12. 实现期发现 / 后续切片注意事项

切片 4 实现完成后整体审查沉淀：

- **切片 5 关系权重**：`RELATES_TO` 边的语义类型在 `meta["type"]`，`weight` 仍是默认 1.0。若 RRF/图打分要按关系类型加权，需在切片 5 自行从 `meta.type` 派生权重（数据已在，未预聚合）。
- **切片 5 遍历方向**：`RELATES_TO` 在存储中是有向的，但 `GraphStore.neighbors()` 做**无向**扩展——这通常正是扩展想要的，切片 5 确认即可。
- **切片 6 孤儿回收谓词**：删文件后，仅在该文档出现过的 Entity 残留为无入边 MENTIONS 的孤儿节点 + 悬挂 RELATES_TO（`doc_id=None` 屏蔽了 `delete_document`，与 Tag 同款）。回收谓词很干净：「ENTITY 节点入边 MENTIONS 数为 0 → 删该节点及其相连 RELATES_TO」，一个回收例程可同时覆盖 Tag。
- **type 非严格 first-seen**：实体 `name` 是首见 canonical，但 `type` 在 `("", "concept")` 时会被后续非默认 type 覆盖（把 `concept` 当弱默认，符合 spec 只钉死 name）。
- MockLLMProvider 把大写词当实体，链接文本里的 `See` 等会被误当实体——纯 mock 假象，真实 provider（缓做）无此问题。
