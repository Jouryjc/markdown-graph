# mdgraph 基础层（Plan 1 / 切片 1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭好 mdgraph 的基础层——核心数据模型、可插拔 provider 抽象（含确定性 mock）、嵌入式 GraphStore（SQLite+NetworkX）与 VectorStore（LanceDB），全部带通过的单测。

**Architecture:** 纯 Python 库骨架。`models` 定义 pydantic 数据模型；`providers` 定义 LLM/Embedding 抽象基类 + 离线可测的 mock 实现；`store` 提供两个嵌入式存储（图用 SQLite 落盘 + NetworkX 内存遍历，向量用 LanceDB 并按模型名+维度版本化表）。本切片不含 parse/chunk/extract/retrieve，但产出的存储与 provider 层可独立单测。

**Tech Stack:** Python 3.11+、pydantic v2、networkx、lancedb、pyarrow、pytest。打包用 hatchling，测试经 `pythonpath=["src"]` 直接 import 源码、免安装。

> 本计划是切片序列的第 1 个。后续切片（2 结构索引 / 3 向量检索 / 4 语义抽取 / 5 图融合 / 6 增量+CLI）各自单独出计划。

---

## 文件结构

本切片创建的文件及职责：

- `pyproject.toml` — 包元数据、依赖、pytest 配置。
- `src/mdgraph/__init__.py` — 包入口，导出公共符号。
- `src/mdgraph/models.py` — 核心数据模型：枚举 `NodeType`/`EdgeType`，模型 `Document`/`Chunk`/`Node`/`Edge`。
- `src/mdgraph/providers/__init__.py` — providers 子包入口。
- `src/mdgraph/providers/base.py` — 抽象接口 `LLMProvider`/`EmbeddingProvider` 与抽取结果 dataclass。
- `src/mdgraph/providers/mock.py` — 确定性 mock：`DeterministicEmbeddingProvider`、`MockLLMProvider`。
- `src/mdgraph/store/__init__.py` — store 子包入口。
- `src/mdgraph/store/graph_store.py` — `GraphStore`（SQLite + NetworkX）。
- `src/mdgraph/store/vector_store.py` — `VectorStore`（LanceDB）。
- `tests/...` — 对应单测。

---

## Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `src/mdgraph/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: 写失败测试**

`tests/test_smoke.py`:

```python
def test_package_imports_and_has_version():
    import mdgraph

    assert mdgraph.__version__ == "0.1.0"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdgraph'`（pyproject 尚未配置 pythonpath / 包尚未创建）。

- [ ] **Step 3: 写 pyproject.toml**

`pyproject.toml`:

```toml
[project]
name = "mdgraph"
version = "0.1.0"
description = "Markdown knowledge graph + vector dual-engine retrieval"
requires-python = ">=3.11"
dependencies = [
    "markdown-it-py>=3.0",
    "networkx>=3.0",
    "lancedb>=0.6",
    "pydantic>=2.0",
    "numpy>=1.24",
    "typer>=0.9",
    "pyarrow>=14.0",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.30"]
voyage = ["voyageai>=0.2"]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mdgraph"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 4: 写包入口**

`src/mdgraph/__init__.py`:

```python
"""mdgraph: Markdown knowledge graph + vector dual-engine retrieval."""

__version__ = "0.1.0"
```

- [ ] **Step 5: 安装依赖**

Run: `pip install -e ".[dev]"`
Expected: 安装成功（lancedb/pyarrow 等就位）。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml src/mdgraph/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold mdgraph package"
```

---

## Task 2: 核心数据模型

**Files:**
- Create: `src/mdgraph/models.py`
- Modify: `src/mdgraph/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_models.py`:

```python
from mdgraph.models import (
    NodeType,
    EdgeType,
    Document,
    Chunk,
    Node,
    Edge,
)


def test_enums_have_expected_values():
    assert NodeType.DOCUMENT.value == "document"
    assert NodeType.CHUNK.value == "chunk"
    assert EdgeType.LINKS_TO.value == "links_to"
    assert EdgeType.MENTIONS.value == "mentions"


def test_document_defaults_frontmatter_to_empty_dict():
    doc = Document(id="d1", path="/a.md", hash="abc", mtime=1.0)
    assert doc.frontmatter == {}


def test_chunk_roundtrip_fields():
    c = Chunk(
        id="c1",
        doc_id="d1",
        section_path="H1>H2",
        text="hello",
        char_start=0,
        char_end=5,
    )
    assert c.doc_id == "d1"
    assert c.char_end == 5


def test_node_and_edge_construct():
    n = Node(id="n1", type=NodeType.ENTITY, doc_id=None, meta={"name": "X"})
    e = Edge(src="a", dst="b", type=EdgeType.RELATES_TO, weight=0.5)
    assert n.type is NodeType.ENTITY
    assert n.meta["name"] == "X"
    assert e.weight == 0.5
    assert e.meta == {}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdgraph.models'`

