# mdgraph 切片 7：真实 provider（fastembed + Claude）+ 复杂中文 demo + 效果验证 — 设计文档

- 日期：2026-06-20
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 后续「真实 provider」增强）
- 前置：切片 1~6 均已合并 main（增量索引 + 孤儿回收 + CLI 已交付）

## 1. 目标与范围

把至今依赖 mock 的检索升级为**真实语义**：实现真实 `EmbeddingProvider`（本地 fastembed，无需 key）与真实 `LLMProvider`（Anthropic Claude，经中转端点），并构造一个**复杂关联的中文知识库 demo**，用 markdown-graph 构建图谱，最后**量化对比纯向量 vs 图+向量双引擎**的检索效果。

provider 经既有 dotted-path / 依赖注入接入，引擎核心零改动——这是切片 6 §2「CLI provider 无关」预留的接缝兑现。

### 不在本切片范围（YAGNI）

- 把真实 provider 设为默认 / 写进 CLI 内置注册表——仍按 dotted-path 显式指定。
- 真实 API 调用 / 模型下载进 CI 套件——离线 135 套件保持确定性，真实端到端只在手动 demo 脚本里跑。
- rerank、查询改写、实体描述向量化——后续增强。
- python-dotenv 依赖——demo 脚本手动解析 `.env`，不引入新运行时依赖。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| Embedding | 本地 fastembed（无 key、可离线复现）；选**无需 query/passage 前缀**的中文/多语模型（统一 `embed()` 接口不区分 query/passage） |
| 模型选型 | 实现 Task 1 用 `TextEmbedding.list_supported_models()` 锁定 fastembed 实际支持的中文/多语模型；首选 `BAAI/bge-small-zh-v1.5`，回退 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`；`dim` 从模型描述动态读取，不硬编码 |
| LLM 抽取 | Anthropic Claude，默认模型 `claude-sonnet-4-6`（可经 `ANTHROPIC_MODEL` 覆盖）；结构化抽取用 **tool use**（强制 JSON），逐 chunk 调用 |
| 凭证 | 优先 `ANTHROPIC_AUTH_TOKEN`（→ SDK `auth_token`，Bearer）+ `ANTHROPIC_BASE_URL`（→ `base_url`，中转端点）；回退 `ANTHROPIC_API_KEY`（→ `api_key`，官方直连）；均从 `.env` 读 |
| 接入方式 | dotted-path `mdgraph.providers.fastembed_embedder:FastEmbedProvider` / `mdgraph.providers.anthropic_extractor:ClaudeExtractor`，零参可构造（配置从 env 读） |
| demo | 中文「AI 工程」知识库，**约 20 篇**互联 markdown；`examples/run_demo.py` 量化对比 |
| 测试 | 离线契约测试（mock SDK）进 CI 套件；真实端到端 = 手动 demo，不进 CI |
| 依赖 | pyproject 新增 extra `local = ["fastembed>=0.3"]`；`anthropic` extra 已有 |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/providers/fastembed_embedder.py`（新） | `FastEmbedProvider(EmbeddingProvider)`：fastembed 批量 embedding，`name`/`dim` 动态、`embed()` 返回 `list[list[float]]` | fastembed |
| `src/mdgraph/providers/anthropic_extractor.py`（新） | `ClaudeExtractor(LLMProvider)`：Claude tool-use 抽取实体/关系，env 凭证注入，重试 + 解析失败降级 | anthropic |
| `examples/ai_kb/`（新，~20 篇 md） | 复杂关联的中文 AI 工程知识库 demo 语料 | — |
| `examples/run_demo.py`（新） | 加载 `.env` → 构建图谱 → 纯向量 vs 双引擎对比 + 子图 + 实体合并统计 | engine |
| `pyproject.toml`（改） | 加 `local` extra | — |

## 4. FastEmbedProvider 细节

```python
class FastEmbedProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)
        self._raw_name = model_name
        desc = next(
            m for m in TextEmbedding.list_supported_models() if m["model"] == model_name
        )
        self._dim = int(desc["dim"])

    @property
    def name(self) -> str:
        return self._raw_name.replace("/", "_")  # VectorStore 表名/版本化安全

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(list(texts))]
```

