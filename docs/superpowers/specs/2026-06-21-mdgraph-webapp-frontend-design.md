# mdgraph webapp（FastAPI 后端 + React/Vite 前端）— 设计文档

- 日期：2026-06-21
- 状态：已确认（待写实现计划）
- 子项目目录：`webapp/`（仓库根 = `mdgraph` 项目，`pyproject.toml` 已含 `pythonpath=["src"]`）
- 依赖引擎：现有 `mdgraph` 双引擎检索库（结构图 + 向量），**本子项目只读式复用，不改引擎语义**

## 0. 一句话定位

在已有的 `mdgraph` 库之上，搭一个**全栈 Web 平台**：FastAPI 把引擎的检索/图谱/统计能力包成 REST API，React/Vite 前端提供搜索、图谱探索、统计、文档浏览四个页面。后端是引擎的**薄适配层**（不重新实现检索算法），前端是引擎能力的**可视化与交互层**。

## 1. 目标与范围

### 1.1 目标

1. 把 `MarkdownGraph` 引擎的能力通过稳定的 REST 契约暴露给浏览器：
   - 双引擎/纯向量检索（带可调旋钮：`k`、`mode`、`graph_weight`、`per_doc_cap`、`hops`）；
   - 全图导出与按种子扩展的子图；
   - 单节点 + 邻居详情；
   - 文档列表 / 单文档（chunks + 出链）；
   - 实体 Top 榜（按 MENTIONS 入度）；
   - 统计面板；
   - 同步索引（MVP）。
2. 前端用力导向图（canvas）把检索/图谱结果**可视化且可解释**：哪些 chunk 是图扩展带进来的（`from_graph`）、节点之间是什么关系。
3. 工程纪律：后端测试**全程离线确定性**（Mock provider + tmp store，零网络）；前端有严格 TS 构建门禁 + 组件测试。

### 1.2 不在本期范围（YAGNI）

明确**不做**，以免过度设计：

- **认证 / 授权（auth）**：无登录、无 token、无 session。API 默认本地可信环境（localhost）。
- **多用户 / 多租户**：单一引擎单例，单一 store，所有请求共享同一份索引。无 per-user 数据隔离。
- **实时索引流式进度（real-time index streaming）**：`POST /api/index` 是**同步**的，请求返回时索引已完成。无 WebSocket / SSE / 进度条轮询 / 后台任务队列。
- **Docker / 部署（deploy）**：不写 Dockerfile、compose、k8s、CI 部署。本子项目只交付源码 + 本地运行说明（`webapp/README.md`）。

