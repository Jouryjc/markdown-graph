# mdgraph 切片 8：本地 LLM 实体抽取 provider + 真实本地双引擎 demo 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完全本地、零外部 key 的 `LocalLLMExtractor`（openai SDK → 本地 OpenAI 兼容端点，JSON prompt + 鲁棒解析），接入 demo 的 provider 选择，组成「fastembed 向量 + 本地 LLM 实体」的离线双引擎。

**Architecture:** `LocalLLMExtractor` 实现既有 `LLMProvider` 抽象，走 openai SDK 指向 `http://localhost:11434/v1`（Ollama，可配）；输出经 `_extract_json` 鲁棒提取（剥围栏/取第一个平衡 `{...}`），失败降级空——与 `ClaudeExtractor` 行为对齐。`client=None` 注入设计让契约测试完全离线、不连真实 Ollama。`run_demo.py` 按 env `MDGRAPH_LLM` 选 local/claude provider。

**Tech Stack:** openai 1.99（已装）、既有 mdgraph 引擎与 fastembed provider。

## Global Constraints

- 运行测试一律用 `python -m pytest`（裸 `pytest` 在本机可能解析到缺 lancedb 的解释器）。
- **离线确定性铁律**：真实 Ollama 调用 / 模型推理**绝不**进 pytest 套件。契约测试用注入的 fake（`LocalLLMExtractor(client=fake)`）或 monkeypatch `openai.OpenAI`，不连本地端点、不发请求。
- 新增运行时依赖仅把 `openai>=1.0` 加入 pyproject `local` extra（openai 已装 1.99.6）。契约测试不依赖 openai 真连。
- 默认配置（均可经 env 覆盖）：`base_url="http://localhost:11434/v1"`（`MDGRAPH_LLM_BASE_URL`）、`api_key="ollama"`（`MDGRAPH_LLM_API_KEY`，本地不校验、openai SDK 要求非空）、`model="qwen2.5:3b"`（`MDGRAPH_LLM_MODEL`）。
- demo provider 选择：env `MDGRAPH_LLM`，默认 `"local"` → `LocalLLMExtractor`；`"claude"` → `ClaudeExtractor`。
- 既有接口（`src/mdgraph/providers/base.py`）：`LLMProvider.extract(text) -> ExtractionResult`；`ExtractedEntity(name, type="concept", description="")`、`ExtractedRelation(source, target, type="related_to")`、`ExtractionResult(entities=[], relations=[])`。
- 失败降级语义与 `ClaudeExtractor` 对齐：任何异常 / 解析失败 → 空 `ExtractionResult`，不抛（交 indexer 记 warning）。
- 提交信息正文用中文；commit 结尾必须是：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 面向用户输出/思考用中文，代码/标识符/路径原文。

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `src/mdgraph/providers/local_llm_extractor.py` | `LocalLLMExtractor` + `_extract_json`/`_first_balanced_object` 鲁棒解析 | 新建 |
| `examples/run_demo.py` | `_make_llm()` provider 选择 + main 重构 | 改 |
| `examples/README.md` | 补本地 LLM 用法 | 改 |
| `pyproject.toml` | `local` extra 加 `openai>=1.0` | 改 |
| `tests/test_local_llm_extractor.py` / `tests/test_run_demo.py` | 离线契约/选择逻辑测试 | 新建 / 追加 |

---

### Task 1: LocalLLMExtractor + 鲁棒 JSON 解析（可注入）

**Files:**
- Create: `src/mdgraph/providers/local_llm_extractor.py`
- Modify: `pyproject.toml`（`local` extra 加 `openai>=1.0`）
- Test: `tests/test_local_llm_extractor.py`

**Interfaces:**
- Consumes: `LLMProvider`/`ExtractedEntity`/`ExtractedRelation`/`ExtractionResult`（`base.py`）。
- Produces:
  - `LocalLLMExtractor(model=None, base_url=None, api_key=None, client=None)`，方法 `extract(text)->ExtractionResult`。`client` 注入用于测试；None 时按 env/默认构造 `openai.OpenAI`。
  - 模块级 `_extract_json(text)->dict|None`、`_first_balanced_object(s)->str|None`。

