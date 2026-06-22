# mdgraph embedder 短名注册表 + OpenAI/Ollama 兼容 embedder — 设计文档

- 日期：2026-06-22
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 后续「真实 provider」增强）
- 关联：`docs/superpowers/specs/2026-06-20-mdgraph-slice8-local-llm-extractor-design.md`（§10 已预留「CLI provider 短名注册表」接缝），`docs/superpowers/specs/2026-06-21-mdgraph-upload-archive-design.md`（webapp 后端）
- 前置：切片 1~9 + webapp 已合并 main（已交付 `FastEmbedProvider`、`LocalLLMExtractor`、CLI、webapp 后端 `engine_provider`）

## 1. 目标与范围

让 CLI 与 web 服务**通过配置（而非改代码）切换 embedding 模型**。当前两个加载器都只接受 dotted-path 且无参构造，要换 fastembed 的模型名、或改用 OpenAI/Ollama 端点的 embedding 模型，都得写新 provider 类。本设计补两个相关增强：

- **特性 A — embedder spec + 短名注册表**（新 `src/mdgraph/providers/registry.py`）：定义一套可参数化的 spec 语法（短名 + 可选参数），并提供 `resolve_embedder(spec)` 统一解析；CLI 与 webapp 后端都改走它。语法对既有 dotted-path 完全**向后兼容**。
- **特性 B — OpenAI/Ollama 兼容 embedder**（新 `src/mdgraph/providers/openai_embedder.py`）：`OpenAIEmbeddingProvider`，镜像 `LocalLLMExtractor` 的「openai SDK + 本地优先默认 + env 覆盖 + client 注入」模式，默认对接本地 Ollama，配三个 env 即可指向云端 OpenAI。注册为短名 `openai`。

成果：

```bash
mdgraph index docs/ --embedder fastembed:BAAI/bge-m3
mdgraph index docs/ --embedder openai:nomic-embed-text
```

```bash
# webapp 后端
export MDGRAPH_EMBEDDER=openai:text-embedding-3-small
export MDGRAPH_EMBED_BASE_URL=https://api.openai.com/v1
export MDGRAPH_EMBED_API_KEY=sk-...
```

### 不在本设计范围（YAGNI）

