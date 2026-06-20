# mdgraph 切片 7：真实 provider + 复杂中文 demo + 效果验证 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现真实 `FastEmbedProvider`（本地 fastembed）与 `ClaudeExtractor`（Anthropic Claude，中转端点），构造复杂中文 AI 工程知识库 demo，量化对比纯向量 vs 图+向量双引擎检索效果。

**Architecture:** 两个真实 provider 实现既有 `EmbeddingProvider`/`LLMProvider` 抽象，经依赖注入接入（引擎核心零改动）；二者都支持**注入底层对象**（`model=` / `client=`），使契约测试完全离线（不下载模型、不调 API）；真实端到端只在 `examples/run_demo.py` 手动跑。

**Tech Stack:** fastembed（local extra）、anthropic 0.62（已装，支持 auth_token/base_url/tool-use）、既有 mdgraph 引擎。

## Global Constraints

- 运行测试一律用 `python -m pytest`（裸 `pytest` 在本机可能解析到缺 lancedb 的解释器）。
- **离线确定性铁律**：真实模型下载、真实 API 调用**绝不**进 pytest 套件。契约测试用注入的 fake（`FastEmbedProvider(model=fake)` / `ClaudeExtractor(client=fake)`）或 monkeypatch，不碰网络/磁盘下载。
- 新增运行时依赖仅 `fastembed`（pyproject `[project.optional-dependencies]` 的 `local` extra）；`anthropic` extra 已存在。契约测试不依赖 fastembed 可导入（靠注入）。
- 凭证：优先 `ANTHROPIC_AUTH_TOKEN`（→ SDK `auth_token`，Bearer）+ `ANTHROPIC_BASE_URL`（→ `base_url`）；回退 `ANTHROPIC_API_KEY`（→ `api_key`）；默认模型 `claude-sonnet-4-6`，`ANTHROPIC_MODEL` 可覆盖。**绝不**把凭证写进代码或提交；`.env`/`.fastembed_cache/` 已 gitignore。
- fastembed 默认模型 `BAAI/bge-small-zh-v1.5`（fastembed 原生支持、无需 query/passage 前缀）；`dim` 用**探针嵌入**测量（`len(embed(["x"])[0])`），不赌 `list_supported_models` 字段名。
- 既有接口（`src/mdgraph/providers/base.py`）：`EmbeddingProvider` 需 `name:str`/`dim:int`/`embed(texts)->list[list[float]]`；`LLMProvider` 需 `extract(text)->ExtractionResult`。`ExtractedEntity(name, type="concept", description="")`、`ExtractedRelation(source, target, type="related_to")`、`ExtractionResult(entities=[], relations=[])`。
- 提交信息正文用中文；commit 结尾必须是：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 面向用户输出/思考用中文，代码/标识符/路径原文。

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `src/mdgraph/providers/fastembed_embedder.py` | `FastEmbedProvider`：fastembed 适配器 | 新建 |
| `src/mdgraph/providers/anthropic_extractor.py` | `ClaudeExtractor`：Claude tool-use 抽取 | 新建 |
| `examples/ai_kb/*.md` | ~20 篇中文互联知识库 demo 语料 | 新建 |
| `examples/run_demo.py` | .env 加载 + 构建 + 效果对比脚本 | 新建 |
| `pyproject.toml` | 加 `local` extra | 改 |
| `tests/test_fastembed_provider.py` / `test_anthropic_extractor.py` / `test_examples_corpus.py` / `test_run_demo.py` | 离线契约/语料/逻辑测试 | 新建 |

---

### Task 1: FastEmbedProvider（fastembed 适配器，可注入）

**Files:**
- Create: `src/mdgraph/providers/fastembed_embedder.py`
- Modify: `pyproject.toml`（`[project.optional-dependencies]` 加 `local`）
- Test: `tests/test_fastembed_provider.py`