- [ ] **Step 3: 写实现**

`src/mdgraph/models.py`:

```python
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
```

- [ ] **Step 4: 更新包入口导出模型**

`src/mdgraph/__init__.py`:

```python
"""mdgraph: Markdown knowledge graph + vector dual-engine retrieval."""

from mdgraph.models import (
    Chunk,
    Document,
    Edge,
    EdgeType,
    Node,
    NodeType,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Chunk",
    "Document",
    "Edge",
    "EdgeType",
    "Node",
    "NodeType",
]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS（4 个测试全过）

- [ ] **Step 6: 提交**

```bash
git add src/mdgraph/models.py src/mdgraph/__init__.py tests/test_models.py
git commit -m "feat: add core data models (Document/Chunk/Node/Edge)"
```

---

## Task 3: Provider 抽象与确定性 mock

**Files:**
- Create: `src/mdgraph/providers/__init__.py`
- Create: `src/mdgraph/providers/base.py`
- Create: `src/mdgraph/providers/mock.py`
- Test: `tests/test_providers_mock.py`

- [ ] **Step 1: 写失败测试**

`tests/test_providers_mock.py`:

```python
from mdgraph.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    ExtractionResult,
)
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)


def test_embedding_provider_is_subclass_and_reports_dim_name():
    emb = DeterministicEmbeddingProvider(dim=16, name="mock-embed")
    assert isinstance(emb, EmbeddingProvider)
    assert emb.dim == 16
    assert emb.name == "mock-embed"


def test_embedding_is_deterministic_and_correct_dim():
    emb = DeterministicEmbeddingProvider(dim=16)
    a = emb.embed(["hello world"])
    b = emb.embed(["hello world"])
    assert a == b
    assert len(a) == 1
    assert len(a[0]) == 16


def test_embedding_is_unit_normalized_for_nonempty_text():
    emb = DeterministicEmbeddingProvider(dim=16)
    vec = emb.embed(["alpha beta gamma"])[0]
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_different_text_gives_different_vector():
    emb = DeterministicEmbeddingProvider(dim=16)
    assert emb.embed(["cat"])[0] != emb.embed(["dog"])[0]


def test_mock_llm_extracts_capitalized_entities_and_chain_relations():
    llm = MockLLMProvider()
    assert isinstance(llm, LLMProvider)
    result = llm.extract("Alpha relates to Beta and Gamma here.")
    assert isinstance(result, ExtractionResult)
    names = [e.name for e in result.entities]
    assert names == ["Alpha", "Beta", "Gamma"]
    rels = [(r.source, r.target) for r in result.relations]
    assert rels == [("Alpha", "Beta"), ("Beta", "Gamma")]


def test_mock_llm_dedupes_entities():
    llm = MockLLMProvider()
    result = llm.extract("Alpha and Alpha again.")
    assert [e.name for e in result.entities] == ["Alpha"]
    assert result.relations == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_providers_mock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdgraph.providers'`

- [ ] **Step 3: 写 providers 子包入口**

`src/mdgraph/providers/__init__.py`:

```python
"""可插拔 LLM / Embedding provider。"""

from mdgraph.providers.base import (
    EmbeddingProvider,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)

__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "ExtractionResult",
    "ExtractedEntity",
    "ExtractedRelation",
]
```

- [ ] **Step 4: 写抽象接口**

`src/mdgraph/providers/base.py`:

```python
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
```

- [ ] **Step 5: 写确定性 mock**

`src/mdgraph/providers/mock.py`:

```python
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
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_providers_mock.py -v`
Expected: PASS（6 个测试全过）

- [ ] **Step 7: 提交**

```bash
git add src/mdgraph/providers tests/test_providers_mock.py
git commit -m "feat: add provider abstraction with deterministic mocks"
```

---

## Task 4: GraphStore — SQLite CRUD

