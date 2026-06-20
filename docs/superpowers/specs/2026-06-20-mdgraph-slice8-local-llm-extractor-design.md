# mdgraph 切片 8：本地 LLM 实体抽取 provider + 真实本地双引擎 demo — 设计文档

- 日期：2026-06-20
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 后续「真实 provider」增强）
- 前置：切片 1~7 均已合并 main（切片 7 已交付 FastEmbedProvider + ClaudeExtractor + 中文 demo）

## 1. 目标与范围

补一个**完全本地、零外部 key** 的 LLM 实体抽取 provider `LocalLLMExtractor`（走 openai SDK 指向本地 OpenAI 兼容端点，默认 Ollama），套进既有 `LLMProvider` 抽象、引擎零改动。配合切片 7 的 FastEmbedProvider，组成「本地向量 + 本地 LLM」的完整离线双引擎，并用真实中文实体层重跑 demo，观察对切片 7 发现的 hub 偏置的影响。

背景：切片 7 准备的 Anthropic 中转端点不可用（一个限制只给 Claude Code 客户端、一个宕机），官方 key 暂不便取。本地 LLM 是当前可行且最贴合项目「本地优先」定位的真实语义来源。

### 不在本切片范围（YAGNI）

- 真实 Ollama 调用 / 模型下载进 CI 套件——离线契约测试用注入 fake，真实端到端只手动跑。
- function-calling / JSON mode——本切片用「JSON prompt + 鲁棒解析」，对任意本地模型/端点最通用（决策见 §2）。
- hub 偏置的实际改进——本切片只**观察**真实中文实体层对它的影响，据结果再决定是否单开改进切片。
- 把本地 provider 设为引擎默认——仍按 dotted-path / env 显式选择。

## 2. 关键决策

| 维度 | 决策 |
|---|---|
| runtime | 本地 Ollama（已装 0.20.5），OpenAI 兼容端点 `http://localhost:11434/v1` |
| 模型 | 默认 `qwen2.5:3b`（中文好、~2GB、内存友好），可经 env 覆盖 |
| SDK | `openai`（已装 1.99.1）；`OpenAI(base_url=, api_key=)` |
| 凭证 | 本地端点不校验；`api_key` 用占位 `"ollama"`（openai SDK 要求非空），可经 env 覆盖 |
| 结构化抽取 | **JSON prompt + 鲁棒解析**：system 要求只输出 JSON，`_extract_json` 容错剥围栏/取第一个平衡 `{...}`。不依赖 function-calling（本地小模型遵循度参差） |
| 降级 | 任何失败（端点不可达、解析失败、缺键）→ 空 `ExtractionResult`，复用 indexer `failed_chunks`/warning（与 ClaudeExtractor 一致） |
| 注入 | `LocalLLMExtractor(client=None)`，注入 fake 用于离线契约测试 |
| demo 选择 | `run_demo.py` 按 env `MDGRAPH_LLM`（默认 `local`）选 `LocalLLMExtractor` / `claude` 选 `ClaudeExtractor` |

## 3. 组件

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/providers/local_llm_extractor.py`（新） | `LocalLLMExtractor(LLMProvider)` + `_extract_json` 鲁棒解析 | openai |
| `examples/run_demo.py`（改） | `main()` 加 `MDGRAPH_LLM` provider 选择 | engine, providers |
| `examples/README.md`（改） | 补本地 LLM 用法 | — |
| `pyproject.toml`（改） | `local` extra 加 `openai>=1.0` | — |

## 4. LocalLLMExtractor 细节

```python
_SYSTEM = (
    "你是一个实体关系抽取器。从用户给的文本中抽取关键实体（概念、技术、产品、组织等）"
    "及其类型和一句话描述，以及实体之间的有向关系。只针对文本明确提及的内容，不要臆造。"
    "严格只输出一个 JSON 对象，不要任何额外文字或 markdown 围栏，格式："
    '{"entities":[{"name":"..","type":"..","description":".."}],'
    '"relations":[{"source":"..","target":"..","type":".."}]}'
)


class LocalLLMExtractor(LLMProvider):
    def __init__(self, model=None, base_url=None, api_key=None, client=None):
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
                model=self._model, temperature=0,
                messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text}],
            )
            content = resp.choices[0].message.content or ""
            payload = _extract_json(content)
            if payload is None:
                return ExtractionResult()
            entities = [
                ExtractedEntity(name=e["name"], type=e.get("type") or "concept", description=e.get("description") or "")
                for e in payload.get("entities", [])
            ]
            relations = [
                ExtractedRelation(source=r["source"], target=r["target"], type=r.get("type") or "related_to")
                for r in payload.get("relations", [])
            ]
            return ExtractionResult(entities=entities, relations=relations)
        except Exception:  # noqa: BLE001 — 任何失败降级空抽取
            return ExtractionResult()