这些都是有意省略；如未来需要，再单独立项。

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│ Browser (http://localhost:5173)                              │
│  React 18 + TS + Vite 5 + Tailwind v3.4                       │
│  react-query v5 ── typed fetch client ── react-router v6     │
│  react-force-graph-2d (canvas)                               │
└───────────────┬─────────────────────────────────────────────┘
                │  /api/*  (Vite dev proxy → :8000)
                ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI (http://localhost:8000)  prefix /api  CORS:5173       │
│  routers: health/stats/query/graph/documents/entities/index  │
│  schemas.py (pydantic 响应模型 = 前端 types.ts 的唯一真源)   │
│  engine_provider.py  ── LAZY SINGLETON ──┐                   │
└──────────────────────────────────────────┼──────────────────┘
                                           ▼
┌─────────────────────────────────────────────────────────────┐
│ mdgraph 引擎 (src/mdgraph，只读复用)                          │
│  MarkdownGraph(store_dir, embedder, llm)                     │
│   ├─ graph_store: GraphStore (SQLite + NetworkX)             │
│   ├─ vector_store: VectorStore (LanceDB)  ← 仅在 embedder 就绪 │
│   └─ Retriever(...).retrieve(query, k, hops)                 │
└─────────────────────────────────────────────────────────────┘
```

设计原则：

- **后端薄、引擎厚**：检索/扩展/融合/导出全部委托给引擎现有方法（`Retriever.retrieve`、`GraphStore.export_graph/expand/subgraph/to_networkx` 等）。后端只做：参数映射、`from_graph` 标注、字段裁剪、错误转 HTTP。
- **契约单一真源**：`webapp/backend/schemas.py` 的 pydantic 响应模型是唯一真源，前端 `src/api/types.ts` **逐字段镜像**（字段名 + 类型一致）。
- **优雅降级**：引擎可在「无 embedder」下提供图谱/统计/文档/节点能力；只有需要向量的 `query`/`index` 在 embedder 不可用时返回 503，**绝不**让应用启动崩溃。

## 3. 引擎复用面（基于真实源码核对）

以下是后端将依赖的引擎事实（已核对 `src/mdgraph/engine.py`、`retrieve.py`、`store/graph_store.py`、`models.py`、`providers/mock.py`、`cli.py`）：

### 3.1 入口

```python
from mdgraph import MarkdownGraph
from mdgraph.models import Node, Edge, NodeType, EdgeType, Document, Chunk
from mdgraph.retrieve import Retriever, RetrievalResult, Context
```

- `MarkdownGraph(store_dir, embedder=None, llm=None)`
  - `.build(paths, root=None, max_chars=1200, overlap=150, incremental=True) -> IndexReport`
  - `.retrieve(query, k=8) -> RetrievalResult`（用默认 Retriever 旋钮）
  - `.stats() -> dict[str,int]`：`documents, sections?, chunks, entities?, tags?, nodes, edges`，**embedder 就绪时附 `vectors`**（来自 `vector_store.count()`）
  - `.graph_store`、`.vector_store`（可能为 `None`）、`.embedder`、`.close()`
  - 构造时：`store_dir.mkdir(parents=True, exist_ok=True)`，并打开 `GraphStore(store_dir/"graph.db")`；仅当 `embedder is not None` 才建 `VectorStore`。

> 注意：`MarkdownGraph.stats()` 实际返回的是 `GraphStore.stats()`（`documents/nodes/edges/chunks`）+ 可选 `vectors`。`sections/entities/tags` 不一定在该 dict 里。因此 `GET /api/stats` 的响应模型对所有计数键**缺失即默认 0**（见 §5.2），不依赖引擎填全。

### 3.2 Retriever（query 的核心）

`mdgraph.retrieve.Retriever(vector_store, embedder, graph_store=None, vector_weight=1.0, graph_weight=0.5, per_doc_cap=2)`，方法 `.retrieve(query, k=8, hops=2) -> RetrievalResult`。

- **`graph_store=None` ⇒ 纯向量模式**：`_vector_only`，`score = 1/(1+distance)`（越大越相关），`subgraph` 为空 `{"nodes":[],"edges":[]}`。
- **`graph_store` 给定 ⇒ dual 模式**：向量召回 → `expand(vector_ranking, edge_types=[CONTAINS,LINKS_TO,MENTIONS,RELATES_TO], hops)` → RRF 加权融合（`weights=[vector_weight, graph_weight]`）→ 每 `source_path` 最多 `per_doc_cap` 块的贪心 top-k → 装配 `contexts` + `subgraph(ordered)`。

`Context`（pydantic）字段：`chunk_id, text, score(float, 越大越相关), source_path="", heading_path=""`。
`RetrievalResult`：`contexts: list[Context]`、`subgraph: dict {"nodes":[{id,type,meta}], "edges":[{src,dst,type}]}`。

> `score` 在 dual 与 vector 两模式下量纲不同（加权 RRF vs 相似度），仅用于排序，前端只做相对展示，不解释绝对值。

### 3.3 GraphStore（图/文档/节点的数据面）

- `export_graph() -> {"nodes":[{id,type,meta}], "edges":[{src,dst,type}]}`，**确定性排序**：nodes 按 `id`，edges 按 `(src,dst,type)`。
- `expand(seed_ids, edge_types=None, hops=1) -> {node_id: min_hop_dist}`，**不含种子自身**，忽略不在图中的种子。
- `subgraph(node_ids) -> {"nodes":[...],"edges":[...]}`：给定节点 + 其 **1 跳邻居** 的诱导子图（确定性排序）。
- `neighbors(node_id, edge_types=None, hops=1) -> set[str]`。
- `to_networkx() -> nx.MultiDiGraph`：节点带 `type/doc_id/meta`，边以 `type` 为 key 且带 `weight`；后端用它推导单节点的 out/in 邻居。
- `get_document(doc_id) -> Document|None`、`get_node(node_id) -> Node|None`、`get_chunk(chunk_id) -> Chunk|None`。
- `list_chunks_by_doc(doc_id) -> list[Chunk]`（按 id 排序）、`list_documents() -> list[(id, hash)]`（按 id 排序）、`stats() -> dict[str,int]`。

### 3.4 模型与枚举

- `NodeType`：`document, section, chunk, entity, tag`。
- `EdgeType`：`contains, links_to, tagged, mentions, relates_to`。
- `Document(id, path, hash, mtime, frontmatter)`、`Chunk(id, doc_id, section_path, text, char_start, char_end)`、`Node(id, type, doc_id, meta)`、`Edge(src, dst, type, weight, meta)`。
- **Entity 节点**：`type=entity`，人类可读名在 `node.meta`（优先 `meta["name"]`，否则回退到 `id`）；实体子类型在 `node.meta.get("type","")`（可能为空）。
- **MENTIONS 边方向**：`chunk -> entity`。因此某实体的「被提及次数」= 指向它的 `MENTIONS` **入边数**（in-degree）。

### 3.5 Provider（测试 vs 真实）

- **测试用 Mock（仅 pytest）**：在 `mdgraph.providers.mock` 中。核对源码后确认确切类名为：
  - `DeterministicEmbeddingProvider(dim=16, name="mock-embed")` —— 实现 `EmbeddingProvider`，`embed()` 基于 token 哈希、确定性、单位归一化。
  - `MockLLMProvider()` —— 实现 `LLMProvider`，`extract()` 把大写开头单词当实体、相邻实体串成链式关系。
  - 后端测试 fixture 用 `DeterministicEmbeddingProvider` 作为 `embedder`，`MockLLMProvider` 作为 `llm`。**不要**臆造 `MockEmbeddingProvider` 之类不存在的名字。
- **真实 provider（永不进 pytest）**：`providers.fastembed_embedder:FastEmbedProvider`、`providers.anthropic_extractor:ClaudeExtractor`、`providers.local_llm_extractor:LocalLLMExtractor`。生产/手动运行时经 dotted-path 动态加载（与 CLI 的 `_load` 同构）。

## 4. 后端架构（`webapp/backend/`）

### 4.1 引擎单例（`engine_provider.py`）— 核心

引擎是**惰性单例（LAZY SINGLETON）**。第一次需要时构造，之后复用，进程退出时 `close()`。

**配置（`settings.py`，从环境变量读，带默认）：**

| 设置 | 环境变量 | 默认 |
|---|---|---|
| store 目录 | `MDGRAPH_STORE` | `./.mdgraph`（相对仓库根） |
| embedder dotted-path | `MDGRAPH_EMBEDDER` | `mdgraph.providers.fastembed_embedder:FastEmbedProvider` |
| （可选）llm dotted-path | `MDGRAPH_LLM` | 留空（索引不抽实体时可不配） |

`settings.py` 用 pydantic-settings 或简单 `os.environ` 读取均可（无需引外部依赖时优先标准库），暴露 `Settings` 对象或模块级常量：`store_dir: Path`、`embedder_path: str`、`llm_path: str | None`、`allowed_origins: list[str]`。

**单例职责：**

```python
# 伪代码契约（非最终实现）
class EngineProvider:
    def get_engine(self) -> MarkdownGraph: ...        # 惰性构造，含/不含 embedder
    def get_embedder_or_none(self) -> EmbeddingProvider | None: ...
    def require_query_capable(self) -> tuple[VectorStore, EmbeddingProvider, GraphStore]:
        # embedder/vector_store 缺失时抛 EngineUnavailable → 路由层转 503
```

**优雅降级规则（必须遵守）：**

- 构造引擎时**不要**因 embedder 导入失败/依赖缺失/store 缺失而崩溃。
- embedder dotted-path 加载失败（`ImportError`/构造异常）⇒ 记录原因，引擎仍以 `embedder=None` 构造 ⇒ `graph_store` 可用。
- 这样 `stats / graph / graph/expand / node / documents / document / entities` 这些**只依赖 GraphStore** 的端点照常工作。
- 只有 `query`、`index` 需要 embedder；不可用时返回 **HTTP 503** + `{detail: "<清晰原因>"}`，例如 `"embedder unavailable: <import error>"` 或 `"vector store not initialized; run indexing first"`。

### 4.2 SQLite / 线程安全（必须处理，已核对源码）

**问题事实**：`GraphStore.__init__`（`store/graph_store.py:54`）执行

```python
self.conn = sqlite3.connect(self.db_path)   # 默认 check_same_thread=True
```

**没有** `check_same_thread=False`。FastAPI 把同步端点丢进 **threadpool** 执行，不同请求可能落在不同线程。一个跨线程复用的连接会触发：

> `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`

**本子项目的决策（在 `engine_provider.py` 层处理，不改引擎源码）：**

采用「**在引擎层重开一条允许跨线程的连接**」策略——单例构造出 `MarkdownGraph` 后，把其 `graph_store.conn` 替换为一个用 `check_same_thread=False` 打开的连接，并保留与原始一致的 `row_factory = sqlite3.Row`：

```python
# engine_provider.py，单例构造完成后立刻执行（在任何请求之前，单线程内）
import sqlite3
gs = engine.graph_store
gs.conn.close()
gs.conn = sqlite3.connect(gs.db_path, check_same_thread=False)
gs.conn.row_factory = sqlite3.Row
```

理由与权衡（必须在代码注释 + README 记录）：

1. **为什么不改引擎**：引擎库面向通用单线程/CLI 场景，`check_same_thread=True` 是合理默认；webapp 是引擎的下游消费者，线程模型是 webapp 引入的，应在 webapp 适配层解决，保持引擎纯净。若未来引擎自身要支持并发服务，再回流到引擎。
2. **为什么这样安全**：本子项目的写操作只有 `POST /api/index`（同步、MVP）。SQLite 默认 `serialized` 线程模式下，单个连接可被多线程使用（`check_same_thread=False` 仅解除 Python 层的同线程断言）；只读端点是 `SELECT`，并发读安全。
3. **额外护栏（防御）**：在 `engine_provider.py` 内对**写路径**（`index`）用一把 `threading.Lock` 串行化，避免两个并发索引交叉提交。读路径不加锁（LanceDB/SQLite 读并发安全）。
4. **替代方案（记录但不采用）**：每请求新开连接 / 连接池——会丢失内存态、增加复杂度，且 `MarkdownGraph` 单例语义最简单。故选「单连接 + `check_same_thread=False` + 写锁」。

实现时**必须先验证** `GraphStore` 当前如何开连接（已确认无 `check_same_thread=False`），再落地上述方案；若未来引擎已自带该参数，则 webapp 这段重开逻辑应变为 no-op 检测（幂等）。

### 4.3 应用装配（`app.py`）

- `FastAPI()` 实例，挂 CORS 中间件：`allow_origins=["http://localhost:5173","http://127.0.0.1:5173"]`，`allow_methods=["*"]`，`allow_headers=["*"]`。
- 所有路由挂在 `/api` 前缀下（各 router 自带前缀或在 `include_router(..., prefix="/api")` 统一加）。
- `include_router`：health、stats、query、graph、documents、entities、index。
- **不在 startup 强行加载 embedder**：单例惰性化，启动永不因模型缺失失败。
- 可选：`@app.on_event("shutdown")` 调 `engine.close()`。

### 4.4 schemas.py（pydantic 响应模型 = 唯一真源）

所有响应都用显式 pydantic 模型（不裸返 dict），字段名 + 类型即前端契约。关键模型（字段见 §5）：

`HealthResp, StatsResp, QueryRequest, QueryContext, SubgraphNode, SubgraphEdge, Subgraph, QueryResp, GraphResp, GraphExpandResp(=Subgraph), NodeMeta..., NodeResp, NeighborItem, DocumentListItem, DocumentDetailResp, DocChunk, EntityItem, IndexRequest, IndexResp`。

`SubgraphNode = {id:str, type:str, meta:dict}`，`SubgraphEdge = {src:str, dst:str, type:str}`，`Subgraph = {nodes:list[SubgraphNode], edges:list[SubgraphEdge]}`——`graph`、`graph/expand`、`query.subgraph` 共用这套形状。

## 5. REST API 契约（全部 `/api`，JSON）

通用约定：

- 成功 2xx；资源不存在 404，且 body `{detail: "..."}`；需要 embedder 但不可用 503 `{detail: "..."}`；请求体校验失败 422（FastAPI 默认）。
- 所有子图/图响应里节点是 `{id,type,meta}`，边是 `{src,dst,type}`。

### 5.1 `GET /api/health`

```json
{ "status": "ok" }
```

无依赖，永远 200。

### 5.2 `GET /api/stats`

```json
{ "documents": 0, "sections": 0, "chunks": 0, "entities": 0,
  "tags": 0, "nodes": 0, "edges": 0, "vectors": 0 }
```

- 数据来源：`engine.stats()`（= `GraphStore.stats()` + 可选 `vectors`）。
- 引擎 dict 里**缺失的键一律默认 0**（`sections/entities/tags/vectors` 可能缺）。`entities`/`tags`/`sections` 若引擎未提供，后端可由 `export_graph()` 的 node `type` 计数补齐（可选增强）；最低要求是缺失即 0，不报错。
- 只依赖 GraphStore，**embedder 缺失也能返回**（`vectors` 此时为 0）。

### 5.3 `POST /api/query`

请求体（`QueryRequest`）：

```json
{ "query": "string", "k": 8, "mode": "dual", "graph_weight": 0.5,
  "per_doc_cap": 2, "hops": 2 }
```

- `mode: "dual" | "vector"`，默认 `"dual"`。
- `per_doc_cap: int | null`，默认 `2`（`null` 表示不限流）。
- `graph_weight: float`，默认 `0.5`；`hops: int`，默认 `2`；`k: int`，默认 `8`。

行为：

- 取引擎的 `vector_store` + `embedder` + `graph_store`；若 embedder/vector_store 不可用 ⇒ **503** `{detail:"..."}`（绝不崩）。
- **始终先跑一次纯向量 ranking** 以计算 `from_graph`：
  - `qvec = embedder.embed([query])[0]`；`vector_rows = vector_store.search(qvec, k=k)`；`vector_ids = {r["chunk_id"] for r in vector_rows}`（top-k 纯向量命中集合）。
- 然后按 mode 构 Retriever：
  - `mode="vector"`：`Retriever(vector_store, embedder, graph_store=None).retrieve(query, k=k, hops=hops)`（`graph_store=None` ⇒ 纯向量，`subgraph` 空）。
  - `mode="dual"`：`Retriever(vector_store, embedder, graph_store=graph_store, graph_weight=<body.graph_weight>, per_doc_cap=<body.per_doc_cap>).retrieve(query, k=k, hops=hops)`。
- 组装响应：对结果 `contexts` 的每条，`from_graph = (chunk_id not in vector_ids)`——即**不在纯向量 top-k 里、由图扩展带进来**的 chunk。`mode="vector"` 时所有 `from_graph` 必为 `false`（同一向量集合）。

响应（`QueryResp`）：

```json
{
  "contexts": [
    { "chunk_id": "…", "text": "…", "score": 0.83,
      "source_path": "…", "heading_path": "…", "from_graph": false }
  ],
  "subgraph": { "nodes": [ {"id","type","meta"} ],
                "edges": [ {"src","dst","type"} ] }
}
```

> 实现要点：复用 Retriever 的算法，不要在后端重写融合；后端只额外做「纯向量 ranking 用于打 `from_graph` 标记」。空 query 时 Retriever 返回空结果（引擎已处理 `if not query.strip()`）。

### 5.4 `GET /api/graph?limit=<int?>`

```json
{ "nodes": [ {"id","type","meta"} ],
  "edges": [ {"src","dst","type"} ],
  "truncated": false, "total_nodes": 1234 }
```

- 全量来自 `graph_store.export_graph()`（id 排序确定性）。`total_nodes` = 全图节点数。
- 无 `limit`，或 `limit >= total_nodes` ⇒ `truncated=false`，返回全部。
- 有 `limit` 且 `limit < total_nodes` ⇒ `truncated=true`，**保留前 `limit` 个节点**（export_graph 已按 id 排序），边只保留**两端都在保留集合内**的。

### 5.5 `GET /api/graph/expand?seeds=a,b,c&hops=2`

- `seeds`：逗号分隔的 node id 列表；`hops` 默认 2。
- 计算：`dist = graph_store.expand(seed_ids, hops=hops)`；返回 `graph_store.subgraph(seed_ids + list(dist))`。
- 响应即 `Subgraph`：`{nodes:[{id,type,meta}], edges:[{src,dst,type}]}`。
- 不在图中的种子被忽略（引擎行为）；空 seeds ⇒ 空子图。

### 5.6 `GET /api/node/{node_id}`

```json
{
  "node": { "id": "…", "type": "entity", "meta": { } },
  "neighbors": [
    { "id":"…", "type":"chunk", "meta":{}, "edge_type":"mentions", "direction":"in" }
  ]
}
```

- `graph_store.get_node(node_id)`，**缺失 ⇒ 404** `{detail:"node not found"}`。
- 邻居从 `to_networkx()` 推导 **1 跳**：遍历该节点的 `out_edges` ⇒ `direction="out"`，`in_edges` ⇒ `direction="in"`；`edge_type` = 边的 type（multigraph 的 key）。邻居节点的 `type/meta` 从图节点属性取。

### 5.7 `GET /api/documents`

```json
[ { "id":"…", "path":"…", "chunk_count": 7 } ]
```

- 列表来自 `graph_store.list_documents()`（返回 `(id, hash)`，按 id 排序），逐个用 `get_document(id).path` 取 `path`，`list_chunks_by_doc(id)` 长度作 `chunk_count`。
- **按 id 升序**输出。

### 5.8 `GET /api/document/{doc_id}`

```json
{
  "document": { "id":"…", "path":"…", "frontmatter": { } },
  "chunks": [ { "id":"…", "section_path":"…", "text":"…" } ],
  "links": [ "other_doc_id", "…" ]
}
```

- `get_document(doc_id)`，**缺失 ⇒ 404**。
- `chunks` 来自 `list_chunks_by_doc(doc_id)`，裁剪为 `{id, section_path, text}`。
- `links` = 该文档（其 document 节点或其下属 section 节点）的 `LINKS_TO` **出边**指向的其他 document id 列表。推导方式：用 `to_networkx()`/`export_graph()`，取 `type==links_to` 且 `src` 属于本文档（src 是该 doc 节点，或 `doc_id==doc_id` 的 section 节点）的边，收集去重后的目标 document id（若目标是 section，归并到其所属 document）。去重并排序。

### 5.9 `GET /api/entities?limit=20`

```json
[ { "id":"…", "name":"…", "type":"concept", "mentions": 12 } ]
```

- 候选 = 所有 `type==entity` 的节点（来自 `export_graph()`）。
- `mentions` = 指向该 entity 的 `MENTIONS` **入边数**（`mentions` 边方向 chunk→entity，故统计 dst==该 entity 的 mentions 边数）。
- `name` = `meta.get("name")` 或回退 `id`；`type` = `meta.get("type","")`（实体子类型，可能空字符串）。
- 排序：**mentions 入度降序，平手按 id 升序**；取前 `limit`（默认 20）。

### 5.10 `POST /api/index`

请求体（`IndexRequest`）：

```json
{ "paths": ["docs/", "notes/a.md"], "full": false }
```

行为：

- **需要 embedder 配置**；不可用 ⇒ 503 `{detail:"..."}`。
- 同步（MVP）：`engine.build(paths, incremental=not full)`，构造 `IndexReport`。
- 写路径串行化（§4.2 的 `threading.Lock`）。
- 出错（路径不存在等）⇒ 4xx/5xx + `{detail:"..."}`。

响应（`IndexResp`，镜像 `IndexReport` 子集）：

```json
{ "indexed": 3, "unchanged": 1, "removed": 0, "reclaimed": 0,
  "entities": 12, "errors": [ ["path", "message"] ] }
```

`errors` 是 `[[path, msg], …]`（`IndexReport.errors` 是 `list[tuple[str,str]]`，序列化成数组的数组）。

## 6. 前端架构（`webapp/frontend/`）

### 6.1 技术栈（固定，勿偏离）

- **React 18 + TypeScript**（strict）+ **Vite 5**。
- **TailwindCSS v3.4**（classic config + postcss）。**不用 Tailwind v4**。
- 数据层：**@tanstack/react-query v5** + 自写 typed fetch client。
- 路由：**react-router-dom v6**（`BrowserRouter`）。
- 图可视化：**react-force-graph-2d**（canvas 力导向）。
- 图标：**lucide-react**。

### 6.2 Vite dev 代理

`vite.config.ts` 的 `server.proxy`：`/api -> http://localhost:8000`。前端代码里所有请求都打相对路径 `/api/...`，开发期由 Vite 转发，免 CORS 摩擦（CORS 仍在后端配好作为直连兜底）。

### 6.3 路由与页面（`react-router-dom` v6，`BrowserRouter`）

| path | 页面组件 | 职责 |
|---|---|---|
| `/` | `SearchPage` | 输入 query + 旋钮（`RetrievalControls`），调 `/api/query`，渲染 `ContextCard` 列表（含 `from_graph` 徽标）+ 结果子图（`GraphCanvas`） |
| `/graph` | `GraphExplorerPage` | 调 `/api/graph?limit=…` 渲染全图；点击节点开 `NodeDetailDrawer`（拉 `/api/node/:id`），支持以选中节点为 seed 调 `/api/graph/expand` 扩展 |
| `/stats` | `StatsPage` | 调 `/api/stats`，卡片网格展示各计数（documents/sections/chunks/entities/tags/nodes/edges/vectors） + 调 `/api/entities` 展示 Top 实体榜 |
| `/doc/:id` | `DocumentPage` | 调 `/api/document/:id`，展示 frontmatter、chunks（按 section_path 分组）、出链（`links` → 链到 `/doc/:targetId`） |

顶部持久 `NavBar`（在 `Layout` 内）链接四个路由，高亮当前路由。

### 6.4 API 层（`src/api/`）

- `types.ts`：**逐字段镜像** `schemas.py`（字段名 + 类型一致），包含 `StatsResp, QueryRequest, QueryContext, Subgraph, SubgraphNode, SubgraphEdge, QueryResp, GraphResp, NodeResp, NeighborItem, DocumentListItem, DocumentDetailResp, DocChunk, EntityItem, IndexRequest, IndexResp` 等。任何后端 schema 改动必须同步这里。
- `client.ts`：每个端点一个 typed 函数，基于一个 `apiFetch<T>(path, init)` 封装（统一 JSON 解析、非 2xx 抛带 `detail` 的错误）。函数清单：
  - `getHealth()`, `getStats()`, `postQuery(body: QueryRequest)`, `getGraph(limit?)`, `expandGraph(seeds: string[], hops?)`, `getNode(id)`, `getDocuments()`, `getDocument(id)`, `getEntities(limit?)`, `postIndex(body: IndexRequest)`。
- `hooks.ts`：用 react-query v5 包装：`useStats()`, `useQueryMutation()`（query 是带参动作，用 `useMutation`），`useGraph(limit?)`, `useExpandGraph()`, `useNode(id)`, `useDocuments()`, `useDocument(id)`, `useEntities(limit?)`, `useIndexMutation()`。`QueryClientProvider` 在 `main.tsx` 或 `App.tsx` 顶层挂一次。

### 6.5 组件（`src/components/`）

- `Layout.tsx`：外壳，含 `NavBar` + `<Outlet/>`（或 children），统一页面 padding/max-width。
- `NavBar.tsx`：四个 `NavLink`（Search/Graph/Stats，+ 不一定在导航暴露的 Doc），lucide 图标，当前路由高亮。
- `GraphCanvas.tsx`：封装 `react-force-graph-2d`。入参：`nodes/edges`（`Subgraph` 形状）、`onNodeClick`。节点颜色按 `colorForType`，边标签按 `labelForEdge`。负责把后端 `{id,type,meta}`/`{src,dst,type}` 适配成 force-graph 的 `{nodes:[{id,...}], links:[{source,target,...}]}`。
- `NodeDetailDrawer.tsx`：侧抽屉，展示某节点的 `node` + `neighbors`（来自 `/api/node/:id`），邻居可点击切换；entity 节点显示 name/type/mentions 之类 meta。
- `ContextCard.tsx`：单条检索结果卡片：`heading_path`、`source_path`（可链到 `/doc/:id`）、`text`、`score`、以及 `from_graph` 为真时的「Graph」徽标（区别于纯向量命中）。
- `RetrievalControls.tsx`：受控表单：`mode` 切换（dual/vector）、`k`、`graph_weight`、`per_doc_cap`（允许置空=null）、`hops`。dual 才显示 `graph_weight/per_doc_cap/hops`。

### 6.6 颜色与边标签（`src/lib/graphColors.ts`）

节点按 `NodeType` 上色：

| type | 颜色 |
|---|---|
| `document` | `#2563eb` |
| `section` | `#7c3aed` |
| `chunk` | `#0891b2` |
| `entity` | `#dc2626` |
| `tag` | `#ca8a04` |

导出 `colorForType(type: string): string`（未知 type 给一个中性回退色）和 `labelForEdge(type: string): string`（把 `contains/links_to/tagged/mentions/relates_to` 映射成人类可读标签，如 `links_to → "links to"`）。

### 6.7 样式

`src/index.css` 引 Tailwind 三段 directives（`@tailwind base/components/utilities`）。`tailwind.config.js`（classic v3 配置，`content` 指向 `index.html` + `src/**/*.{ts,tsx}`）+ `postcss.config.js`（`tailwindcss` + `autoprefixer`）。

### 6.8 构建门禁与测试

- **构建门禁**：`tsc -b && vite build` 必须通过（strict TS，无类型错误）。
- **测试**：vitest + @testing-library/react + jsdom + @testing-library/jest-dom；config 放 `vite.config.ts` 的 `test` 块或独立 `vitest.config.ts`；`src/test/setup.ts` 注册 jest-dom（`import '@testing-library/jest-dom'`），在 vitest `setupFiles` 引用。
- 测试目标（建议覆盖）：`graphColors`（颜色/边标签纯函数）、`ContextCard`（`from_graph` 徽标渲染）、`RetrievalControls`（mode 切换显隐旋钮）、API client 的错误解析。前端测试不打真实后端（mock fetch / msw 可选）。

## 7. 文件布局（全部在 `webapp/` 下，仓库根 = `mdgraph`）

### 7.1 后端 `webapp/backend/`

```
webapp/backend/
  __init__.py
  settings.py            # 环境变量 → store_dir / embedder_path / llm_path / origins
  schemas.py             # pydantic 响应模型（前端 types.ts 唯一真源）
  engine_provider.py     # 惰性单例 + SQLite check_same_thread=False + 写锁 + 优雅降级
  app.py                 # FastAPI + CORS + include_router
  requirements.txt       # fastapi / uvicorn[standard] / pydantic / (引擎依赖经源码 path)
  routers/
    __init__.py
    health.py            # GET /health
    stats.py             # GET /stats
    query.py             # POST /query
    graph.py             # GET /graph, GET /graph/expand, GET /node/{id}
    documents.py         # GET /documents, GET /document/{id}
    entities.py          # GET /entities
    index.py             # POST /index
  tests/
    __init__.py
    conftest.py          # tmp store + Mock providers + TestClient fixture
    test_api.py          # 每端点的离线断言
```

### 7.2 前端 `webapp/frontend/`

```
webapp/frontend/
  package.json
  vite.config.ts          # server.proxy /api→:8000 ；test 块（或独立 vitest.config.ts）
  tsconfig.json
  tsconfig.node.json
  tailwind.config.js
  postcss.config.js
  index.html
  .gitignore
  src/
    main.tsx              # ReactDOM root + BrowserRouter + QueryClientProvider
    App.tsx               # <Routes> 定义四条路由 + Layout
    index.css             # tailwind directives
    vite-env.d.ts
    test/setup.ts         # 注册 jest-dom
    api/
      types.ts            # 镜像 schemas.py
      client.ts           # 每端点 typed 函数
      hooks.ts            # react-query 包装
    lib/
      graphColors.ts      # colorForType / labelForEdge
    components/
      Layout.tsx
      NavBar.tsx
      GraphCanvas.tsx
      NodeDetailDrawer.tsx
      ContextCard.tsx
      RetrievalControls.tsx
    pages/
      SearchPage.tsx
      GraphExplorerPage.tsx
      StatsPage.tsx
      DocumentPage.tsx
```

### 7.3 文档与配置（仓库根级改动）

- `webapp/README.md`：本地运行说明（见 §9）。
- 更新仓库根 `.gitignore`：新增 `node_modules/`、`dist/`、`__pycache__/`、`.pytest_cache/`（若已存在则去重）。
- `pyproject.toml` 新增 `[project.optional-dependencies]` 的 `web` extra：`web = ["fastapi", "uvicorn[standard]"]`（与现有 `anthropic/voyage/local/dev` 并列）。pydantic 引擎已依赖，无需重复。

## 8. 离线测试纪律（IRON RULE）

**铁律：真实模型 / API / 网络永不进入 pytest。**

后端测试（`webapp/backend/tests/`）必须：

1. 在 `tmp_path`（pytest tmp 目录）建一个**极小 store**：用 `MarkdownGraph(tmp_store, embedder=DeterministicEmbeddingProvider(), llm=MockLLMProvider())`，`build()` 一两个内联的小 markdown 文件（fixture 里写字符串到 tmp 文件再索引），**零网络、确定性**。
2. `conftest.py` 提供 fixture：
   - `tmp_store`（含已索引的小图）；
   - 通过依赖注入/环境覆盖让 `engine_provider` 单例指向该 tmp store + Mock embedder（例如设 `MDGRAPH_STORE` env、或暴露 `engine_provider.override(...)` 测试钩子、或在 app 上覆盖依赖）；
   - `client = TestClient(app)`。
3. `test_api.py` 对每个端点断言：
   - `health` 200 `{status:"ok"}`；
   - `stats` 缺失键默认 0、`vectors` 存在（Mock embedder 已就绪）；
   - `query` dual / vector 两模式；断言 `from_graph` 在 vector 模式恒 false，在 dual 模式存在因图扩展进来的项；断言 `score` 字段存在；
   - `graph` 带/不带 `limit`：`truncated` 与边裁剪正确；
   - `graph/expand` seeds 解析与子图返回；
   - `node/{id}` 命中 + 404；neighbors 的 direction/edge_type；
   - `documents` 排序 + `chunk_count`；
   - `document/{id}` 命中 + 404 + `links`；
   - `entities` 按 mentions 降序 + name 回退；
   - `index` 用 Mock embedder 同步索引一个 tmp 文件，断言 `IndexResp` 计数；
   - **503 降级**：构造一个无 embedder 的引擎（或令 embedder 加载失败），断言 `query`/`index` 返回 503，而 `stats`/`graph`/`documents` 仍 200。
4. **运行命令**：`python -m pytest`（**不要**用裸 `pytest`，可能命中错误解释器）。`pyproject.toml` 的 `[tool.pytest.ini_options]` 已设 `pythonpath=["src"]`；测试需能 import `webapp.backend.*`，故从仓库根运行，`webapp/backend/` 与 `webapp` 需有 `__init__.py`（或在 conftest 调整 sys.path）。

> 关键：测试里**绝不** import 真实 provider（`FastEmbedProvider`/`ClaudeExtractor`/`LocalLLMExtractor`），只用 `DeterministicEmbeddingProvider` / `MockLLMProvider`。

## 9. 本地运行（`webapp/README.md` 要写清）

**后端：**

```bash
# 仓库根，建议虚拟环境
pip install -e ".[web,local]"        # web=fastapi/uvicorn；local=fastembed 等真实 embedder
# 先用 CLI 或 /api/index 建索引到 ./.mdgraph
python -m mdgraph index docs/ --store .mdgraph \
  --embedder mdgraph.providers.fastembed_embedder:FastEmbedProvider
# 起 API
uvicorn webapp.backend.app:app --reload --port 8000
```

环境变量：`MDGRAPH_STORE`（默认 `./.mdgraph`）、`MDGRAPH_EMBEDDER`（默认 `...fastembed_embedder:FastEmbedProvider`）、`MDGRAPH_LLM`（可选）。

**前端：**

```bash
cd webapp/frontend
npm install
npm run dev      # http://localhost:5173，/api 代理到 :8000
# 门禁与测试
npm run build    # tsc -b && vite build
npm run test     # vitest
```

**后端测试：** `python -m pytest webapp/backend/tests`（离线，Mock providers）。

## 10. 给实现者的纪律提醒

- **不要运行任何 git 命令**：本子项目的所有 git 操作由编排器在专门阶段统一处理。实现者只创建/编辑文件，并在被允许处运行 `pip` / `npm` / `pytest` / `vitest`。
- 后端是引擎的**薄适配层**：检索/扩展/融合/导出全部委托引擎现有方法，禁止在 webapp 里重写算法。唯一的「额外计算」是 `from_graph` 标注（多跑一次纯向量 ranking）。
- `schemas.py` ↔ `types.ts` 必须**逐字段一致**；任一侧改字段名/类型，另一侧同步。
- SQLite 跨线程方案（§4.2）落地前**先核对** `GraphStore` 当前连接打开方式（已确认无 `check_same_thread=False`），并把选择与理由写进代码注释 + README。
- 严守 YAGNI（§1.2）：不加 auth、不做多用户、不做实时索引流、不写 Docker/部署。

## 11. 与既有切片的衔接

本子项目位于切片 1–9（引擎本体：结构索引 → 向量检索 → 语义抽取 → 图扩展+RRF → 增量/CLI → 真实 provider/demo → 本地 LLM → hub 去偏）之上，是引擎的**首个上层应用**。它**不改引擎源码**（线程适配在 webapp 层做），因此引擎的离线测试与公开 API 语义保持不变；webapp 自带独立的离线测试集与构建门禁。
