"""SAG 事件/实体抽取 provider：每 chunk → 一条融合事件 + 带类型实体。

镜像 local_llm_extractor.py（真 openai SDK 仅 client is None 懒导入；client= 可注入；
默认 MDGRAPH_LLM_*；失败/坏 JSON/空 → None；不抛崩构建）。按 provider 隔离惯例，
JSON 解析助手在本文件内自带（不跨文件依赖）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# 复刻 SAG 的固定 11 类实体 taxonomy（不在此列的 type 一律归为 "tags"）。
# 每类带中文定义：小模型只靠类型名无法判别（如概念/技术应归 subject），
# 缺定义时会把一切塞进 tags，导致实体类型层失去区分度。定义直接进 system 提示与 meta。
SAG_ENTITY_TYPE_DESCRIPTIONS: dict[str, str] = {
    "person": "人物、作者、用户、负责人等具体个人",
    "organization": "公司、机构、团体、政府部门、学校、团队等组织",
    "location": "地点、地域、国家、城市、场所、地址",
    "time": "日期、年份、时期、时间表达",
    "product": "产品、系统、平台、模型、软件、服务、数据库",
    "metric": "数字、指标、金额、比例、数量、评分、性能数据",
    "action": "动作、行为、流程、操作、状态变化",
    "work": "作品、文档、论文、项目、任务、计划",
    "group": "人群、角色群体、职业群体、用户群体",
    "subject": "主题、概念、领域、技术、专业术语、算法、方法、事件名称",
    "tags": "以上类型都不贴切时才用的兜底标签",
}
SAG_ENTITY_TYPES = list(SAG_ENTITY_TYPE_DESCRIPTIONS)

# meta 里下发「带定义」的类型表（而非裸类型名），模型据此挑最贴切的具体类型。
SAG_ENTITY_TYPE_SPEC = [
    {"type": t, "description": d} for t, d in SAG_ENTITY_TYPE_DESCRIPTIONS.items()
]

_TYPE_GUIDE = "；".join(
    f"{t}={d}" for t, d in SAG_ENTITY_TYPE_DESCRIPTIONS.items()
)

_SYSTEM = (
    "你是 SAG（Semantic Aggregation Graph）的事件/实体抽取器。"
    "对给定的一段文本，抽取**恰好一条**融合事件（event）及其支撑实体（entities）。"
    "事件包含 title（标题）、summary（一句话摘要）、content（忠于原文的事件正文片段）、"
    "category（事件类别）、keywords（关键词数组）。"
    "实体的 type 只能取以下 11 类之一，含义如下：" + _TYPE_GUIDE + "。"
    "请**优先选择最贴切的具体类型**：概念/技术/领域/算法/方法/专业术语一律用 subject，"
    "系统/平台/模型/软件/服务/数据库用 product；只有确实没有任何具体类型贴切时才用 tags（应尽量少用）。"
    "把并列实体（如「A 和 B」）拆成多个实体。每个实体含 type、name、description，"
    "description 说明该实体在事件中的具体角色或关系。"
    "所有 title/summary/content/实体名必须忠于原文，不要臆造文本中没有的内容。"
    "严格只输出一个 JSON 对象，不要任何额外文字或 markdown 围栏，格式："
    '{"type":"response","data":{"items":[{"id":1,'
    '"title":"..","summary":"..","content":"..","category":"..",'
    '"keywords":["..",".."],'
    '"entities":[{"type":"subject","name":"..","description":".."}]}]}}'
)

# 一条 few-shot（input/output 示例），帮助小模型对齐输出结构。
_FEWSHOT_USER = json.dumps(
    {
        "type": "request",
        "data": {
            "items": [
                {
                    "id": 1,
                    "content": "# 发布会\n\n2024 年 3 月，OpenAI 在旧金山发布了大语言模型 GPT-4。",
                }
            ],
            "meta": {
                "source_title": "示例文档",
                "entity_types": SAG_ENTITY_TYPE_SPEC,
                "output_language": "跟随输入语言",
            },
        },
    },
    ensure_ascii=False,
)
_FEWSHOT_ASSISTANT = json.dumps(
    {
        "type": "response",
        "data": {
            "items": [
                {
                    "id": 1,
                    "title": "OpenAI 发布 GPT-4",
                    "summary": "2024 年 3 月 OpenAI 在旧金山发布大语言模型 GPT-4。",
                    "content": "2024 年 3 月，OpenAI 在旧金山发布了大语言模型 GPT-4。",
                    "category": "产品发布",
                    "keywords": ["GPT-4", "OpenAI", "大语言模型", "发布会"],
                    "entities": [
                        {"type": "organization", "name": "OpenAI", "description": "发布 GPT-4 的 AI 公司"},
                        {"type": "product", "name": "GPT-4", "description": "本次发布的大语言模型产品"},
                        {"type": "subject", "name": "大语言模型", "description": "GPT-4 所属的技术领域"},
                        {"type": "location", "name": "旧金山", "description": "发布地点"},
                        {"type": "time", "name": "2024 年 3 月", "description": "发布时间"},
                    ],
                }
            ]
        },
    },
    ensure_ascii=False,
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


@dataclass
class SAGEntity:
    type: str
    name: str
    description: str = ""


@dataclass
class SAGEvent:
    title: str
    summary: str
    content: str
    category: str
    keywords: list[str] = field(default_factory=list)
    entities: list[SAGEntity] = field(default_factory=list)


def _parse_entities(raw: object) -> list[SAGEntity]:
    """逐条防御解析 entities：name 长度>1 才保留；type 不在 taxonomy 归 "tags"。"""
    if not isinstance(raw, list):
        return []
    out: list[SAGEntity] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        if not isinstance(name, str) or len(name.strip()) <= 1:
            continue
        etype = e.get("type")
        if not isinstance(etype, str) or etype not in SAG_ENTITY_TYPES:
            etype = "tags"
        desc = e.get("description")
        out.append(
            SAGEntity(
                type=etype,
                name=name.strip(),
                description=desc if isinstance(desc, str) else "",
            )
        )
    return out


def _coerce_keywords(raw: object) -> list[str]:
    """强制 keywords 为 list[str]：非 list 返回空；非字符串项跳过。"""
    if not isinstance(raw, list):
        return []
    return [k for k in raw if isinstance(k, str) and k.strip()]


def _parse_item(item: object) -> SAGEvent | None:
    """把 data.items[0] 映射为 SAGEvent；非 dict → None。"""
    if not isinstance(item, dict):
        return None
    return SAGEvent(
        title=item.get("title") if isinstance(item.get("title"), str) else "",
        summary=item.get("summary") if isinstance(item.get("summary"), str) else "",
        content=item.get("content") if isinstance(item.get("content"), str) else "",
        category=item.get("category") if isinstance(item.get("category"), str) else "",
        keywords=_coerce_keywords(item.get("keywords")),
        entities=_parse_entities(item.get("entities")),
    )


class SAGExtractor:
    def __init__(self, model=None, base_url=None, api_key=None, client=None) -> None:
        if client is None:
            from openai import OpenAI

            base_url = base_url or os.environ.get("MDGRAPH_LLM_BASE_URL") or "http://localhost:11434/v1"
            api_key = api_key or os.environ.get("MDGRAPH_LLM_API_KEY") or "ollama"
            client = OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self._model = model or os.environ.get("MDGRAPH_LLM_MODEL") or "qwen2.5:3b"

    def extract_event(
        self, content: str, heading: str | None = None, doc_title: str | None = None
    ) -> SAGEvent | None:
        if not content or not content.strip():
            return None
        # heading 作为 markdown H1 前缀，给模型更多事件上下文。
        text = f"# {heading}\n\n{content}" if heading else content
        user = json.dumps(
            {
                "type": "request",
                "data": {
                    "items": [{"id": 1, "content": text}],
                    "meta": {
                        "source_title": doc_title,
                        "entity_types": SAG_ENTITY_TYPE_SPEC,
                        "output_language": "跟随输入语言",
                    },
                },
            },
            ensure_ascii=False,
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _FEWSHOT_USER},
                    {"role": "assistant", "content": _FEWSHOT_ASSISTANT},
                    {"role": "user", "content": user},
                ],
            )
            raw = resp.choices[0].message.content or ""
        except Exception:  # noqa: BLE001 — API/网络失败降级 None，交由 build 记 failed
            return None
        payload = _extract_json(raw)
        if payload is None:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        items = data.get("items")
        if not isinstance(items, list) or not items:
            return None
        return _parse_item(items[0])