**Interfaces:**
- Consumes: `EmbeddingProvider`（`src/mdgraph/providers/base.py`）。
- Produces: `FastEmbedProvider(model_name="BAAI/bge-small-zh-v1.5", model=None)`，属性 `name`（`/`→`_`）、`dim`（探针测）、方法 `embed(texts)->list[list[float]]`。`model` 注入用于测试，None 时 lazy 构造 `fastembed.TextEmbedding`。

- [ ] **Step 1: 写失败测试** — `tests/test_fastembed_provider.py`

```python
from mdgraph.providers.fastembed_embedder import FastEmbedProvider


class _FakeModel:
    """模拟 fastembed.TextEmbedding：embed 返回 generator，每条 4 维。"""
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        return (([0.1, 0.2, 0.3, 0.4]) for _ in texts)


def test_dim_probed_from_model():
    p = FastEmbedProvider(model_name="BAAI/bge-small-zh-v1.5", model=_FakeModel())
    assert p.dim == 4  # 探针 embed(["x"]) 测出


def test_name_sanitized_for_table_versioning():
    p = FastEmbedProvider(model_name="BAAI/bge-small-zh-v1.5", model=_FakeModel())
    assert p.name == "BAAI_bge-small-zh-v1.5"  # 斜杠清洗，VectorStore 表名安全


def test_embed_returns_list_of_float_lists():
    p = FastEmbedProvider(model_name="m", model=_FakeModel())
    vecs = p.embed(["a", "b"])
    assert vecs == [[0.1, 0.2, 0.3, 0.4], [0.1, 0.2, 0.3, 0.4]]
    assert all(isinstance(x, float) for x in vecs[0])  # generator→list、float 转换


def test_embed_empty():
    p = FastEmbedProvider(model_name="m", model=_FakeModel())
    assert p.embed([]) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_fastembed_provider.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mdgraph.providers.fastembed_embedder'`）

- [ ] **Step 3: 实现 `src/mdgraph/providers/fastembed_embedder.py`**

```python
"""真实 embedding provider：本地 fastembed（无需 API key）。"""

from __future__ import annotations

from mdgraph.providers.base import EmbeddingProvider


class FastEmbedProvider(EmbeddingProvider):
    """用 fastembed 本地模型批量生成向量。

    选用无需 query/passage 前缀的模型（默认中文 bge-small-zh-v1.5），
    因 EmbeddingProvider.embed() 不区分 query/passage。dim 由探针嵌入测得，
    不依赖 fastembed 内部元数据结构。model 参数仅供测试注入。
    """

    def __init__(
        self, model_name: str = "BAAI/bge-small-zh-v1.5", model=None
    ) -> None:
        if model is None:
            from fastembed import TextEmbedding

            model = TextEmbedding(model_name=model_name)
        self._model = model
        self._raw_name = model_name
        self._dim = len(self.embed(["x"])[0])

    @property
    def name(self) -> str:
        return self._raw_name.replace("/", "_")

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._model.embed(list(texts))]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_fastembed_provider.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 加 `local` extra** — `pyproject.toml` 的 `[project.optional-dependencies]` 加一行（与现有 anthropic/voyage/dev 并列）：

```toml
local = ["fastembed>=0.3"]
```

- [ ] **Step 6: 安装并真实自检模型可用性**（一次性，不进测试套件）

Run: `pip install fastembed && python -c "from fastembed import TextEmbedding; ok=[m for m in TextEmbedding.list_supported_models() if (m['model'] if isinstance(m,dict) else m.model)=='BAAI/bge-small-zh-v1.5']; print('bge-small-zh-v1.5 supported:', bool(ok))"`
Expected: 打印 `bge-small-zh-v1.5 supported: True`。若为 False，改默认 `model_name` 为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 并在报告说明（dim 仍由探针测，provider 代码无需改其它处）。

- [ ] **Step 7: Commit**

```bash
git add src/mdgraph/providers/fastembed_embedder.py tests/test_fastembed_provider.py pyproject.toml
git commit -m "$(cat <<'EOF'
feat: FastEmbedProvider (local fastembed embedding, no API key)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: ClaudeExtractor（Claude tool-use 抽取，可注入）