- **LLM provider 短名注册表**——CLI `--llm` 与 webapp `llm_path` 仍走既有 dotted-path 无参构造（`_load` / `_load_dotted`），不动。注册表只覆盖 embedder。
- **Voyage（或其它非 OpenAI 兼容）embedder**——本设计只补一个 OpenAI 兼容 provider；Voyage 等留待后续。
- **任何选模型的 UI**——这是 backend/engine 的配置项，不碰 `webapp/frontend`，不加选模型的前端控件。
- **真实模型/真实端点进 pytest**——一律注入 fake / monkeypatch；真实 fastembed 下载、真实 OpenAI/Ollama 调用只手动跑（见 §8 铁律）。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| spec 语法 | 按**第一个 `:`** 切成 `(key, arg)`；`key` 命中注册短名 → 工厂 + 可选 `arg`；否则整串当 dotted-path 无参构造 |
| 向后兼容 | 默认 `mdgraph.providers.fastembed_embedder:FastEmbedProvider` 含 `:` 但不是注册短名，落到 dotted-path 分支，行为与今天**完全一致** |
| `/` 与 `:` | 模型名（如 `BAAI/bge-m3`）含 `/` 但不含 `:`，按第一个 `:` 切分天然安全 |
| 短名集合 | 本设计注册两个：`fastembed`、`openai`。注册表是 `dict[str, factory]`，可扩展 |
| spec 只带模型 | `openai` 的 `base_url`/`api_key`/`batch` 不进 spec，全走 provider 的 env（避免把 key 写进命令行/历史/日志） |
| OpenAI embedder 默认 | **本地优先**：`base_url=http://localhost:11434/v1`、`api_key=ollama`、`model=nomic-embed-text`，开箱即用对接 Ollama；三个 env 覆盖即指向云端 OpenAI |
| dim 探测 | 同 `FastEmbedProvider`：`__init__` 里 `len(self.embed(["x"])[0])` 探一次，不读 SDK 元数据 |
| name | 清洗后的模型 id（`replace("/","_").replace(":","_")`），令向量表名按模型版本化 |
| 注入 | `OpenAIEmbeddingProvider(client=...)` 注入 fake；注册表工厂 monkeypatch，离线可测 |
| 失败语义 | 解析失败 / 路径不可导入 / 短名工厂出错 → `resolve_embedder` 抛 `ValueError`（带 spec 原文）。webapp `_build_embedder` 仍捕获、降级 None → 后续 503 |
| **re-index 警示** | **换 embedder ⇒ 必须重建 store**（详见 §6，README + 本 spec 醒目标注） |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/providers/registry.py`（新） | `resolve_embedder(spec)`、`_parse_spec(spec)`、`EMBEDDER_REGISTRY` 字典 | base, fastembed, openai_embedder, importlib |
| `src/mdgraph/providers/openai_embedder.py`（新） | `OpenAIEmbeddingProvider(EmbeddingProvider)` | openai |
| `src/mdgraph/cli.py`（改） | `--embedder` 改走 `resolve_embedder`；`--llm` 不变 | registry |
| `webapp/backend/engine_provider.py`（改） | `_build_embedder(settings)` 改走 `resolve_embedder`；其余不变 | registry |
| `webapp/README.md`（改） | 文档化 `MDGRAPH_EMBEDDER` 短名语法 + `MDGRAPH_EMBED_*` env + **re-index 警示** | — |
| `pyproject.toml`（已就绪） | `openai` 已在 `[local]` extra（切片 8 已加 `openai>=1.0`）；本设计无新依赖 | — |

`EmbeddingProvider` 抽象（`base.py`：`name:str` / `dim:int` / `embed(texts)->list[list[float]]`）**不改**。引擎、`VectorStore`、indexer 零改动。

## 4. 特性 A — embedder spec + 短名注册表（`registry.py`）

### 4.1 spec 语法

`resolve_embedder(spec: str) -> EmbeddingProvider`：

1. **切分**：按第一个 `:` 把 spec 切成 `(key, arg)`；`arg` 可为 `""` 或缺省（无 `:`）。提供独立接缝 `_parse_spec(spec) -> (key, arg)`，便于单测且不构造任何 provider。
2. **短名分支**：`key` 命中 `EMBEDDER_REGISTRY` → 调对应工厂，把可选 `arg` 传进去：
   - `"fastembed"`：`arg` 是 fastembed 模型名，缺省默认 `BAAI/bge-small-zh-v1.5` → `FastEmbedProvider(model_name=arg or "BAAI/bge-small-zh-v1.5")`。
   - `"openai"`：`arg` 是 embedding 模型名，缺省走 provider 默认 → `OpenAIEmbeddingProvider(model=arg or None)`；`base_url`/`api_key`/`batch_size` **不来自 spec**，由 provider 的 env / 构造默认决定。
3. **dotted-path 分支（向后兼容）**：`key` 不是注册短名 → 把**整串** spec 当 dotted import path 处理，支持 `module:attr` 与 `module.attr` 两种写法，**无参构造**。既有默认 `mdgraph.providers.fastembed_embedder:FastEmbedProvider` 由此原样工作。
4. **错误**：dotted-path 不可导入 / attr 不存在 / 短名工厂构造抛错 → 抛 `ValueError`，消息**带 spec 原文**，便于定位配置错误。

> 注：`BAAI/bge-m3` 之类含 `/` 但不含 `:`，按第一个 `:` 切分后 `key="BAAI/bge-m3"`、`arg` 缺省——它不是注册短名，会落到 dotted-path 分支并因不可导入而 `ValueError`。换言之，**裸模型名必须带短名前缀**（`fastembed:BAAI/bge-m3`）。这与「短名携带参数」的语法一致，README 须明确这点。

### 4.2 可扩展 + 可测的接缝

- `EMBEDDER_REGISTRY: dict[str, Callable[[str | None], EmbeddingProvider]]`——名→工厂的字典，**模块级公开**，方便后续注册（如未来的 voyage，本设计不做）。
- 工厂是普通可调用对象（`arg: str | None`），测试可 monkeypatch 字典里的工厂为返回 mock 的桩，从而验证「短名 + arg → 工厂收到正确 arg」而**不构造真实模型**。
- `_parse_spec` 单独可测：裸 dotted-path、短名无参、短名带参、含 `/` 的模型名、空串等都只验证 `(key, arg)`，不触发任何构造。

### 4.3 dotted-path 加载的统一

现有两个加载器语义有差：

- CLI `_load`（`cli.py`）：只认 `pkg.mod:attr`（无 `:` 直接报错），`getattr` 后**无参 `obj()`**，失败抛 `typer.BadParameter`。用于 `--embedder` 与 `--llm`。
- webapp `_load_dotted`（`engine_provider.py`）：认 `module:attr` 或 `module.attr`，**返回类**（构造在 `_build_embedder` 里 `cls()`）。

`resolve_embedder` 内部的 dotted-path 分支统一采用 webapp 那条更宽松的规则（`module:attr` 或 `module.attr` 皆可），内部完成构造并返回**实例**。CLI 与 webapp 改为都调 `resolve_embedder`（见 §5），embedder 的解析口径自此统一。`--llm` 仍留在 CLI 的 `_load`、webapp 的 `_load_dotted`+`_build_llm`，不动（LLM 注册表是 YAGNI）。

## 5. 集成点

### 5.1 CLI（`cli.py`）

- `index` / `query` / `stats` 的 `--embedder` 改为 `resolve_embedder(spec)`（替换 `_load(embedder)`）。`resolve_embedder` 抛 `ValueError` 时，CLI 包成 `typer.BadParameter`（保持现有错误呈现）。
- 帮助文案从 `pkg.mod:attr` 更新为说明短名语法，例：`--embedder fastembed:BAAI/bge-m3` / `--embedder openai:nomic-embed-text` / 或 dotted-path。
- `--llm` **不变**：仍走 `_load(dotted)` 无参构造。
- 现有 CLI 行为/测试保持绿：默认 dotted-path 仍可用；`query` 仍强制要求 `--embedder`。

### 5.2 webapp 后端（`engine_provider.py`）

- `_build_embedder(settings)` 改为 `return resolve_embedder(settings.embedder_path)`，仍包在 `try/except` 内：任何异常（含 `resolve_embedder` 的 `ValueError`）→ 记 `_embedder_error`、返回 `None`，后续 embedder 相关操作经 `require_embedder` 抛 `EngineUnavailable` → HTTP 503（与今天一致）。
- `settings.embedder_path` 来自 env `MDGRAPH_EMBEDDER`，默认仍是 `mdgraph.providers.fastembed_embedder:FastEmbedProvider`（`settings.py` 的 `DEFAULT_EMBEDDER` 不改）→ 经 dotted-path 分支原样解析，**向后兼容**。
- 现在 `embedder_path` 可填短名 spec（`fastembed:<model>` / `openai:<model>`）。`settings.py` 无需结构改动（已是一根字符串透传）。
- `_load_dotted` / `_build_llm` 不动。

### 5.3 前端

无任何前端改动。不碰 `webapp/frontend`，不加选模型 UI（YAGNI）。

## 6. ⚠️ RE-INDEX 警示（务必醒目）

> **换 embedding 模型 ⇒ 必须重建 store（重新 index / 重新上传）。查询用的 embedder 必须与建库时的 embedder 一致。**

机制（`store/vector_store.py`）：`VectorStore(dir, model_name, dim)` 的表名是 `vectors_<清洗后的 model_name>_<dim>`（`_table_name` 把非字母数字压成 `_`）。`MarkdownGraph` 用 `model_name=embedder.name`、`dim=embedder.dim` 建表。因此：

- 换模型（不同 `name` 或不同 `dim`）会**指向另一张表**，旧向量根本不会被命中——查询要么落空表、要么基于不兼容的向量空间，结果无意义。
- 即便 `name` 相同但底层向量空间变了（如同名模型不同版本/不同端点），距离也不可比。
- `name` 设计为「清洗后的模型 id」正是为了让表按模型版本化、彼此隔离——这是保护，不是 bug。

所以切换 `--embedder` / `MDGRAPH_EMBEDDER` 后必须：

- **CLI**：`mdgraph index ... --full --embedder <新 spec>` 全量重建；之后 `query` 用**同一** spec。
- **webapp**：改 `MDGRAPH_EMBEDDER` 后重新上传/重建 store（触发 build），且建库与查询同一配置。

此警示**同时**写进 `webapp/README.md`（醒目位置）与本 spec。

## 7. OpenAI/Ollama 兼容 embedder（`openai_embedder.py`）

镜像 `LocalLLMExtractor` 的注入/env 模式（见 `local_llm_extractor.py` 与其测试 `tests/test_local_llm_extractor.py`）。

```python
class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model=None, base_url=None, api_key=None, batch_size=128, client=None):
        if client is None:
            from openai import OpenAI   # 仅当未注入 client 时才 import（离线测试不触发）
            base_url = base_url or os.environ.get("MDGRAPH_EMBED_BASE_URL") or "http://localhost:11434/v1"
            api_key = api_key or os.environ.get("MDGRAPH_EMBED_API_KEY") or "ollama"
            client = OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self._model = model or os.environ.get("MDGRAPH_EMBED_MODEL") or "nomic-embed-text"
        self._batch = batch_size
        self._dim = len(self.embed(["x"])[0])   # 探针一次，同 FastEmbedProvider

    @property
    def name(self) -> str:
        return self._model.replace("/", "_").replace(":", "_")

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts):
        texts = list(texts)
        if not texts:
            return []
        out = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            out.extend([float(x) for x in d.embedding] for d in resp.data)
        return out