- 模型名含 `/`，`name` 清洗为 `_`（VectorStore 表名按 `model_name+dim` 版本化，见切片 1/3）。
- `dim` 从 fastembed 模型描述读，换模型不出错。
- `embed` 把 fastembed 的 generator[np.ndarray] 转成 `list[list[float]]`（VectorStore/LanceDB 需原生 float）。
- 首次构造触发模型下载（联网一次，缓存后离线）；下载失败抛原生异常，run_demo 捕获给出指引。
- **实现 Task 1 第一步**：运行 `python -c "from fastembed import TextEmbedding; print([(m['model'], m['dim']) for m in TextEmbedding.list_supported_models()])"`，确认 `bge-small-zh-v1.5` 是否在列；若不在，改用回退多语模型并更新默认 `model_name`/`dim`。无需前缀是硬约束（统一 `embed()` 接口）。

## 5. ClaudeExtractor 细节

```python
class ClaudeExtractor(LLMProvider):
    def __init__(self, model: str | None = None, max_retries: int = 2) -> None:
        import os
        from anthropic import Anthropic
        token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        kwargs = {"max_retries": max_retries}
        if base_url:
            kwargs["base_url"] = base_url
        if token:
            kwargs["auth_token"] = token
        elif api_key:
            kwargs["api_key"] = api_key
        else:
            raise RuntimeError("缺少凭证：请在 .env 设置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY")
        self._client = Anthropic(**kwargs)
        self._model = model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6"

    def extract(self, text: str) -> ExtractionResult: ...
```

- **结构化抽取用 tool use**：定义一个 `record_extraction` tool，`input_schema` 为
  `{entities: [{name, type, description}], relations: [{source, target, type}]}`，
  `tool_choice` 强制调用它。从 `tool_use` block 的 `input` 直接拿到结构化 dict。
- prompt（中文）：要求从给定文本抽取关键实体（概念/技术/产品/组织）及其类型、一句话描述，以及实体间的有向关系（如「依赖」「属于」「用于」）。
- 解析 → `ExtractedEntity(name,type,description)` / `ExtractedRelation(source,target,type)`，组装 `ExtractionResult`。
- **降级**：任何异常（无 tool_use block、schema 不符、API 错误重试耗尽）→ 返回**空** `ExtractionResult`。配合 `extract.extract_graph` 已有的 `failed_chunks` 路径，单 chunk 失败不阻断整体（indexer 把它记入 `report.warnings`）。
- 重试交给 SDK 的 `max_retries`（限流/瞬时网络）。

## 6. demo 数据集设计（`examples/ai_kb/`，约 20 篇中文 md）

主题「AI 工程」知识库，刻意构造**高互联**以凸显图谱价值：

- **文档**（每篇 frontmatter `tags` + 多级 heading + 正文）：`index`、`rag`、`embedding`、`向量数据库(vector-db)`、`chunking`、`reranking`、`llm`、`claude`、`agent`、`tool-use`、`prompt-engineering`、`fine-tuning`、`evaluation`、`knowledge-graph`、`semantic-search`、`ann`、`lancedb`、`planning`、`multimodal`、`guardrails` 等 ~20 篇。
- **关联**：
  - `[[wiki 链接]]` 与相对路径链接交织成网（如 `rag` ↔ `embedding`/`向量数据库`/`reranking`/`chunking`，`agent` ↔ `llm`/`tool-use`/`planning`/`claude`）。
  - 跨文档反复出现的**实体**（RAG、Embedding、向量检索、Claude、Agent、LLM、知识图谱…）→ Claude 抽取后形成跨文档 `MENTIONS` + 实体间 `RELATES_TO`。
  - frontmatter tags 复用（`检索`、`生成`、`基础设施`、`Agent`…）→ `TAGGED` 边。
  - 故意安排「桥接」：某概念只在 A 文出现却经共享实体 / wiki 链接与 B 文相连——用于检验**双引擎能拉回纯向量漏掉的相关 chunk**。
- 内容真实可读（非占位），每篇 150–400 字，便于 chunk 切分出多块。

## 7. `examples/run_demo.py` 效果验证

加载 `.env`（手动解析 `KEY=VALUE` 写入 `os.environ`，无 python-dotenv），用 dotted-path 不相关、直接构造 provider：

```python
from mdgraph.engine import MarkdownGraph
from mdgraph.providers.fastembed_embedder import FastEmbedProvider
from mdgraph.providers.anthropic_extractor import ClaudeExtractor
```

输出四块**可量化对比**：

