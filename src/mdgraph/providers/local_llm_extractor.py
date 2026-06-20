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