```

要点：

- **lazy import**：`from openai import OpenAI` 只在 `client is None` 时执行——注入 fake 的离线测试根本不 import openai，也不联网。
- **env 覆盖**：`MDGRAPH_EMBED_MODEL` / `MDGRAPH_EMBED_BASE_URL` / `MDGRAPH_EMBED_API_KEY`（与 LLM 的 `MDGRAPH_LLM_*` 三件套对称，但前缀是 `MDGRAPH_EMBED_`，互不干扰）。
- **本地优先默认**：不配任何东西即对接本地 Ollama（`nomic-embed-text`）。指向云端 OpenAI 时设三件套：`MDGRAPH_EMBED_BASE_URL=https://api.openai.com/v1` + 真实 `MDGRAPH_EMBED_API_KEY` + 如 `MDGRAPH_EMBED_MODEL=text-embedding-3-small`。
- **dim**：构造时探一次，不依赖 SDK 元数据（与 `FastEmbedProvider` 一致）。
- **name**：清洗模型 id，令向量表按模型版本化（见 §6）。
- **embed 批处理**：按 `batch_size` 切块，每块 `client.embeddings.create(model=, input=batch)`，**按顺序**收集各块的 `[d.embedding for d in resp.data]`，全部 `float` 化；空输入 → `[]`。注意 OpenAI embeddings 响应 `data` 与输入同序，跨块仍按块顺序拼接，保证返回与输入等长且对齐。
- **client 注入**：fake 需提供 `.embeddings.create(model=, input=)`，返回的对象 `.data` 是一列「带 `.embedding` 属性」的项（见 §8 测试桩）。
- **失败语义**：embedder 本身不吞异常（与 `FastEmbedProvider` 一致：embed 失败就抛）。降级发生在更上层——webapp `_build_embedder` 的 try/except、CLI 的 `BadParameter` 包装、indexer 的 `failed_chunks`/warning。

