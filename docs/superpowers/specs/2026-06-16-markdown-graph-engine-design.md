# Markdown 图谱构建与双引擎检索 — 设计文档

- 日期：2026-06-16
- 状态：已确认（待写实现计划）
- 包名（暂定）：`mdgraph`

## 1. 目标与范围

构建一个 **markdown 知识图谱引擎**：输入任意数量的 markdown 文件，将其构建成图谱以提升检索效率与正确性；构建完成后，通过 **图谱 + 向量双引擎** 检索内容，提升召回质量。

交付形态：**Python 库 + CLI**（既能 `import` 进 RAG/LLM 应用，也能命令行索引/检索）。

### 已确认的关键决策

| 维度 | 决策 |
|---|---|
| 交付形态 | Python 库 + CLI |
| 建图策略 | 混合：结构化骨架 + LLM 语义抽取 |
| 存储 | 全嵌入式、零依赖（SQLite/NetworkX + LanceDB） |
| 模型提供方 | 可插拔 provider 抽象（默认 Claude 抽取 + 可换 embedding） |
| 检索输出 | 排序上下文块 + 诱导子图（生成答案交给调用方） |
| 节点粒度/融合 | 方案 C：双层混合（结构层 + 实体语义层） |

### 不在本期范围（YAGNI）

- 不内置答案生成（`retrieve()` 只返回上下文 + 子图，生成交给调用方 LLM）。
- 不做 GraphRAG 式社区发现 / 社区摘要（方案 B 的重型能力）。
- 不内置 Web UI / 可视化前端（仅提供 `graph export` 导出供外部工具渲染）。
- 不接入外部图/向量服务（Neo4j、Qdrant 等）；存储接口预留可换，但本期只实现嵌入式后端。

## 2. 总体架构

两条主链路：

```
索引(build):    files → parse → chunk → 结构建图 → LLM语义抽取 → embed → 持久化
检索(retrieve): query → 向量召回 + 实体锚定 → 图扩展(1~2跳) → RRF融合 → {上下文块 + 子图}
```

设计原则：每个模块单一职责、通过明确接口通信、可独立测试。能在不读内部实现的前提下回答"它做什么、怎么用、依赖什么"。

## 3. 组件清单

| 模块 | 职责 | 依赖 |
|---|---|---|
| `ingest` | 发现/读取 md 文件，计算 content-hash 支持增量 | 文件系统 |
| `parse` | md → 结构化模型：标题层级、`[[wiki链接]]`、md 链接、`#标签`、frontmatter、代码块 | markdown-it-py |
| `chunk` | 章节切成 embedding 尺寸的块（标题感知 + overlap），保留来源回链 | parse |
| `graph` | 建结构层节点(Document/Section/Chunk)与边(CONTAINS/LINKS_TO/TAGGED) | store |
| `extract` | LLM 抽取实体+关系，实体消歧/合并，建 MENTIONS / RELATES_TO 边 | providers, graph |
| `embed` | 块（及实体描述）向量化 | providers, store |
| `providers` | `LLMProvider` + `EmbeddingProvider` 抽象接口；默认 Claude，可换 OpenAI/本地 | — |
| `store` | `GraphStore`(SQLite+NetworkX) + `VectorStore`(LanceDB)，接口可换 | sqlite/lancedb |
| `retrieve` | 向量召回 → 实体锚定 → 图扩展 → RRF 融合 → 输出 | store |
| `cli` | `mdgraph index/query/stats/graph export` | facade |
| `MarkdownGraph`(facade) | `build()/update()/retrieve()` 公共 API | 全部 |

### 模块间接口（要点）

- `parse.parse_document(path, text) -> Document`：纯函数，无 I/O 副作用（I/O 在 `ingest`）。
- `chunk.chunk_document(Document) -> list[Chunk]`：标题感知切分。
- `extract.extract(chunk, llm: LLMProvider) -> list[Entity], list[Relation]`：可被 mock。
- `providers.LLMProvider` / `providers.EmbeddingProvider`：抽象基类，默认实现 + mock 实现。
- `store.GraphStore` / `store.VectorStore`：抽象接口，本期仅嵌入式实现。

## 4. 数据模型（双层混合）

### 结构层节点

- `Document`：一个 md 文件。属性：id、path、hash、mtime、frontmatter。
- `Section`：文档内一个标题层级片段。属性：id、doc_id、heading_path、level。
- `Chunk`：embedding 粒度的文本块。属性：id、doc_id、section_path、text、char_range。

### 结构层边

- `CONTAINS`：Document → Section → Chunk 的包含关系。
- `LINKS_TO`：由 `[[wiki链接]]` 与 markdown 链接解析得到，指向目标 Document/Section（解析失败记为悬挂链接，保留原文）。
- `TAGGED`：Chunk/Document ↔ `Tag` 节点。

### 语义层节点/边

- `Entity`：LLM 抽取的实体。属性：id、name(规范化)、type、description、aliases。
- `MENTIONS`：Chunk → Entity（实体出现在哪个块）。
- `RELATES_TO`：Entity → Entity（带类型的语义关系，如 "depends_on"、"part_of"）。