- [ ] **Step 1: 写失败测试** — `tests/test_local_llm_extractor.py`

```python
import pytest

from mdgraph.providers.local_llm_extractor import (
    LocalLLMExtractor,
    _extract_json,
    _first_balanced_object,
)


# --- fake openai client（chat.completions.create -> resp.choices[0].message.content）---
class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, content=None, exc=None):
        self._content, self._exc = content, exc
        self.kwargs = None

    def create(self, **kw):
        self.kwargs = kw
        if self._exc:
            raise self._exc
        return _Resp(self._content)


class _FakeClient:
    def __init__(self, content=None, exc=None):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content, exc)})()


# --- _extract_json / _first_balanced_object ---
def test_extract_json_bare():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_surrounded_by_text():
    assert _extract_json('好的，结果如下：{"a": 1} 希望有帮助') == {"a": 1}


def test_extract_json_nested():
    assert _extract_json('{"x": {"y": 2}}') == {"x": {"y": 2}}


def test_extract_json_no_json():
    assert _extract_json("这里没有 JSON") is None


def test_extract_json_empty():
    assert _extract_json("") is None


def test_first_balanced_object():
    assert _first_balanced_object('xx {"a": {"b": 1}} yy') == '{"a": {"b": 1}}'
    assert _first_balanced_object("no brace") is None


# --- extract() ---
def test_extract_parses_entities_and_relations():
    content = (
        '{"entities":[{"name":"RAG","type":"技术","description":"检索增强生成"},'
        '{"name":"Embedding","type":"技术","description":"向量表示"}],'
        '"relations":[{"source":"RAG","target":"Embedding","type":"依赖"}]}'
    )
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("RAG 依赖 Embedding。")
    assert [e.name for e in res.entities] == ["RAG", "Embedding"]
    assert res.entities[0].type == "技术"
    assert res.entities[0].description == "检索增强生成"
    assert (res.relations[0].source, res.relations[0].target, res.relations[0].type) == (
        "RAG", "Embedding", "依赖",
    )


def test_extract_handles_fenced_and_missing_optional_fields():
    content = '```json\n{"entities":[{"name":"A"}],"relations":[]}\n```'
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert res.entities[0].name == "A"
    assert res.entities[0].type == "concept"      # 缺 type → 默认
    assert res.entities[0].description == ""        # 缺 description → 默认


def test_extract_malformed_degrades_to_empty():
    res = LocalLLMExtractor(client=_FakeClient(content="抱歉，我无法完成")).extract("x")
    assert res.entities == [] and res.relations == []


def test_extract_api_error_degrades_to_empty():
    res = LocalLLMExtractor(client=_FakeClient(exc=RuntimeError("connection refused"))).extract("x")
    assert res.entities == [] and res.relations == []


# --- 端点/模型 env 注入（monkeypatch openai.OpenAI 捕获 kwargs）---
def test_default_endpoint_and_model(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    for k in ("MDGRAPH_LLM_BASE_URL", "MDGRAPH_LLM_MODEL", "MDGRAPH_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ext = LocalLLMExtractor()
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"
    assert ext._model == "qwen2.5:3b"


def test_env_overrides(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setenv("MDGRAPH_LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("MDGRAPH_LLM_MODEL", "qwen2.5:7b")
    ext = LocalLLMExtractor()
    assert captured["base_url"] == "http://localhost:1234/v1"
    assert ext._model == "qwen2.5:7b"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_local_llm_extractor.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mdgraph.providers.local_llm_extractor'`）

- [ ] **Step 3: 实现 `src/mdgraph/providers/local_llm_extractor.py`**