在 `EMBEDDER_REGISTRY` 注册：`"openai": lambda arg: OpenAIEmbeddingProvider(model=arg or None)`。

## 8. 测试策略（离线确定性）

引擎套件 `python -m pytest -q`（`pyproject` 配 `pythonpath=["src"]`）；webapp 后端 `python -m pytest webapp/backend/tests -v`（需 `fastapi`/`uvicorn[standard]`/`httpx`/`python-multipart`/`pytest`）。若全量跑命中 `ModuleNotFoundError: anthropic/openai`，`python -m pip install anthropic openai`（仅 import，不联网）。

### 8.1 `registry`（`tests/test_registry.py`，新）

- `_parse_spec`：裸 dotted-path、`fastembed`（无参）、`fastembed:BAAI/bge-m3`、`openai`、`openai:nomic-embed-text`、含 `/` 的串、空串 → 仅断言 `(key, arg)`，**不构造**。
- `resolve_embedder` 短名分支：monkeypatch `EMBEDDER_REGISTRY` 里 `fastembed`/`openai` 工厂为返回 mock（如 `DeterministicEmbeddingProvider`）的桩，断言工厂收到正确 `arg`（缺省 → `None` 或默认），返回值是该 mock。
- `resolve_embedder` dotted-path 分支：用一个**纯 Python、不下载**的目标（如 `mdgraph.providers.mock:DeterministicEmbeddingProvider`）验证无参构造成功；用 `module:attr` 与 `module.attr` 两种写法各验一次。
- **向后兼容**：默认 `mdgraph.providers.fastembed_embedder:FastEmbedProvider` 必须仍走 dotted-path 分支——但**不能真构造**（会下载 fastembed）。验证方式：monkeypatch `FastEmbedProvider.__init__`（或在该路径上拦截）使其不下载，断言 `resolve_embedder(默认 spec)` 命中 dotted-path 分支并 `getattr` 到正确的类/无参构造路径。
- 错误：不可导入路径、不存在 attr、短名工厂抛错 → `ValueError`，消息含 spec 原文。

