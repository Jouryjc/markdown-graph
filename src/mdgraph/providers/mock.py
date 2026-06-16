"""离线、确定性的 mock provider，供测试使用。"""

from __future__ import annotations

import hashlib
import re

from mdgraph.providers.base import (
    EmbeddingProvider,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """基于 token 哈希的确定性 embedding：同文本恒等、非空文本单位归一化。"""

    def __init__(self, dim: int = 16, name: str = "mock-embed") -> None:
        self._dim = dim
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in re.findall(r"\w+", text.lower()):
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            vec[h % self._dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class MockLLMProvider(LLMProvider):
    """确定性抽取：大写开头单词视作实体，相邻实体串成链式关系。"""

    def extract(self, text: str) -> ExtractionResult:
        names: list[str] = []
        for token in re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", text):
            if token not in names:
                names.append(token)
        entities = [ExtractedEntity(name=n) for n in names]
        relations = [
            ExtractedRelation(source=names[i], target=names[i + 1])
            for i in range(len(names) - 1)
        ]
        return ExtractionResult(entities=entities, relations=relations)