```python
"""本地 LLM 实体抽取 provider：openai SDK → 本地 OpenAI 兼容端点（默认 Ollama），零外部 key。"""

from __future__ import annotations

import json
import os
import re

from mdgraph.providers.base import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)

_SYSTEM = (
    "你是一个实体关系抽取器。从用户给的文本中抽取关键实体（概念、技术、产品、组织等）"
    "及其类型和一句话描述，以及实体之间的有向关系。只针对文本明确提及的内容，不要臆造。"
    "严格只输出一个 JSON 对象，不要任何额外文字或 markdown 围栏，格式："
    '{"entities":[{"name":"..","type":"..","description":".."}],'
    '"relations":[{"source":"..","target":"..","type":".."}]}'
)


def _first_balanced_object(s: str) -> str | None:
    """返回 s 中第一个括号平衡的 {...} 子串；无则 None。"""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _extract_json(text: str) -> dict | None:
    """从可能含 markdown 围栏/前后解释文字的输出里鲁棒提取 JSON 对象。"""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = (fence.group(1) if fence else text).strip()
    for attempt in (candidate, _first_balanced_object(candidate)):
        if not attempt:
            continue
        try:
            obj = json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


class LocalLLMExtractor(LLMProvider):
    def __init__(self, model=None, base_url=None, api_key=None, client=None) -> None:
        if client is None:
            from openai import OpenAI

            base_url = base_url or os.environ.get("MDGRAPH_LLM_BASE_URL") or "http://localhost:11434/v1"
            api_key = api_key or os.environ.get("MDGRAPH_LLM_API_KEY") or "ollama"
            client = OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self._model = model or os.environ.get("MDGRAPH_LLM_MODEL") or "qwen2.5:3b"

    def extract(self, text: str) -> ExtractionResult:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
            )
            content = resp.choices[0].message.content or ""
            payload = _extract_json(content)
            if payload is None:
                return ExtractionResult()
            entities = [
                ExtractedEntity(
                    name=e["name"],
                    type=e.get("type") or "concept",
                    description=e.get("description") or "",
                )
                for e in payload.get("entities", [])
            ]
            relations = [
                ExtractedRelation(
                    source=r["source"],
                    target=r["target"],
                    type=r.get("type") or "related_to",
                )
                for r in payload.get("relations", [])
            ]
            return ExtractionResult(entities=entities, relations=relations)
        except Exception:  # noqa: BLE001 — 任何失败降级空抽取，交由 indexer 记 warning
            return ExtractionResult()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_local_llm_extractor.py -v`
Expected: PASS（13 passed）

- [ ] **Step 5: pyproject `local` extra 加 openai** — `pyproject.toml` 把现有
  `local = ["fastembed>=0.3"]` 改为：

```toml
local = ["fastembed>=0.3", "openai>=1.0"]
```

- [ ] **Step 6: Commit**

```bash
git add src/mdgraph/providers/local_llm_extractor.py tests/test_local_llm_extractor.py pyproject.toml
git commit -m "$(cat <<'EOF'
feat: LocalLLMExtractor (local OpenAI-compatible endpoint, robust JSON parse)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: demo provider 选择 + README + 选择逻辑测试

**Files:**
- Modify: `examples/run_demo.py`（加 `_make_llm()`，main 重构 provider 选择）
- Modify: `examples/README.md`（补本地 LLM 用法）
- Test: `tests/test_run_demo.py`（追加 `_make_llm` 选择测试）

**Interfaces:**
- Consumes: `LocalLLMExtractor`（Task 1）、`ClaudeExtractor`（切片 7）、`FastEmbedProvider`、`MarkdownGraph`。
- Produces: `run_demo._make_llm() -> LLMProvider`（按 env `MDGRAPH_LLM` 选择）。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_run_demo.py` 末尾追加：

