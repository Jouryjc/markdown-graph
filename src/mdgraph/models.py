"""核心数据模型：结构层与语义层共用的节点/边/文档/块。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    DOCUMENT = "document"
    SECTION = "section"
    CHUNK = "chunk"
    ENTITY = "entity"
    TAG = "tag"


class EdgeType(str, Enum):
    CONTAINS = "contains"
    LINKS_TO = "links_to"
    TAGGED = "tagged"
    MENTIONS = "mentions"
    RELATES_TO = "relates_to"


class Document(BaseModel):
    id: str
    path: str
    hash: str
    mtime: float
    frontmatter: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    id: str
    doc_id: str
    section_path: str
    text: str
    char_start: int
    char_end: int


class Node(BaseModel):
    id: str
    type: NodeType
    doc_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    src: str
    dst: str
    type: EdgeType
    weight: float = 1.0
    meta: dict[str, Any] = Field(default_factory=dict)