**Files:**
- Create: `src/mdgraph/providers/anthropic_extractor.py`
- Test: `tests/test_anthropic_extractor.py`

**Interfaces:**
- Consumes: `LLMProvider`/`ExtractedEntity`/`ExtractedRelation`/`ExtractionResult`（`base.py`）。
- Produces: `ClaudeExtractor(model=None, max_retries=2, client=None)`，方法 `extract(text)->ExtractionResult`。`client` 注入用于测试；None 时按凭证 env 构造 `anthropic.Anthropic`。

- [ ] **Step 1: 写失败测试** — `tests/test_anthropic_extractor.py`

```python
import pytest

from mdgraph.providers.anthropic_extractor import ClaudeExtractor


class _Block:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "record_extraction"
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]


class _FakeMessages:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._exc:
            raise self._exc
        return self._resp


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self.messages = _FakeMessages(resp, exc)


def test_parses_tool_use_into_extraction_result():
    payload = {
        "entities": [
            {"name": "RAG", "type": "技术", "description": "检索增强生成"},
            {"name": "Embedding", "type": "技术", "description": "向量表示"},
        ],
        "relations": [{"source": "RAG", "target": "Embedding", "type": "依赖"}],
    }
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp(payload)))
    res = ext.extract("RAG 依赖 Embedding。")
    assert [e.name for e in res.entities] == ["RAG", "Embedding"]
    assert res.entities[0].type == "技术"
    assert res.entities[0].description == "检索增强生成"
    assert (res.relations[0].source, res.relations[0].target, res.relations[0].type) == (
        "RAG", "Embedding", "依赖",
    )


def test_api_error_degrades_to_empty():
    ext = ClaudeExtractor(client=_FakeClient(exc=RuntimeError("boom")))
    res = ext.extract("anything")
    assert res.entities == [] and res.relations == []


def test_malformed_payload_degrades_to_empty():
    # tool_use.input 缺 entities/relations 键 → 降级空，不抛
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp({"foo": "bar"})))
    res = ext.extract("anything")
    assert res.entities == [] and res.relations == []


def test_default_model_and_override(monkeypatch):
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp({"entities": [], "relations": []})))
    assert ext._model == "claude-sonnet-4-6"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    ext2 = ClaudeExtractor(client=_FakeClient(resp=_Resp({"entities": [], "relations": []})))
    assert ext2._model == "claude-haiku-4-5"


def test_auth_token_branch(monkeypatch):
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("anthropic.Anthropic", _Fake)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.example.com")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ClaudeExtractor()
    assert captured.get("auth_token") == "tok"
    assert captured.get("base_url") == "https://relay.example.com"
    assert "api_key" not in captured


def test_api_key_fallback_branch(monkeypatch):
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("anthropic.Anthropic", _Fake)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xxx")
    ClaudeExtractor()
    assert captured.get("api_key") == "sk-xxx"
    assert "auth_token" not in captured


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ClaudeExtractor()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_anthropic_extractor.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mdgraph.providers.anthropic_extractor'`）

- [ ] **Step 3: 实现 `src/mdgraph/providers/anthropic_extractor.py`**