```python
def test_make_llm_defaults_to_local(monkeypatch):
    monkeypatch.delenv("MDGRAPH_LLM", raising=False)
    from mdgraph.providers.local_llm_extractor import LocalLLMExtractor
    llm = run_demo._make_llm()
    assert isinstance(llm, LocalLLMExtractor)


def test_make_llm_claude_when_selected(monkeypatch):
    monkeypatch.setenv("MDGRAPH_LLM", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    from mdgraph.providers.anthropic_extractor import ClaudeExtractor
    llm = run_demo._make_llm()
    assert isinstance(llm, ClaudeExtractor)


def test_make_llm_claude_missing_creds_raises(monkeypatch):
    monkeypatch.setenv("MDGRAPH_LLM", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    import pytest
    with pytest.raises(RuntimeError):
        run_demo._make_llm()
```

（`tests/test_run_demo.py` 顶部已有 `run_demo` 模块导入；构造 `LocalLLMExtractor()`/`ClaudeExtractor()` 只建 client、不发网络请求，故类型可测。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_run_demo.py -k make_llm -v`
Expected: FAIL（`AttributeError: module 'run_demo' has no attribute '_make_llm'`）

- [ ] **Step 3: 加 `_make_llm()` + 重构 main** — `examples/run_demo.py`：

在 `top_mentioned_entities` 之后、`main` 之前插入：

```python
def _make_llm():
    """按 env MDGRAPH_LLM 选择 LLM provider：默认本地（Ollama），可选 claude。"""
    choice = os.environ.get("MDGRAPH_LLM", "local")
    if choice == "claude":
        if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
            raise RuntimeError(
                "MDGRAPH_LLM=claude 需要 .env 配 ANTHROPIC_AUTH_TOKEN(+ANTHROPIC_BASE_URL) 或 ANTHROPIC_API_KEY"
            )
        from mdgraph.providers.anthropic_extractor import ClaudeExtractor

        return ClaudeExtractor()
    from mdgraph.providers.local_llm_extractor import LocalLLMExtractor

    return LocalLLMExtractor()
```

把 `main()` 的第 73-92 行（凭证检查 + import + embedder 构造 + `mg = MarkdownGraph(..., llm=ClaudeExtractor())`）替换为：

```python
    load_env(ROOT / ".env")
    try:
        from mdgraph.providers.fastembed_embedder import FastEmbedProvider  # noqa: F401
    except ImportError as exc:
        print(f"缺少依赖：{exc}（请 `pip install fastembed openai`）", file=sys.stderr)
        return 1
    try:
        llm = _make_llm()
    except Exception as exc:  # noqa: BLE001
        print(f"LLM provider 初始化失败：{exc}", file=sys.stderr)
        return 1

    mode = os.environ.get("MDGRAPH_LLM", "local")
    print(f"== 构建图谱（embedder=fastembed，llm={mode}；首次会下载 embedding 模型，请稍候）==")
    try:
        embedder = FastEmbedProvider()
    except Exception as exc:  # noqa: BLE001
        print(f"embedding 模型加载失败（需联网下载一次）：{exc}", file=sys.stderr)
        return 1
    mg = None
    try:
        mg = MarkdownGraph(STORE, embedder=embedder, llm=llm)
```

（`main()` 第 92 行之后的 build / 四块对比打印 / `finally: mg.close()` 全部保持不变。若 `llm=local` 而本地端点不可达，逐 chunk 抽取会降级空、build 仍完成，`report.warnings` 增多——属预期。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_run_demo.py -v`
Expected: PASS（原有 + 3 个新 `_make_llm` 测试全绿）

- [ ] **Step 5: 更新 `examples/README.md`** — 在「运行」一节前补一段本地 LLM 用法：

````markdown
## 本地 LLM 实体层（推荐，零外部 key）

默认用本地 Ollama 做实体抽取，无需任何外部凭证：

```bash
pip install fastembed openai          # 本地依赖
ollama serve &                        # 启动 Ollama（若未运行）
ollama pull qwen2.5:3b                # 拉中文模型（约 2GB，仅首次）
MDGRAPH_LLM=local PYTHONPATH=src python examples/run_demo.py
```