### 8.2 `OpenAIEmbeddingProvider`（`tests/test_openai_embedder.py`，新）

镜像 `tests/test_local_llm_extractor.py` 的 fake/monkeypatch 写法：

```python
class _Item:
    def __init__(self, emb): self.embedding = emb
class _Resp:
    def __init__(self, data): self.data = data
class _FakeEmbeddings:
    def __init__(self, dim=4): self.dim, self.calls = dim, []
    def create(self, model, input):
        self.calls.append({"model": model, "input": list(input)})
        return _Resp([_Item([0.1] * self.dim) for _ in input])
class _FakeClient:
    def __init__(self, dim=4): self.embeddings = _FakeEmbeddings(dim)
```

- `dim` 由探针 `embed(["x"])` 测出（注入 fake，4 维）。
- `name` 清洗：`nomic-embed-text` → `nomic-embed-text`；`BAAI/bge-m3` → `BAAI_bge-m3`；`text-embedding-3-small` 不变；含 `:` 的 → `_` 化。
- `embed` 返回 `list[list[float]]`，全是 `float`；与输入等长。
- **批处理 + 顺序**：`batch_size=2` 喂 5 条 → fake 记录到 3 次 `create`（2/2/1），返回顺序与输入一致（fake 给每条注入可区分的向量以断言顺序）。
- 空输入 → `[]`，且**不调用** `create`。
- **env 注入**（monkeypatch `openai.OpenAI` 捕获 kwargs，同 LLM 测试）：默认 `base_url=http://localhost:11434/v1`、`api_key=ollama`、`model=nomic-embed-text`；设 `MDGRAPH_EMBED_BASE_URL`/`MDGRAPH_EMBED_API_KEY`/`MDGRAPH_EMBED_MODEL` → 被覆盖。注意此分支会 `from openai import OpenAI`，故需 monkeypatch `openai.OpenAI`（不真连）。

