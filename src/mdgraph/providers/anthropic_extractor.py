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