可经环境变量覆盖：`MDGRAPH_LLM_BASE_URL`（默认 `http://localhost:11434/v1`）、
`MDGRAPH_LLM_MODEL`（默认 `qwen2.5:3b`）、`MDGRAPH_LLM_API_KEY`（默认 `ollama`）。
任何 OpenAI 兼容端点（LM Studio、vLLM、llama.cpp server）都可用，改 `MDGRAPH_LLM_BASE_URL` 即可。

用 Anthropic Claude（需凭证）则设 `MDGRAPH_LLM=claude` 并在 `.env` 填 Anthropic 凭证。
````

- [ ] **Step 6: 全套回归**

Run: `python -m pytest -q`
Expected: PASS（152 既有 + Task 1/2 新增，全绿；真实 Ollama/openai 不参与）。

- [ ] **Step 7: Commit**

```bash
git add examples/run_demo.py examples/README.md tests/test_run_demo.py
git commit -m "$(cat <<'EOF'
feat: run_demo MDGRAPH_LLM provider switch (local default) + README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 真实端到端验证（手动，合并后由 controller + 用户执行，不进 subagent TDD / CI）

合并切片 8 后，起本地 LLM 并跑真实 demo（controller 用放开网络的命令协助）：

```bash
ollama serve &                 # 若未运行
ollama pull qwen2.5:3b         # 约 2GB，仅首次
MDGRAPH_LLM=local PYTHONPATH=src python examples/run_demo.py
```

记录并对照切片 7 的 mock 结果，观察：
- 跨文档实体合并 top10 是否变为**中文概念实体**（「检索增强生成」「重排序」「向量检索」…），而非 mock 的英文大写词；
- 纯向量 vs 双引擎对比里「图扩展新增」是否仍被中心文档 `llm.md` 主导（hub 偏置是否被真实中文实体桥接缓解）；
- 据此决定是否单开「hub 偏置改进切片」。

---

## 任务依赖与顺序

1. **Task 1**（LocalLLMExtractor）— 独立。
2. **Task 2**（demo provider 选择）— 依赖 Task 1 的 `LocalLLMExtractor`。

按 1→2 顺序执行；真实端到端为合并后手动验证。

## Self-Review

**1. Spec 覆盖：**
- §3/§4 `LocalLLMExtractor` + `_extract_json`/`_first_balanced_object` → Task 1 ✓；pyproject `local` 加 openai → Task 1 Step 5 ✓。
- §4 默认配置 + env 覆盖（base_url/api_key/model）→ Task 1 测试 `test_default_endpoint_and_model`/`test_env_overrides` ✓。
- §4 鲁棒解析容错链（裸/围栏/前后文字/嵌套/无 JSON）→ Task 1 `_extract_json` 测试 ✓；降级（畸形/API 异常）→ ✓。
- §5 demo provider 选择（`MDGRAPH_LLM` local/claude）→ Task 2 `_make_llm` + main 重构 + 测试 ✓。
- §6 离线契约（注入 fake / monkeypatch openai.OpenAI，不连 Ollama）→ Task 1/2 测试均注入/ monkeypatch ✓。
- §8 端点不可达降级 + 提示 → `extract` 降级（Task 1）+ main 模式提示（Task 2）✓。
- §9 任务切分（1 provider、2 demo、3 手动验证）→ 对应 Task 1/2 + 手动验证节 ✓。

**2. Placeholder 扫描：** 无 TBD/TODO；provider/解析/测试/demo 改动均含完整代码。✓

**3. 类型一致性：**
- `LocalLLMExtractor(model=None, base_url=None, api_key=None, client=None)`、`extract` Task 1 定义、Task 2 `_make_llm` 与手动验证使用 ✓。
- `_extract_json`/`_first_balanced_object` Task 1 定义并被同任务测试消费 ✓。
- `_make_llm()` Task 2 定义、main 与测试消费 ✓。
- fake openai client 结构（`chat.completions.create -> resp.choices[0].message.content`）与 §4 `extract` 读取路径一致 ✓。
- `ExtractedEntity(name,type,description)`/`ExtractedRelation(source,target,type)` 用法与 base.py 一致 ✓。