```python
"""真实 LLM provider：Anthropic Claude，tool-use 强制结构化实体/关系抽取。"""

from __future__ import annotations

import os

from mdgraph.providers.base import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)

_TOOL = {
    "name": "record_extraction",
    "description": "记录从文本中抽取的实体与实体间关系。",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "实体名称"},
                        "type": {"type": "string", "description": "实体类型，如 概念/技术/产品/组织"},
                        "description": {"type": "string", "description": "一句话描述"},
                    },
                    "required": ["name"],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "type": {"type": "string", "description": "关系类型，如 依赖/属于/用于"},
                    },
                    "required": ["source", "target"],
                },
            },
        },
        "required": ["entities", "relations"],
    },
}

_PROMPT = (
    "从下面的文本中抽取关键实体（概念、技术、产品、组织等）及其类型和一句话描述，"
    "并抽取实体之间的有向关系。只针对文本明确提及的内容，不要臆造。"
    "通过 record_extraction 工具返回结果。\n\n文本：\n"
)


class ClaudeExtractor(LLMProvider):
    def __init__(self, model: str | None = None, max_retries: int = 2, client=None) -> None:
        if client is None:
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
                raise RuntimeError(
                    "缺少凭证：请在 .env 设置 ANTHROPIC_AUTH_TOKEN（+ANTHROPIC_BASE_URL）或 ANTHROPIC_API_KEY"
                )
            client = Anthropic(**kwargs)
        self._client = client
        self._model = model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6"

    def extract(self, text: str) -> ExtractionResult:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": "record_extraction"},
                messages=[{"role": "user", "content": _PROMPT + text}],
            )
            payload = next(
                b.input for b in resp.content if getattr(b, "type", None) == "tool_use"
            )
            entities = [
                ExtractedEntity(
                    name=e["name"],
                    type=e.get("type") or "concept",
                    description=e.get("description") or "",
                )
                for e in payload["entities"]
            ]
            relations = [
                ExtractedRelation(
                    source=r["source"],
                    target=r["target"],
                    type=r.get("type") or "related_to",
                )
                for r in payload["relations"]
            ]
            return ExtractionResult(entities=entities, relations=relations)
        except Exception:  # noqa: BLE001 — 任何失败降级为空抽取，交由 indexer 记 warning
            return ExtractionResult()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_anthropic_extractor.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add src/mdgraph/providers/anthropic_extractor.py tests/test_anthropic_extractor.py
git commit -m "$(cat <<'EOF'
feat: ClaudeExtractor (Anthropic tool-use entity/relation extraction)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 复杂中文 demo 语料 + 语料 sanity 测试

**Files:**
- Create: `examples/ai_kb/*.md`（~20 篇）
- Test: `tests/test_examples_corpus.py`

**Interfaces:**
- Consumes: `MarkdownGraph`（结构索引，无 provider）、`mdgraph.ids.doc_id`。
- Produces: `examples/ai_kb/` 语料目录，供 Task 4 的 run_demo 使用。

**语料规格（必须满足，sanity 测试会强制）：**
- 目录 `examples/ai_kb/`，约 20 篇 `.md`，文件名（无空格、小写连字符）：`index, rag, embedding, vector-db, chunking, reranking, llm, claude, agent, tool-use, prompt-engineering, fine-tuning, evaluation, knowledge-graph, semantic-search, ann, lancedb, planning, multimodal, guardrails`。
- 每篇：YAML frontmatter 含 `tags`（从 `检索/生成/基础设施/Agent/评估/模型/向量` 中选 1–3 个，跨文档复用）；至少 2 级 heading（`#`/`##`）；正文 150–400 字中文，内容真实可读。
- 互联：每篇正文用 `[[目标文件名]]` 维基链接指向 ≥2 个其它文档（用不带扩展名的文件 stem，如 `[[embedding]]`）；整体形成连通网络。跨文档反复出现核心实体（RAG、Embedding、向量检索、Claude、Agent、LLM、知识图谱、重排序…）。
- `index.md` 作为门户，链接到至少 8 个主题文档。

示范（直接照此风格写全部 20 篇）——`examples/ai_kb/rag.md`：

```markdown
---
tags: [检索, 生成]
---

# 检索增强生成（RAG）

RAG 把外部知识检索与大模型生成结合：先用 [[embedding]] 把文档与问题映射到向量空间，
经 [[vector-db]] 做相似度召回，再把召回内容拼进提示交给 [[llm]] 生成答案。

## 为什么需要 RAG

大模型的参数知识有截止时间且易幻觉。RAG 让回答**有据可依**，把权威内容放进上下文，
显著降低幻觉、支持私有知识。

## 提升召回质量

朴素向量召回会漏掉表述不同但相关的内容。常见手段：更好的 [[chunking]] 切分、
[[reranking]] 重排序、以及用 [[knowledge-graph]] 做图扩展把语义相邻的片段一起带出。
```

示范——`examples/ai_kb/embedding.md`：

```markdown
---
tags: [检索, 向量]
---

# 向量嵌入（Embedding）

Embedding 把文本映射成稠密向量，使语义相近的文本在向量空间中距离更近，
是 [[rag]] 与 [[semantic-search]] 的基础。

## 模型选择

中文场景常用 bge、multilingual-e5 等模型。向量维度与模型绑定，需与 [[vector-db]] 的表结构一致。

## 与检索的关系

Embedding 的质量直接决定 [[rag]] 的召回上限；下游再叠加 [[reranking]] 进一步排序。
```

示范——`examples/ai_kb/knowledge-graph.md`（呼应本项目，制造跨文档桥接）：

```markdown
---
tags: [检索, 基础设施]
---

# 知识图谱（Knowledge Graph）

知识图谱用节点与边表达实体及其关系。在 [[rag]] 中，图结构能把 [[embedding]] 向量召回
漏掉、但经实体或链接相邻的片段一并带出，提升召回的连通性与可解释性。

## 图 + 向量双引擎

向量负责语义相似，图负责结构关联。先向量召回种子，再沿实体（MENTIONS/RELATES_TO）
与文档链接扩展，最后做排名融合——这正是 [[semantic-search]] 之外的增量价值。
```

- [ ] **Step 1: 写失败测试** — `tests/test_examples_corpus.py`

```python
from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.models import EdgeType

CORPUS = Path(__file__).resolve().parent.parent / "examples" / "ai_kb"


def test_corpus_exists_and_sized():
    files = list(CORPUS.glob("*.md"))
    assert len(files) >= 18, f"语料至少 18 篇，实际 {len(files)}"


def test_corpus_builds_clean_and_interlinked(tmp_path):
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # 无 provider，纯结构
    report = mg.build([CORPUS])
    assert report.errors == [], f"解析/索引不应有错误：{report.errors}"
    assert report.indexed >= 18
    g = mg.graph_store.to_networkx()
    links = [1 for _, _, k in g.edges(keys=True) if k == EdgeType.LINKS_TO.value]
    tagged = [1 for _, _, k in g.edges(keys=True) if k == EdgeType.TAGGED.value]
    assert len(links) >= 20, f"维基链接 LINKS_TO 边过少：{len(links)}"
    assert len(tagged) >= 10, f"TAGGED 边过少：{len(tagged)}"
    # 互联：未解析链接占比应较低（绝大多数 [[..]] 指向真实存在的文档）
    assert report.unresolved_links <= len(links) * 0.2
    mg.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_examples_corpus.py -v`
Expected: FAIL（`test_corpus_exists_and_sized` 因 `examples/ai_kb/` 不存在 / 文档数不足）

- [ ] **Step 3: 写全部 ~20 篇语料** —— 按上面「语料规格」与 3 篇示范的风格，创建 `examples/ai_kb/` 下全部文件。每篇真实可读、frontmatter tags 复用、≥2 个 `[[wiki]]` 链接、核心实体跨文档复现。`index.md` 链接到 ≥8 个主题。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_examples_corpus.py -v`
Expected: PASS（2 passed）。若 `unresolved_links` 偏高，检查 `[[..]]` 目标 stem 是否与文件名一致（如 `[[vector-db]]` 对应 `vector-db.md`）。

- [ ] **Step 5: Commit**

```bash
git add examples/ai_kb tests/test_examples_corpus.py
git commit -m "$(cat <<'EOF'
feat: add interlinked Chinese AI-engineering demo corpus (examples/ai_kb)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: run_demo.py（.env 加载 + 效果对比，逻辑可测）

**Files:**
- Create: `examples/run_demo.py`
- Test: `tests/test_run_demo.py`

**Interfaces:**
- Consumes: `MarkdownGraph`、`Retriever`（`mdgraph.retrieve`）、`GraphStore`、`mdgraph.providers.mock`（测试用）、Task 1/2 的真实 provider（仅 `main()` 用）。
- Produces（可被测试导入的纯函数）：
  - `load_env(path)->dict`：解析 `.env`（`KEY=VALUE`，忽略空行/`#`），写入 `os.environ` 并返回 dict。
  - `compare_retrieval(vector_store, embedder, graph_store, queries, k=5)->list[dict]`：每个 query 返回 `{"query","vector_only":[ids],"dual":[ids],"graph_added":[ids]}`（`graph_added` = 双引擎有而纯向量没有的 chunk_id）。
  - `top_mentioned_entities(graph_store, top=10)->list[tuple[str,int]]`：按入边 MENTIONS 数排序的 (entity_name, 文档数) — 实际用 MENTIONS 入边计数。
  - `main()`：加载 .env、构造真实 provider、build、打印四块对比（不被测试调用）。

- [ ] **Step 1: 写失败测试** — `tests/test_run_demo.py`

```python
import importlib.util
from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.mock import DeterministicEmbeddingProvider, MockLLMProvider

DEMO = Path(__file__).resolve().parent.parent / "examples" / "run_demo.py"
spec = importlib.util.spec_from_file_location("run_demo", DEMO)
run_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_demo)


def test_load_env_parses_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO=bar\n\nBAZ = qux \n", encoding="utf-8")
    monkeypatch.delenv("FOO", raising=False)
    got = run_demo.load_env(env)
    assert got["FOO"] == "bar"
    assert got["BAZ"] == "qux"
    import os
    assert os.environ["FOO"] == "bar"


def _write(tmp_path, name, body):
    f = tmp_path / "src" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def test_compare_retrieval_flags_graph_added(tmp_path):
    # a 链接 b；查询命中 a，双引擎应经 LINKS_TO 把 b 也带出
    _write(tmp_path, "a.md", "# A\n\nalpha topic see [[b]]\n")
    _write(tmp_path, "b.md", "# B\n\nbeta detail about alpha\n")
    store = tmp_path / ".mdgraph"
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(store, embedder=emb, llm=MockLLMProvider())
    mg.build([tmp_path / "src"])
    rows = run_demo.compare_retrieval(
        mg.vector_store, emb, mg.graph_store, ["alpha"], k=5
    )
    assert rows[0]["query"] == "alpha"
    assert set(rows[0]["dual"]) >= set(rows[0]["vector_only"])  # 双引擎是超集或并集
    mg.close()


def test_top_mentioned_entities(tmp_path):
    _write(tmp_path, "a.md", "# A\n\nAlpha here\n")
    _write(tmp_path, "b.md", "# B\n\nAlpha again\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph", llm=MockLLMProvider())
    mg.build([tmp_path / "src"])
    top = run_demo.top_mentioned_entities(mg.graph_store, top=10)
    assert any(name == "Alpha" and cnt >= 2 for name, cnt in top)
    mg.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_run_demo.py -v`
Expected: FAIL（`examples/run_demo.py` 不存在 → import 失败）

- [ ] **Step 3: 实现 `examples/run_demo.py`**

```python
"""真实 provider 端到端 demo：构建 examples/ai_kb 图谱并量化对比检索效果。

运行（需先在项目根 .env 填好凭证，并 `pip install fastembed`）：
    PYTHONPATH=src python examples/run_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.models import EdgeType
from mdgraph.retrieve import Retriever

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "examples" / "ai_kb"
STORE = ROOT / "examples" / ".demo_store"


def load_env(path: Path) -> dict:
    """解析 .env（KEY=VALUE，忽略空行与 # 注释），写入 os.environ 并返回 dict。"""
    env: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key:
            env[key] = val
            os.environ.setdefault(key, val)
    return env


def compare_retrieval(vector_store, embedder, graph_store, queries, k: int = 5) -> list[dict]:
    out = []
    for q in queries:
        vonly = Retriever(vector_store, embedder).retrieve(q, k=k)
        dual = Retriever(vector_store, embedder, graph_store=graph_store).retrieve(q, k=k)
        v_ids = [c.chunk_id for c in vonly.contexts]
        d_ids = [c.chunk_id for c in dual.contexts]
        out.append(
            {
                "query": q,
                "vector_only": v_ids,
                "dual": d_ids,
                "graph_added": [c for c in d_ids if c not in v_ids],
            }
        )
    return out


def top_mentioned_entities(graph_store, top: int = 10) -> list[tuple[str, int]]:
    g = graph_store.to_networkx()
    counts = []
    for n, data in g.nodes(data=True):
        if data.get("type") == "entity":
            mentions = sum(
                1 for _, _, k in g.in_edges(n, keys=True) if k == EdgeType.MENTIONS.value
            )
            name = data.get("meta", {}).get("name", n)
            counts.append((name, mentions))
    counts.sort(key=lambda x: (-x[1], x[0]))
    return counts[:top]


def main() -> int:
    load_env(ROOT / ".env")
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("缺少凭证：请在项目根 .env 填写 ANTHROPIC_AUTH_TOKEN(+ANTHROPIC_BASE_URL) 或 ANTHROPIC_API_KEY", file=sys.stderr)
        return 1
    try:
        from mdgraph.providers.fastembed_embedder import FastEmbedProvider
        from mdgraph.providers.anthropic_extractor import ClaudeExtractor
    except ImportError as exc:
        print(f"缺少依赖：{exc}（请 `pip install fastembed`）", file=sys.stderr)
        return 1

    print("== 构建图谱（首次会下载 embedding 模型 + 调用 Claude 抽取，请稍候）==")
    try:
        embedder = FastEmbedProvider()
    except Exception as exc:  # noqa: BLE001
        print(f"embedding 模型加载失败（需联网下载一次）：{exc}", file=sys.stderr)
        return 1
    mg = MarkdownGraph(STORE, embedder=embedder, llm=ClaudeExtractor())
    try:
        report = mg.build([CORPUS], incremental=False)
        print(
            f"indexed={report.indexed} entities={report.entities} "
            f"errors={len(report.errors)} warnings={len(report.warnings)}"
        )
        print("stats:", mg.stats())

        queries = [
            "如何提升 RAG 的召回质量",
            "Agent 怎么调用工具",
            "向量数据库和近似最近邻",
            "用知识图谱做图加向量双引擎检索",
        ]
        print("\n== 纯向量 vs 图+向量双引擎 ==")
        for row in compare_retrieval(mg.vector_store, embedder, mg.graph_store, queries):
            print(f"\n[查询] {row['query']}")
            print(f"  纯向量 top: {row['vector_only']}")
            print(f"  双引擎 top: {row['dual']}")
            print(f"  ← 图扩展新增（纯向量漏掉）: {row['graph_added']}")

        print("\n== 子图（首个查询命中结果的诱解释结构）==")
        first = Retriever(mg.vector_store, embedder, graph_store=mg.graph_store).retrieve(queries[0], k=5)
        sg = first.subgraph
        print(f"  子图节点 {len(sg['nodes'])} 个、边 {len(sg['edges'])} 条")

        print("\n== 跨文档实体合并（被最多 chunk MENTIONS 的实体）==")
        for name, cnt in top_mentioned_entities(mg.graph_store, top=10):
            print(f"  {name}: {cnt}")
    finally:
        mg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_run_demo.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add examples/run_demo.py tests/test_run_demo.py
git commit -m "$(cat <<'EOF'
feat: run_demo.py — real-provider end-to-end demo with effect comparison

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 用法说明 + 整体回归

**Files:**
- Create: `examples/README.md`
- Test: 全套回归（无新测试）

**Interfaces:** 无新接口。

- [ ] **Step 1: 写 `examples/README.md`**（中文，说明如何跑 demo）

````markdown
# markdown-graph 真实 provider Demo

用本地 fastembed（无需 key）做向量、Anthropic Claude（经中转端点）做实体抽取，
在 `examples/ai_kb/` 的中文 AI 工程知识库上构建图谱，并量化对比纯向量 vs 图+向量双引擎检索。

## 准备

1. 安装本地 embedding 依赖：
   ```bash
   pip install fastembed
   ```
2. 在项目根 `.env` 填写凭证（已被 .gitignore 忽略，不会提交）：
   ```
   ANTHROPIC_AUTH_TOKEN=<你的中转 token>
   ANTHROPIC_BASE_URL=<你的中转 base url>
   # ANTHROPIC_MODEL 留空即用 claude-sonnet-4-6
   ```
   若用官方直连：改填 `ANTHROPIC_API_KEY`，上面两项留空。

## 运行

```bash
PYTHONPATH=src python examples/run_demo.py
```

首次运行会联网下载 embedding 模型（约一两百 MB，之后离线），并逐 chunk 调用 Claude 抽取实体。
输出包含：构建报告与 stats、4 个查询的纯向量 vs 双引擎对比（标注图扩展新增的命中）、
命中结果的子图规模、被最多 chunk 提及的跨文档实体。
````

- [ ] **Step 2: 全套回归**

Run: `python -m pytest -q`
Expected: PASS（135 既有 + Task 1~4 新增契约/语料/逻辑测试，全绿；真实模型/API 不参与）。

- [ ] **Step 3: Commit**

```bash
git add examples/README.md
git commit -m "$(cat <<'EOF'
docs: add examples/README for real-provider demo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 任务依赖与顺序

1. **Task 1**（FastEmbedProvider）— 独立。
2. **Task 2**（ClaudeExtractor）— 独立。
3. **Task 3**（demo 语料）— 独立（纯结构索引，不依赖 provider）。
4. **Task 4**（run_demo）— 依赖 Task 3 语料；逻辑测试用 mock provider，main() 用 Task 1/2 真实 provider。
5. **Task 5**（README + 回归）— 依赖全部。

按 1→2→3→4→5 顺序执行。

## Self-Review

**1. Spec 覆盖：**
- §3 FastEmbedProvider → Task 1 ✓；ClaudeExtractor → Task 2 ✓；demo 语料 → Task 3 ✓；run_demo → Task 4 ✓；pyproject local extra → Task 1 Step 5 ✓。
- §4 探针测 dim、name 清洗、generator→list → Task 1 ✓；模型可用性自检 → Task 1 Step 6 ✓。
- §5 tool-use 抽取、凭证三分支（auth_token/api_key/缺失）、默认模型+覆盖、降级空 → Task 2 测试全覆盖 ✓。
- §6 语料规格（~20 篇、tags、wiki 链接、核心实体）→ Task 3 规格 + sanity 测试 ✓。
- §7 四块效果对比（stats、纯向量 vs 双引擎、子图、实体合并）→ Task 4 `main()` + 可测函数 ✓。
- §8 离线契约测试（mock SDK/注入）进套件、真实端到端 = run_demo 不进 CI → 各 Task 测试用注入/mock ✓。
- §10 缺凭证 RuntimeError、模型下载失败指引、单 chunk 降级 → Task 2 测试 + Task 4 main 的错误分支 ✓。

**2. Placeholder 扫描：** 无 TBD/TODO；provider/脚本/测试均含完整代码；Task 3 语料给规格 + 3 篇完整示范 + 强制 sanity 测试（数据非代码，规格 + 验证齐全）。✓

**3. 类型一致性：**
- `FastEmbedProvider(model_name, model=None)`、`name`/`dim`/`embed` Task 1 定义、Task 4 main 使用 ✓。
- `ClaudeExtractor(model=None, max_retries=2, client=None)`、`extract` Task 2 定义、Task 4 main 使用 ✓。
- `load_env`/`compare_retrieval`/`top_mentioned_entities` Task 4 定义并被同任务测试消费，签名一致 ✓。
- `ExtractedEntity(name,type,description)`/`ExtractedRelation(source,target,type)`/`ExtractionResult` 用法与 base.py 一致 ✓。
- `Retriever(vector_store, embedder, graph_store=None)`、`EdgeType.MENTIONS/LINKS_TO/TAGGED.value` 与既有代码一致 ✓。