**Files:**
- Create: `src/mdgraph/store/__init__.py`
- Create: `src/mdgraph/store/graph_store.py`
- Test: `tests/test_graph_store_crud.py`

- [ ] **Step 1: 写失败测试**

`tests/test_graph_store_crud.py`:

```python
from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def make_store(tmp_path):
    return GraphStore(tmp_path / "graph.db")


def test_document_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    doc = Document(id="d1", path="/a.md", hash="h1", mtime=1.5, frontmatter={"title": "A"})
    store.upsert_document(doc)
    got = store.get_document("d1")
    assert got is not None
    assert got.path == "/a.md"
    assert got.frontmatter == {"title": "A"}
    store.close()


def test_document_upsert_is_idempotent_update(tmp_path):
    store = make_store(tmp_path)
    store.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    store.upsert_document(Document(id="d1", path="/a.md", hash="h2", mtime=2.0))
    got = store.get_document("d1")
    assert got.hash == "h2"
    assert store.stats()["documents"] == 1
    store.close()


def test_node_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    store.upsert_node(Node(id="n1", type=NodeType.ENTITY, meta={"name": "X"}))
    got = store.get_node("n1")
    assert got.type is NodeType.ENTITY
    assert got.meta["name"] == "X"
    store.close()


def test_chunk_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    store.upsert_chunk(
        Chunk(id="c1", doc_id="d1", section_path="H1", text="hi", char_start=0, char_end=2)
    )
    got = store.get_chunk("c1")
    assert got.text == "hi"
    assert got.char_end == 2
    store.close()


def test_edge_upsert_idempotent(tmp_path):
    store = make_store(tmp_path)
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.LINKS_TO, weight=1.0))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.LINKS_TO, weight=2.0))
    assert store.stats()["edges"] == 1
    store.close()


def test_get_missing_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.get_document("nope") is None
    assert store.get_node("nope") is None
    assert store.get_chunk("nope") is None
    store.close()


def test_persists_across_reopen(tmp_path):
    db = tmp_path / "graph.db"
    s1 = GraphStore(db)
    s1.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    s1.close()
    s2 = GraphStore(db)
    assert s2.get_document("d1") is not None
    s2.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_graph_store_crud.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdgraph.store'`

- [ ] **Step 3: 写 store 子包入口**

`src/mdgraph/store/__init__.py`:

```python
"""嵌入式存储：GraphStore（SQLite+NetworkX）与 VectorStore（LanceDB）。"""

from mdgraph.store.graph_store import GraphStore

__all__ = ["GraphStore"]
```

- [ ] **Step 4: 写 GraphStore（CRUD + stats，遍历下个 Task 加）**

`src/mdgraph/store/graph_store.py`:

```python
"""GraphStore：SQLite 为真源持久化结构/语义图，NetworkX 做遍历（见后续方法）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    frontmatter_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    doc_id TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    meta_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src, dst, type)
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    section_path TEXT NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
"""


class GraphStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- documents ---
    def upsert_document(self, doc: Document) -> None:
        self.conn.execute(
            "INSERT INTO documents (id, path, hash, mtime, frontmatter_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET path=excluded.path, hash=excluded.hash, "
            "mtime=excluded.mtime, frontmatter_json=excluded.frontmatter_json",
            (doc.id, doc.path, doc.hash, doc.mtime, json.dumps(doc.frontmatter)),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return None
        return Document(
            id=row["id"],
            path=row["path"],
            hash=row["hash"],
            mtime=row["mtime"],
            frontmatter=json.loads(row["frontmatter_json"]),
        )

    # --- nodes ---
    def upsert_node(self, node: Node) -> None:
        self.conn.execute(
            "INSERT INTO nodes (id, type, doc_id, meta_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET type=excluded.type, doc_id=excluded.doc_id, "
            "meta_json=excluded.meta_json",
            (node.id, node.type.value, node.doc_id, json.dumps(node.meta)),
        )
        self.conn.commit()

    def get_node(self, node_id: str) -> Node | None:
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return Node(
            id=row["id"],
            type=NodeType(row["type"]),
            doc_id=row["doc_id"],
            meta=json.loads(row["meta_json"]),
        )

    # --- edges ---
    def upsert_edge(self, edge: Edge) -> None:
        self.conn.execute(
            "INSERT INTO edges (src, dst, type, weight, meta_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(src, dst, type) DO UPDATE SET weight=excluded.weight, "
            "meta_json=excluded.meta_json",
            (edge.src, edge.dst, edge.type.value, edge.weight, json.dumps(edge.meta)),
        )
        self.conn.commit()

    # --- chunks ---
    def upsert_chunk(self, chunk: Chunk) -> None:
        self.conn.execute(
            "INSERT INTO chunks (id, doc_id, section_path, text, char_start, char_end) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET doc_id=excluded.doc_id, "
            "section_path=excluded.section_path, text=excluded.text, "
            "char_start=excluded.char_start, char_end=excluded.char_end",
            (
                chunk.id,
                chunk.doc_id,
                chunk.section_path,
                chunk.text,
                chunk.char_start,
                chunk.char_end,
            ),
        )
        self.conn.commit()

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            return None
        return Chunk(
            id=row["id"],
            doc_id=row["doc_id"],
            section_path=row["section_path"],
            text=row["text"],
            char_start=row["char_start"],
            char_end=row["char_end"],
        )

    def stats(self) -> dict[str, int]:
        return {
            "documents": self.conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0],
            "nodes": self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "chunks": self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_graph_store_crud.py -v`