```

`_extract_json(text) -> dict | None`（鲁棒）：

```python
def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = (fence.group(1) if fence else text).strip()
    for attempt in (candidate, _first_balanced_object(candidate)):
        if not attempt:
            continue
        try:
            obj = json.loads(attempt)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _first_balanced_object(s: str) -> str | None:
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
```

容错链：① 整段（去围栏）直接 `json.loads`；② 失败则取第一个平衡 `{...}` 再 `json.loads`；③ 都失败 → None → 空抽取。

## 5. demo 接入

`run_demo.py` 的 `main()` 把 `llm=ClaudeExtractor()` 改为按 env 选择：

```python
def _make_llm():
    choice = os.environ.get("MDGRAPH_LLM", "local")
    if choice == "claude":
        from mdgraph.providers.anthropic_extractor import ClaudeExtractor
        return ClaudeExtractor()
    from mdgraph.providers.local_llm_extractor import LocalLLMExtractor
    return LocalLLMExtractor()
```

`main()` 的凭证检查改为：`local` 路径不需 Anthropic 凭证（只需本地端点可达，调用失败时 extract 降级 + 提示）；`claude` 路径保留原凭证检查。其余（fastembed embedder、四块对比打印）不变。

## 6. 测试策略（离线确定性，不连真实 Ollama）

- `tests/test_local_llm_extractor.py`（注入 fake openai client，client 形如 `client.chat.completions.create(...) -> resp`，`resp.choices[0].message.content` 为构造字符串）：
  - 纯 JSON 字符串 → 正确解析 entities/relations；
  - ` ```json ... ``` ` 围栏包裹 → 仍解析；
  - 前后带解释文字（"好的，结果如下：{...} 希望有帮助"）→ 取出 JSON 解析；
  - 畸形 JSON / 无 `{` → 降级空；
  - `create` 抛异常 → 降级空；
  - env `MDGRAPH_LLM_MODEL`/`MDGRAPH_LLM_BASE_URL` 注入（monkeypatch `openai.OpenAI` 捕获 kwargs，验证 base_url/默认值与 model）。
- `_extract_json` / `_first_balanced_object` 单元测试（裸 JSON、围栏、前后文字、嵌套对象、无 JSON → None）。
- `run_demo._make_llm` 选择逻辑：env `MDGRAPH_LLM=local`/`claude` → 返回对应类型（构造 OpenAI/Anthropic client 不发请求，类型可测；Anthropic 分支需凭证 env，测试用 monkeypatch 设占位或注入）。
- 真实端到端（Ollama serve + qwen2.5:3b + `MDGRAPH_LLM=local`）= 手动跑，不进 CI。

## 7. 技术栈 / 依赖

- `pyproject.toml` 的 `local` extra 由 `["fastembed>=0.3"]` 改为 `["fastembed>=0.3", "openai>=1.0"]`（openai 已装 1.99.1）。无其它新依赖。契约测试注入 fake、不需真连 Ollama。

## 8. 错误处理 / 边界

- 本地端点不可达（Ollama 未起）→ `create` 抛连接错误 → 单 chunk 降级空；run_demo 若全部空，提示「本地 LLM 端点不可达：请确认 `ollama serve` 已运行、`qwen2.5:3b` 已 `ollama pull`」。
- 模型未拉 → Ollama 返回错误 → 降级空 + 同上提示。
- 小模型输出不规范（多余文字/围栏）→ `_extract_json` 鲁棒兜住；彻底无 JSON → 空抽取（该 chunk 降级为纯结构）。
- `LocalLLMExtractor` 与 `ClaudeExtractor` 行为对齐：都「失败即空、不崩」，indexer 的 `failed_chunks`/warning 路径不变。

## 9. 建议的任务切分（写计划时细化）

1. `LocalLLMExtractor` + `_extract_json`/`_first_balanced_object` + 契约测试（注入 fake，覆盖鲁棒解析与降级）+ pyproject `local` extra 加 openai。
2. `run_demo.py` 的 `_make_llm` provider 选择 + main 凭证分支调整 + `examples/README.md` 本地用法 + `_make_llm` 选择逻辑测试。
3. 真实端到端：起 Ollama + 拉 qwen2.5:3b + `MDGRAPH_LLM=local` 跑 demo，记录「fastembed 向量 + 本地中文实体」的纯向量 vs 双引擎对比、子图、跨文档**中文**实体合并，并对照切片 7 mock 结果观察 hub 偏置变化。

## 10. 给后续的接缝

- 若真实中文实体层仍未缓解 hub 偏置（中心文档被图扩展过度放大），单开「hub 偏置改进切片」：图扩展按节点度数降权 / 每种子限流 / RRF 给向量更高权重 + 图距离衰减。本切片的真实 demo 输出即其基准。
- `LocalLLMExtractor` 的 base_url/model 可配，天然支持任意 OpenAI 兼容端点（LM Studio、vLLM、本地 llama.cpp server），不止 Ollama。
- CLI provider 短名注册表（让 `--llm local` / `--embedder fastembed` 生效）仍是独立 CLI 增强。