### 实体消歧/合并策略

- 规范化名匹配（小写、去标点、别名表）优先；
- 名称近似 + 实体描述向量相似度（阈值可配）做合并候选；
- 合并保留 aliases 与来源块集合；冲突类型时保留多类型标签，不强制单一。

## 5. 存储 schema（嵌入式）

**SQLite**（结构与元数据，真源）：

- `documents(id, path, hash, mtime, frontmatter_json)`
- `nodes(id, type, doc_id, meta_json)`
- `edges(src, dst, type, weight, meta_json)`
- `chunks(id, doc_id, section_path, text, char_start, char_end)`

加载时由 SQLite 重建 **NetworkX** 内存图，用于快速多跳遍历。

**LanceDB**（向量）：

- `vectors(chunk_id, vector, text, meta_json)`
- 按 `模型名 + 维度` 版本化（目录/表名带版本），切换 embedding 模型时不串味。

## 6. 检索融合流程

1. query embedding → LanceDB 取 top-k 块（向量召回）；
2. query 对实体名/实体向量做匹配 → 锚点实体；
3. 从种子块 + 锚点实体出发，沿结构边(CONTAINS/LINKS_TO/TAGGED) + 语义边(MENTIONS/RELATES_TO) 走 1~2 跳，收集邻居块；
4. **RRF（倒数排名融合）** 合并"向量相似度排名 + 图邻近度排名"，可选结构加权（如同文档/直接链接加分）；可选 rerank 钩子；
5. 输出：

```
RetrievalResult {
  contexts: [ { chunk, score, source_path, heading_path } ],
  subgraph: { nodes, edges }   # 诱导子图，用于可解释性
}
```

## 7. 增量索引

- 每个文件存 content-hash + mtime；
- `update(paths)` 只重处理 hash 变化的文件；
- 文件删除/变更时，级联清理其 Document/Section/Chunk 节点、相关边、以及 LanceDB 中对应向量；
- 实体在失去所有来源块后做孤儿回收；
- 索引可断点续跑：重跑时按 hash 跳过已完成文件。

## 8. 错误处理

- **单文件 parse 失败**：隔离跳过 + 记录，不拖垮整批。
- **LLM 抽取失败**：指数退避重试；持续失败则该块 **降级为纯结构**（图仍可用，仅缺该块语义边）。
- **provider/网络错误**：清晰上报；索引可断点续跑。
- **embedding 维度/模型不匹配**：检测并报错；向量库按模型版本化，避免混入。
- **悬挂链接**：保留原文与标记，不报错，供后续补建。

## 9. 测试策略（TDD）

- **单测**：
  - `parse`：wiki 链接 / markdown 链接 / 标题层级 / `#标签` / frontmatter / 代码块内链接不误判等边界；
  - `chunk`：切分边界、overlap、超长章节、来源回链正确；
  - `graph`：链接解析（含相对路径、锚点、悬挂）；
  - `retrieve`：RRF 数学正确性、图扩展跳数边界；
  - `extract`：实体消歧/合并规则。
- **集成**：小型 fixture markdown 语料 → `build` → 断言图结构（节点/边数量与类型）+ `retrieve` 命中预期块与子图。
- **离线可重复**：用 **确定性 mock provider**（固定输出的假 LLM、确定性假 embedding）保证测试无需联网、快速稳定。

## 10. 技术栈

- Python 3.11+，`pyproject.toml` 打包（uv 或 pip 均可）。
- 依赖：`markdown-it-py`(解析)、`networkx`(图遍历)、`lancedb`(向量)、`pydantic`(数据模型)、`anthropic`(默认 LLM provider)、`sqlite3`(stdlib)、`typer`(CLI)、`numpy`。
- 测试：`pytest`。

## 11. CLI / 公共 API 草案

```bash
mdgraph index <path>          # 构建/更新索引（增量）
mdgraph query "<question>" --k 8
mdgraph stats                 # 节点/边/实体/向量统计
mdgraph graph export --format json|graphml   # 导出供外部可视化
```

```python
from mdgraph import MarkdownGraph

mg = MarkdownGraph(store_dir=".mdgraph")
mg.build(["./notes"])              # 或 mg.update(["./notes"])
result = mg.retrieve("如何配置 X？", k=8)
for c in result.contexts:
    print(c.score, c.source_path, c.heading_path)
print(result.subgraph.nodes, result.subgraph.edges)
```

## 12. 建议的实现切片顺序

1. 数据模型 + store（SQLite/NetworkX/LanceDB）骨架 + provider 抽象（含 mock）。
2. parse + chunk + 结构建图（无 LLM，先跑通端到端结构索引）。
3. embed + 纯向量检索（先验证向量召回链路）。
4. LLM 语义抽取 + 实体消歧（接入语义层）。
5. 图扩展 + RRF 融合（双引擎合体）。
6. 增量索引 + CLI 打磨。