Expected: PASS（7 个测试全过）

- [ ] **Step 6: 提交**

```bash
git add src/mdgraph/store/__init__.py src/mdgraph/store/graph_store.py tests/test_graph_store_crud.py
git commit -m "feat: add GraphStore SQLite CRUD"
```

---

## Task 5: GraphStore — 级联删除

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`（新增 `delete_document` 方法，加在 `stats` 之前）
- Test: `tests/test_graph_store_delete.py`

- [ ] **Step 1: 写失败测试**

`tests/test_graph_store_delete.py`:

```python
from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def seed(store):
    # 文档 d1：含一个章节节点 s1、一个块 c1，块指向另一文档 d2 的链接边
    store.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    store.upsert_node(Node(id="s1", type=NodeType.SECTION, doc_id="d1"))
    store.upsert_chunk(
        Chunk(id="c1", doc_id="d1", section_path="H1", text="x", char_start=0, char_end=1)
    )
    store.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    store.upsert_edge(Edge(src="d1", dst="s1", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="c1", dst="d2", type=EdgeType.LINKS_TO))


def test_delete_document_cascades(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    seed(store)
    store.delete_document("d1")
    s = store.stats()
    assert s["documents"] == 0
    assert s["nodes"] == 0  # s1、c1 节点随 doc_id=d1 一并删除
    assert s["chunks"] == 0
    assert s["edges"] == 0  # CONTAINS 与 LINKS_TO（src 在 d1 内）都被清理
    store.close()


def test_delete_document_only_affects_target(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    seed(store)
    store.upsert_document(Document(id="dX", path="/x.md", hash="hx", mtime=1.0))
    store.upsert_node(Node(id="nX", type=NodeType.CHUNK, doc_id="dX"))
    store.delete_document("d1")
    assert store.get_document("dX") is not None
    assert store.get_node("nX") is not None
    store.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_graph_store_delete.py -v`
Expected: FAIL — `AttributeError: 'GraphStore' object has no attribute 'delete_document'`

- [ ] **Step 3: 写实现（在 `graph_store.py` 的 `stats` 方法之前插入）**

```python
    def delete_document(self, doc_id: str) -> None:
        """删除文档及其所有节点/块，并清理任何端点落在该文档节点集合上的边。"""
        node_ids = [
            row["id"]
            for row in self.conn.execute(
                "SELECT id FROM nodes WHERE doc_id = ?", (doc_id,)
            ).fetchall()
        ]
        node_ids.append(doc_id)  # 文档本身也可能是边的端点
        self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self.conn.execute("DELETE FROM nodes WHERE doc_id = ?", (doc_id,))
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        qmarks = ",".join("?" * len(node_ids))
        self.conn.execute(
            f"DELETE FROM edges WHERE src IN ({qmarks}) OR dst IN ({qmarks})",
            node_ids + node_ids,
        )
        self.conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_graph_store_delete.py -v`
Expected: PASS（2 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_delete.py
git commit -m "feat: add GraphStore cascade delete_document"
```

---

## Task 6: GraphStore — NetworkX 多跳遍历

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`（新增 `to_networkx` 与 `neighbors`，加在 `stats` 之前）
- Test: `tests/test_graph_store_traversal.py`

- [ ] **Step 1: 写失败测试**

`tests/test_graph_store_traversal.py`:

```python
import networkx as nx

from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def build_chain(store):
    # a -CONTAINS-> b -LINKS_TO-> c ; 另有 a -TAGGED-> t
    for nid in ["a", "b", "c", "t"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="b", dst="c", type=EdgeType.LINKS_TO))
    store.upsert_edge(Edge(src="a", dst="t", type=EdgeType.TAGGED))


def test_to_networkx_shape(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    g = store.to_networkx()
    assert isinstance(g, nx.MultiDiGraph)
    assert g.number_of_nodes() == 4
    assert g.number_of_edges() == 3
    store.close()


def test_neighbors_one_hop_undirected(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # b 的一跳邻居：a（入边 CONTAINS）与 c（出边 LINKS_TO）
    assert store.neighbors("b", hops=1) == {"a", "c"}
    store.close()


def test_neighbors_two_hops(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # a 两跳：b、t（一跳），再到 c（经 b）
    assert store.neighbors("a", hops=2) == {"b", "t", "c"}
    store.close()


def test_neighbors_filtered_by_edge_type(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # 仅沿 CONTAINS：a 的一跳只有 b（TAGGED 被过滤）
    assert store.neighbors("a", edge_types=[EdgeType.CONTAINS], hops=1) == {"b"}
    store.close()


def test_neighbors_missing_node_returns_empty(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.neighbors("nope") == set()
    store.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_graph_store_traversal.py -v`
Expected: FAIL — `AttributeError: 'GraphStore' object has no attribute 'to_networkx'`

- [ ] **Step 3: 写实现（在 `graph_store.py` 顶部 import 增加 `networkx`，并在 `stats` 之前插入两个方法）**

在文件顶部 import 区加入：

```python
import networkx as nx
```

在 `stats` 方法之前插入：

```python
    def to_networkx(self) -> "nx.MultiDiGraph":
        """从 SQLite 重建内存有向多重图用于遍历。"""
        g = nx.MultiDiGraph()
        for row in self.conn.execute("SELECT * FROM nodes").fetchall():
            g.add_node(
                row["id"],
                type=row["type"],
                doc_id=row["doc_id"],
                meta=json.loads(row["meta_json"]),
            )
        for row in self.conn.execute("SELECT * FROM edges").fetchall():
            g.add_edge(
                row["src"],
                row["dst"],
                key=row["type"],
                type=row["type"],
                weight=row["weight"],
            )
        return g

    def neighbors(
        self,
        node_id: str,
        edge_types: list[EdgeType] | None = None,
        hops: int = 1,
    ) -> set[str]:
        """无向扩展 node_id 的 hops 跳邻居（可按边类型过滤），不含自身。"""
        g = self.to_networkx()
        if node_id not in g:
            return set()
        allowed = {e.value for e in edge_types} if edge_types else None
        visited = {node_id}
        frontier = {node_id}
        for _ in range(hops):
            nxt: set[str] = set()
            for n in frontier:
                for _, dst, key in g.out_edges(n, keys=True):
                    if (allowed is None or key in allowed) and dst not in visited:
                        nxt.add(dst)
                for src, _, key in g.in_edges(n, keys=True):
                    if (allowed is None or key in allowed) and src not in visited:
                        nxt.add(src)
            visited |= nxt
            frontier = nxt
        visited.discard(node_id)
        return visited
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_graph_store_traversal.py -v`
Expected: PASS（5 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_traversal.py
git commit -m "feat: add GraphStore NetworkX traversal (neighbors)"
```

---

## Task 7: VectorStore — LanceDB

**Files:**
- Create: `src/mdgraph/store/vector_store.py`
- Modify: `src/mdgraph/store/__init__.py`（导出 `VectorStore`）
- Test: `tests/test_vector_store.py`

- [ ] **Step 1: 写失败测试**

`tests/test_vector_store.py`:

```python
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.store.vector_store import VectorStore


def make_store(tmp_path, dim=16):
    return VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=dim)


def test_table_name_is_versioned_by_model_and_dim(tmp_path):
    store = make_store(tmp_path)
    assert store.table_name == "vectors_mock_embed_16"
    store.close()


def test_add_and_count(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta", "gamma"]
    vecs = emb.embed(texts)
    store.add(["c1", "c2", "c3"], vecs, texts)
    assert store.count() == 3
    store.close()


def test_search_returns_closest_first(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta", "gamma"]
    vecs = emb.embed(texts)
    store.add(["c1", "c2", "c3"], vecs, texts)
    # 用 "beta" 的向量查询，最近的应是 c2
    query = emb.embed(["beta"])[0]
    results = store.search(query, k=3)
    assert results[0]["chunk_id"] == "c2"
    assert len(results) == 3
    assert "score" in results[0]
    store.close()


def test_delete_removes_rows(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta"]
    store.add(["c1", "c2"], emb.embed(texts), texts)
    store.delete(["c1"])
    assert store.count() == 1
    remaining = [r["chunk_id"] for r in store.search(emb.embed(["beta"])[0], k=5)]
    assert "c1" not in remaining
    store.close()


def test_empty_add_is_noop(tmp_path):
    store = make_store(tmp_path)
    store.add([], [], [])
    assert store.count() == 0
    store.close()


def test_reopen_keeps_data(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    s1 = VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=16)
    s1.add(["c1"], emb.embed(["alpha"]), ["alpha"])
    s1.close()
    s2 = VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=16)
    assert s2.count() == 1
    s2.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_vector_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdgraph.store.vector_store'`

- [ ] **Step 3: 写实现**

`src/mdgraph/store/vector_store.py`:

```python
"""VectorStore：基于 LanceDB 的嵌入式向量库，表名按模型名+维度版本化。"""

from __future__ import annotations

import re
from pathlib import Path

import lancedb
import pyarrow as pa


class VectorStore:
    def __init__(self, dir: str | Path, model_name: str, dim: int) -> None:
        self.dir = str(dir)
        self.model_name = model_name
        self.dim = dim
        self.table_name = self._table_name(model_name, dim)
        self.db = lancedb.connect(self.dir)
        if self.table_name in self.db.table_names():
            self.table = self.db.open_table(self.table_name)
        else:
            schema = pa.schema(
                [
                    pa.field("chunk_id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                    pa.field("text", pa.string()),
                ]
            )
            self.table = self.db.create_table(self.table_name, schema=schema)

    @staticmethod
    def _table_name(model_name: str, dim: int) -> str:
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", model_name).strip("_")
        return f"vectors_{safe}_{dim}"

    def add(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        texts: list[str],
    ) -> None:
        rows = [
            {"chunk_id": cid, "vector": vec, "text": txt}
            for cid, vec, txt in zip(chunk_ids, vectors, texts)
        ]
        if rows:
            self.table.add(rows)

    def search(self, query_vector: list[float], k: int = 8) -> list[dict]:
        results = self.table.search(query_vector).limit(k).to_list()
        return [
            {"chunk_id": r["chunk_id"], "text": r["text"], "score": r["_distance"]}
            for r in results
        ]

    def delete(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        ids = ",".join(f"'{c}'" for c in chunk_ids)
        self.table.delete(f"chunk_id IN ({ids})")

    def count(self) -> int:
        return self.table.count_rows()

    def close(self) -> None:
        # LanceDB 无显式连接需关闭；保留以对齐 GraphStore 接口。
        pass
```

- [ ] **Step 4: 更新 store 子包入口导出 VectorStore**

`src/mdgraph/store/__init__.py`:

```python
"""嵌入式存储：GraphStore（SQLite+NetworkX）与 VectorStore（LanceDB）。"""

from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore

__all__ = ["GraphStore", "VectorStore"]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_vector_store.py -v`
Expected: PASS（6 个测试全过）

- [ ] **Step 6: 跑全量测试套件**

Run: `pytest -v`
Expected: 所有测试 PASS（smoke / models / providers / graph_store ×3 / vector_store）。

- [ ] **Step 7: 提交**

```bash
git add src/mdgraph/store/vector_store.py src/mdgraph/store/__init__.py tests/test_vector_store.py
git commit -m "feat: add VectorStore (LanceDB) with versioned table"
```

---

## 完成标准（切片 1）

- `pytest -v` 全绿。
- `python -c "import mdgraph; from mdgraph.store import GraphStore, VectorStore; from mdgraph.providers.mock import MockLLMProvider, DeterministicEmbeddingProvider"` 无报错。
- 产出物：可独立使用、可持久化、可遍历的图存储 + 可版本化的向量存储 + 可替换的 provider 抽象。后续切片 2（parse+chunk+结构建图）在此之上构建。