### 8.3 集成点

- **CLI**：现有 `--embedder` 测试改/补——用 dotted-path 指向 `mock:DeterministicEmbeddingProvider`（无参构造）验证仍绿；补 `fastembed:`/`openai:` 短名经 monkeypatch 工厂解析到 mock（不下载、不联网）。`--llm` 测试不变。
- **webapp**：`_build_embedder` 测试——默认 spec 经 monkeypatch 解析到 mock（验证向后兼容）；短名 spec 同理；`resolve_embedder` 抛 `ValueError` 时 `_build_embedder` 返回 `None` 并设 `_embedder_error`，且 embedder 相关端点 503（沿用现有测试设施 `set_engine`/`reset_engine`）。
- **铁律（离线确定性）**：真实模型/API/网络**绝不**进 pytest。新测试不得构造真实 `fastembed`（会下载），不得发真实 OpenAI/Ollama 请求——一律注入 fake / monkeypatch 工厂 / dotted-path 指向 mock。真实端到端（Ollama serve + `nomic-embed-text`、或云端 OpenAI key）只手动跑。

## 9. 文档（`webapp/README.md`）

- 新增「配置 embedding 模型」段：
  - `MDGRAPH_EMBEDDER=fastembed:<model>`（本地 fastembed，默认 `BAAI/bge-small-zh-v1.5`）。
  - `MDGRAPH_EMBEDDER=openai:<model>` + `MDGRAPH_EMBED_BASE_URL` / `MDGRAPH_EMBED_API_KEY`（云 vs 本地：留空三件套 → 本地 Ollama `nomic-embed-text`；设三件套 → 云端 OpenAI）。
  - 仍可填 dotted-path（向后兼容）；裸模型名须带短名前缀。
- **醒目标注 RE-INDEX 警示**（§6 同款）：换 embedder 必须重建 store；查询 embedder 必须与建库 embedder 一致。
- 本 spec §6 已含同一警示的简述。

## 10. 建议的任务切分（写计划时细化）

1. `OpenAIEmbeddingProvider` + 契约测试（注入 fake：dim 探测、name 清洗、批处理顺序、空输入、env 注入降级）。
2. `registry.py`（`_parse_spec` + `EMBEDDER_REGISTRY` + `resolve_embedder`）+ 测试（解析、短名 monkeypatch 工厂、dotted-path 向后兼容、错误 `ValueError`）。注册 `fastembed`/`openai`。
3. CLI `--embedder` 改走 `resolve_embedder` + 帮助文案 + 测试（保持现有绿、补短名）。`--llm` 不动。
4. webapp `_build_embedder` 改走 `resolve_embedder` + 测试（默认向后兼容、短名、降级 503）。
5. `webapp/README.md`：embedding 模型配置段 + **RE-INDEX 警示**。

## 11. 给后续的接缝

- `EMBEDDER_REGISTRY` 是公开字典，后续加 voyage / 其它 provider 只需 `EMBEDDER_REGISTRY["voyage"] = ...`（本设计不做）。
- 若日后要给 `--llm` / `MDGRAPH_LLM` 也上短名注册表，可复用同一 `_parse_spec` 接缝建一个对称的 `resolve_llm`（本设计 YAGNI，未做）。
- `OpenAIEmbeddingProvider` 的 base_url/model 可配，天然支持任意 OpenAI 兼容 embedding 端点（LM Studio、vLLM、本地 llama.cpp server、云端 OpenAI），不止 Ollama。