1. **构建报告 + stats**：`IndexReport`（indexed/entities/...）+ `mg.stats()`（documents/nodes/edges/chunks/vectors）。
2. **纯向量 vs 双引擎并排**：对 3–4 个代表性中文 query（如「如何提升 RAG 的召回质量」「Agent 怎么调用工具」），分别用 `Retriever(vs, emb, graph_store=None)`（纯向量）与 `Retriever(vs, emb, graph_store=gs)`（双引擎）检索，并排打印 top-k 的 `source_path::heading_path`，**标注双引擎经图扩展新增、纯向量未召回的 chunk**。
3. **子图可解释性**：打印某 query 命中结果的诱导子图摘要——哪些 `entity` / `links_to` 把不同文档的结果连接起来。
4. **跨文档实体合并**：列出被最多文档 `MENTIONS` 的 top 实体（验证同名实体跨文档归并为一个节点）。

脚本对缺失凭证 / 模型下载失败给出清晰中文指引并退出，不抛裸 traceback。

## 8. 测试策略

- **离线契约测试（进 135 套件，不需 key/网络/模型下载）**：
  - `tests/test_fastembed_provider.py`：monkeypatch `fastembed.TextEmbedding`（假 model + 假 `list_supported_models`），验证 `embed()` 返回 `list[list[float]]`、批量长度一致、`name` 清洗 `/`→`_`、`dim` 从描述读取。
  - `tests/test_anthropic_extractor.py`：monkeypatch `anthropic.Anthropic`（假 client，`messages.create` 返回构造的 tool_use response），验证：tool-use 结果正确解析成 `ExtractionResult`；解析失败 / 抛异常 → 返回**空** `ExtractionResult`（降级）；`ANTHROPIC_AUTH_TOKEN`+`ANTHROPIC_BASE_URL` 与回退 `ANTHROPIC_API_KEY` 的凭证注入分支；缺凭证 → `RuntimeError`。
- **demo 语料 sanity 测试（离线）**：`tests/test_examples_corpus.py`：用结构索引（无 provider）build `examples/ai_kb/`，断言文档数 ≈ 预期、`report.errors == []`、未解析链接比例低（互联确实成立）、有 `LINKS_TO`/`TAGGED` 边。
- **真实端到端 = `examples/run_demo.py`**（手动跑，需 `.env` 凭证 + 首次模型下载），**不进 CI**。
- 离线确定性不破：真实模型/真实 API 绝不进 pytest 套件。

## 9. 技术栈 / 依赖

- 新增 `pyproject.toml` extra：`local = ["fastembed>=0.3"]`；`anthropic` extra 已有（`anthropic>=0.30`，需支持 `auth_token`/`base_url`，0.30+ 满足）。
- run_demo.py、契约测试不引入新运行时依赖（手动解析 `.env`，mock SDK）。
- `.env`（凭证）与 `.fastembed_cache/` 已加入 `.gitignore`。

## 10. 错误处理 / 边界

- 缺 `ANTHROPIC_AUTH_TOKEN` 且缺 `ANTHROPIC_API_KEY` → `ClaudeExtractor.__init__` 抛 `RuntimeError`（清晰中文）。
- fastembed 模型下载失败 / 首次离线 → 原生异常，run_demo 捕获并指引「需联网下载一次模型」。
- 单 chunk Claude 抽取失败 → 降级空抽取 + `report.warnings`（不阻断 build）。
- **顺带验证已知边界**（切片 6 §4）：真实 Claude 产富实体 meta 后，run_demo 可选演示「只改一篇裸提及某实体的文档 → 该实体富描述被增量覆盖、`--full` 恢复」，把此前 mock 下不可见的边界显式呈现。

## 11. 建议的任务切分（写计划时细化）

1. `FastEmbedProvider` + 契约测试 + pyproject `local` extra（第一步先锁定 fastembed 实际支持的中文/多语模型与 dim）。
2. `ClaudeExtractor`（tool-use 抽取 + 凭证注入 + 降级）+ 契约测试（mock anthropic SDK）。
3. demo 语料 `examples/ai_kb/`（~20 篇中文互联 md）+ 语料 sanity 测试。
4. `examples/run_demo.py`（.env 加载 + 四块效果对比）。
5. 收尾：README/用法说明 + 整体回归。

## 12. 给后续的接缝

- 真实 provider 就绪后，可把「dotted-path 默认 provider 注册表」做进 CLI（让 `--embedder fastembed` 这种短名生效），属 CLI 增强。
- 实体描述向量化 + query→实体锚定检索（切片 5 缓做项）此时有真实富 meta 可用。
- 大语料下 `to_networkx()` 每查询重建的性能优化（切片 6 carry-forward）在 demo 规模未必显现，但 demo 是验证它的现成基准。
