"""Provider 抽象接口与抽取结果数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractedEntity:
    name: str
    type: str = "concept"
    description: str = ""


@dataclass
class ExtractedRelation:
    source: str
    target: str
    type: str = "related_to"


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


class EmbeddingProvider(ABC):
    """把文本批量转成定长向量。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """provider 标识（用于向量库表版本化）。"""

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与输入等长的向量列表。"""


class LLMProvider(ABC):
    """从文本抽取实体与关系。"""

    @abstractmethod
    def extract(self, text: str) -> ExtractionResult:
        ...
