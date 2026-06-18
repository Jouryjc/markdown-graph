# mdgraph 切片 6：增量索引 + 孤儿回收 + CLI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把引擎升级为增量索引 + 孤儿回收，消除检索 N+1，并补上 typer 命令行入口（`index/query/stats/graph export`）。

**Architecture:** `GraphStore` 加批量 `get_chunks`、`reclaim_orphans`、`export_graph` 三个纯存储方法；`indexer.index` 按 content-hash 分流出 built（new/changed）子集，仅对其 build/embed/extract，末尾自动回收孤儿；`retrieve._dual` 用批量取代逐节点查询；新增 `cli.py`（typer）经 dotted-path `pkg.mod:attr` 动态加载 provider，引擎本身不绑定任何具体 provider。

**Tech Stack:** Python 3.11+、sqlite3、networkx、pydantic v2、typer（均已在 `pyproject.toml`，无新增依赖）。

## Global Constraints

- Python `>=3.11`，src 布局；运行测试一律用 `python -m pytest`（裸 `pytest` 在本机可能解析到缺 lancedb 的解释器，造成假阴性）。
- **无新增第三方依赖**：typer 已在 `pyproject.toml` 依赖；CLI 仅用 `importlib`/`json`/`sqlite3` 标准库。
- 面向用户的输出与提交信息正文用中文；代码、标识符、路径保持原文。
- 每个 commit 信息结尾必须是：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 枚举值均为小写：`NodeType.ENTITY.value == "entity"`、`NodeType.TAG.value == "tag"`、`EdgeType.MENTIONS.value == "mentions"`、`EdgeType.TAGGED.value == "tagged"`、`EdgeType.LINKS_TO.value == "links_to"`。SQL 里用这些字符串值。
- `ENTITY`/`TAG` 节点 `doc_id=None`，`delete_document` 不会删除它们——孤儿回收是唯一清理途径。
- 测试全程离线确定性：用 `DeterministicEmbeddingProvider`（无参 → dim=16, name="mock-embed"）与 `MockLLMProvider`（无参），无网络。
- `Chunk` 字段：`id, doc_id, section_path, text, char_start, char_end`（见 `src/mdgraph/models.py`）。
- 增量默认 `incremental=True`：现有「重 index 同语料」测试在增量下走 unchanged 路径，`stats`/`vs.count()` 断言仍成立——不得回归。

## 文件结构

| 文件 | 责任 | 本切片动作 |
|---|---|---|
| `src/mdgraph/store/graph_store.py` | SQLite 图存储 | 加 `get_chunks`、`reclaim_orphans`、`export_graph` |
| `src/mdgraph/retrieve.py` | 检索融合 | 改写 `_dual`/`_context` 用批量；补 score 量纲 docstring |
| `src/mdgraph/indexer.py` | 索引编排 | `index(incremental)` 分流 + 末尾回收；`IndexReport` 加 `unchanged`/`reclaimed` |
| `src/mdgraph/engine.py` | 门面 | `build` 透传 `incremental` |
| `src/mdgraph/cli.py` | 命令行入口（新） | typer app + dotted-path 加载 + 四命令 |
| `pyproject.toml` | 打包 | 加 `[project.scripts] mdgraph` |

---

### Task 1: `GraphStore.get_chunks` 批量 + 改写 `retrieve._dual` + score 量纲 docstring

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`（在 `get_chunk` 之后加 `get_chunks`）
- Modify: `src/mdgraph/retrieve.py`（改写 `_dual`/`_context`，补 docstring）
- Test: `tests/test_graph_store_get_chunks.py`（新）；回归 `tests/test_retrieve_dual.py`

**Interfaces:**
- Consumes: `Chunk`（`models.py`）、`GraphStore.expand`/`subgraph`/`get_document`、`reciprocal_rank_fusion`。
- Produces: `GraphStore.get_chunks(ids: list[str]) -> dict[str, Chunk]`（缺失 id 不在返回 dict；空 ids → `{}`）。供 Task 4/5 的 CLI 与检索热路径复用。

- [ ] **Step 1: 写失败测试** — `tests/test_graph_store_get_chunks.py`

```python
from mdgraph.models import Chunk
from mdgraph.store.graph_store import GraphStore


def _mk(store, cid, doc="d1", text="x"):
    store.upsert_chunk(
        Chunk(id=cid, doc_id=doc, section_path="A", text=text, char_start=0, char_end=1)
    )


def test_get_chunks_returns_map(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    _mk(store, "c1", text="alpha")
    _mk(store, "c2", text="beta")
    got = store.get_chunks(["c1", "c2"])
    assert set(got) == {"c1", "c2"}
    assert got["c1"].text == "alpha"
    assert got["c2"].text == "beta"
    store.close()


def test_get_chunks_skips_missing_ids(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    _mk(store, "c1")
    got = store.get_chunks(["c1", "nope"])
    assert set(got) == {"c1"}
    store.close()


def test_get_chunks_empty(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    assert store.get_chunks([]) == {}
    store.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_graph_store_get_chunks.py -v`
Expected: FAIL（`AttributeError: 'GraphStore' object has no attribute 'get_chunks'`）

- [ ] **Step 3: 实现 `get_chunks`** — 在 `src/mdgraph/store/graph_store.py` 的 `get_chunk` 方法之后插入：

```python
    def get_chunks(self, ids: list[str]) -> dict[str, Chunk]:
        """批量取块，返回 {id: Chunk}；缺失 id 不在结果中，空 ids 返回空 dict。"""
        ids = list(ids)
        if not ids:
            return {}
        qmarks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM chunks WHERE id IN ({qmarks})", ids
        ).fetchall()
        return {
            r["id"]: Chunk(
                id=r["id"],
                doc_id=r["doc_id"],
                section_path=r["section_path"],
                text=r["text"],
                char_start=r["char_start"],
                char_end=r["char_end"],
            )
            for r in rows
        }
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_graph_store_get_chunks.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 改写 `retrieve._dual`/`_context` 用批量 + 补 docstring** — 把 `src/mdgraph/retrieve.py` 第 68-101 行的 `_dual` 与 `_context` 整体替换为：

```python
    def _dual(self, rows: list[dict], k: int, hops: int) -> RetrievalResult:
        vector_ranking = [r["chunk_id"] for r in rows]
        row_by_id = {r["chunk_id"]: r for r in rows}
        dist = self.graph_store.expand(vector_ranking, edge_types=_EXPAND_EDGES, hops=hops)
        chunk_map = self.graph_store.get_chunks(list(dist))  # 一次批量取，消 N+1
        graph_chunks = [n for n in dist if n in chunk_map]
        graph_ranking = sorted(graph_chunks, key=lambda n: (dist[n], n))
        fused = reciprocal_rank_fusion([vector_ranking, graph_ranking])
        ordered = sorted(fused, key=lambda c: (-fused[c], c))[:k]
        # 图独有命中块的 source_path：按 doc_id 去重后批量取 document
        doc_ids = {
            chunk_map[cid].doc_id
            for cid in ordered
            if cid not in row_by_id and cid in chunk_map
        }
        doc_paths: dict[str, str] = {}
        for did in doc_ids:
            doc = self.graph_store.get_document(did)
            doc_paths[did] = doc.path if doc is not None else ""
        contexts = [
            self._context(cid, fused[cid], row_by_id, chunk_map, doc_paths)
            for cid in ordered
        ]
        subgraph = self.graph_store.subgraph(ordered)
        return RetrievalResult(contexts=contexts, subgraph=subgraph)

    def _context(
        self,
        chunk_id: str,
        score: float,
        row_by_id: dict,
        chunk_map: dict,
        doc_paths: dict,
    ) -> Context:
        if chunk_id in row_by_id:
            r = row_by_id[chunk_id]
            return Context(
                chunk_id=chunk_id,
                text=r["text"],
                score=score,
                source_path=r["meta"].get("source_path", ""),
                heading_path=r["meta"].get("heading_path", ""),
            )
        ch = chunk_map.get(chunk_id)
        if ch is None:
            return Context(chunk_id=chunk_id, text="", score=score)
        return Context(
            chunk_id=chunk_id,
            text=ch.text,
            score=score,
            source_path=doc_paths.get(ch.doc_id, ""),
            heading_path=ch.section_path,
        )
```

并把 `Context` 类（`retrieve.py` 第 21-26 行）的 docstring 补上量纲说明，替换为：

```python
class Context(BaseModel):
    """一条检索命中。

    score 在 dual（图+向量）模式下是 RRF 融合值，在纯向量模式下是
    1/(1+距离) 相似度——同字段不同量纲，二者都「越大越相关」，仅用于排序。
    """

    chunk_id: str
    text: str
    score: float
    source_path: str = ""
    heading_path: str = ""
```

- [ ] **Step 6: 运行回归确认等价**

Run: `python -m pytest tests/test_graph_store_get_chunks.py tests/test_retrieve_dual.py tests/test_retrieve.py tests/test_engine_dual.py -v`
Expected: PASS（全绿；`test_dual_pulls_graph_only_chunk_with_graph_metadata` 等断言不变）

- [ ] **Step 7: Commit**

```bash
git add src/mdgraph/store/graph_store.py src/mdgraph/retrieve.py tests/test_graph_store_get_chunks.py
git commit -m "$(cat <<'EOF'
feat: batch GraphStore.get_chunks; use it in retrieve._dual (kill N+1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `GraphStore.reclaim_orphans` + `export_graph`

**Files:**
- Modify: `src/mdgraph/store/graph_store.py`（在 `delete_document` 之后加两方法）
- Test: `tests/test_graph_store_reclaim.py`（新）

**Interfaces:**
- Consumes: `NodeType`/`EdgeType`（已 import 于 `graph_store.py`）。
- Produces:
  - `GraphStore.reclaim_orphans() -> int`：删除无 MENTIONS 入边的 ENTITY、无 TAGGED 入边的 TAG，连带删以这些节点为端点的所有边；返回删除的节点数。
  - `GraphStore.export_graph() -> dict`：`{"nodes": [{id,type,meta}], "edges": [{src,dst,type}]}`，确定性排序的全图导出。

- [ ] **Step 1: 写失败测试** — `tests/test_graph_store_reclaim.py`

```python
from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_reclaim_deletes_orphan_entity_and_dangling_relation(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    # e1 有 MENTIONS（来自 chunk c1）→ 保留；e2 无 MENTIONS → 孤儿
    store.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    store.upsert_node(Node(id="e1", type=NodeType.ENTITY))
    store.upsert_node(Node(id="e2", type=NodeType.ENTITY))
    store.upsert_edge(Edge(src="c1", dst="e1", type=EdgeType.MENTIONS))
    store.upsert_edge(Edge(src="e1", dst="e2", type=EdgeType.RELATES_TO))
    n = store.reclaim_orphans()
    assert n == 1
    assert store.get_node("e1") is not None
    assert store.get_node("e2") is None
    # e2 的悬挂 RELATES_TO 也被清掉
    g = store.to_networkx()
    assert not any(k == EdgeType.RELATES_TO.value for _, _, k in g.edges(keys=True))
    store.close()


def test_reclaim_deletes_orphan_tag(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="d1", type=NodeType.DOCUMENT, doc_id="d1"))
    store.upsert_node(Node(id="t_used", type=NodeType.TAG, meta={"name": "used"}))
    store.upsert_node(Node(id="t_orphan", type=NodeType.TAG, meta={"name": "orphan"}))
    store.upsert_edge(Edge(src="d1", dst="t_used", type=EdgeType.TAGGED))
    n = store.reclaim_orphans()
    assert n == 1
    assert store.get_node("t_used") is not None
    assert store.get_node("t_orphan") is None
    store.close()


def test_reclaim_is_idempotent(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="e_orphan", type=NodeType.ENTITY))
    assert store.reclaim_orphans() == 1
    assert store.reclaim_orphans() == 0
    store.close()


def test_export_graph_shape_and_counts(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="b", type=NodeType.CHUNK, doc_id="d1", meta={"k": 1}))
    store.upsert_node(Node(id="a", type=NodeType.DOCUMENT, doc_id="d1"))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    data = store.export_graph()
    assert [n["id"] for n in data["nodes"]] == ["a", "b"]  # 确定性排序
    assert data["nodes"][0]["type"] == NodeType.DOCUMENT.value
    assert data["edges"] == [{"src": "a", "dst": "b", "type": EdgeType.CONTAINS.value}]
    assert len(data["nodes"]) == store.stats()["nodes"]
    store.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_graph_store_reclaim.py -v`
Expected: FAIL（`AttributeError: ... 'reclaim_orphans'`）

- [ ] **Step 3: 实现两方法** — 在 `src/mdgraph/store/graph_store.py` 的 `delete_document` 之后插入：

```python
    def reclaim_orphans(self) -> int:
        """删除无 MENTIONS 入边的 ENTITY 与无 TAGGED 入边的 TAG，连带清除以它们
        为端点的所有边（含悬挂 RELATES_TO）。返回删除的节点数。幂等。"""
        orphans = [
            row["id"]
            for row in self.conn.execute(
                "SELECT id FROM nodes WHERE type = ? "
                "AND id NOT IN (SELECT dst FROM edges WHERE type = ?)",
                (NodeType.ENTITY.value, EdgeType.MENTIONS.value),
            ).fetchall()
        ]
        orphans += [
            row["id"]
            for row in self.conn.execute(
                "SELECT id FROM nodes WHERE type = ? "
                "AND id NOT IN (SELECT dst FROM edges WHERE type = ?)",
                (NodeType.TAG.value, EdgeType.TAGGED.value),
            ).fetchall()
        ]
        if not orphans:
            return 0
        qmarks = ",".join("?" * len(orphans))
        self.conn.execute(f"DELETE FROM nodes WHERE id IN ({qmarks})", orphans)
        self.conn.execute(
            f"DELETE FROM edges WHERE src IN ({qmarks}) OR dst IN ({qmarks})",
            orphans + orphans,
        )
        self.conn.commit()
        return len(orphans)

    def export_graph(self) -> dict:
        """全图导出：{"nodes": [{id,type,meta}], "edges": [{src,dst,type}]}，确定性排序。"""
        nodes = sorted(
            (
                {
                    "id": r["id"],
                    "type": r["type"],
                    "meta": json.loads(r["meta_json"]),
                }
                for r in self.conn.execute("SELECT * FROM nodes").fetchall()
            ),
            key=lambda x: x["id"],
        )
        edges = sorted(
            (
                {"src": r["src"], "dst": r["dst"], "type": r["type"]}
                for r in self.conn.execute("SELECT * FROM edges").fetchall()
            ),
            key=lambda e: (e["src"], e["dst"], e["type"]),
        )
        return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_graph_store_reclaim.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/mdgraph/store/graph_store.py tests/test_graph_store_reclaim.py
git commit -m "$(cat <<'EOF'
feat: GraphStore.reclaim_orphans + export_graph

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 增量索引（indexer 分流 + 末尾回收 + engine 透传）

**Files:**
- Modify: `src/mdgraph/indexer.py`（`IndexReport` 加字段；`index` 加 `incremental` 参数与分流/回收）
- Modify: `src/mdgraph/engine.py`（`build` 透传 `incremental`）
- Test: `tests/test_indexer_incremental.py`（新）；回归全部 `tests/test_indexer_*.py`

**Interfaces:**
- Consumes: `GraphStore.list_documents() -> list[tuple[str,str]]`（`(doc_id, hash)`）、`GraphStore.reclaim_orphans()`、`_DocCtx`（已有：`relpath/did/doc/pd/chunks`，`doc.hash` 为内容哈希）。
- Produces:
  - `IndexReport` 新增 `unchanged: int = 0`、`reclaimed: int = 0`。
  - `StructuralIndexer.index(paths, root=None, max_chars=1200, overlap=150, incremental=True) -> IndexReport`。
  - `MarkdownGraph.build(paths, root=None, max_chars=1200, overlap=150, incremental=True) -> IndexReport`。

- [ ] **Step 1: 写失败测试** — `tests/test_indexer_incremental.py`

```python
from mdgraph.ids import entity_id
from mdgraph.indexer import StructuralIndexer
from mdgraph.providers.mock import MockLLMProvider
from mdgraph.store.graph_store import GraphStore


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_unchanged_doc_is_skipped(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    write(src, "b.md", "# B\n\nbeta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs)
    idx.index([src], root=src)
    # 改 b.md，重建
    write(src, "b.md", "# B\n\nbeta changed\n")
    report = idx.index([src], root=src)
    assert report.indexed == 1     # 只重建 b
    assert report.unchanged == 1   # a 跳过
    gs.close()


def test_full_rebuild_indexes_all(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    write(src, "b.md", "# B\n\nbeta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs)
    idx.index([src], root=src)
    report = idx.index([src], root=src, incremental=False)
    assert report.indexed == 2
    assert report.unchanged == 0
    gs.close()


def test_removing_doc_reclaims_its_orphan_entity(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha here\n")    # 仅此文档提及 Alpha
    write(src, "b.md", "# B\n\nBeta there\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    idx.index([src], root=src)
    assert gs.get_node(entity_id("Alpha")) is not None
    (src / "a.md").unlink()
    report = idx.index([src], root=src)
    assert report.removed == 1
    assert report.reclaimed >= 1
    assert gs.get_node(entity_id("Alpha")) is None  # 孤儿实体被回收
    assert gs.get_node(entity_id("Beta")) is not None
    gs.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_indexer_incremental.py -v`
Expected: FAIL（`test_unchanged_doc_is_skipped`：`report.unchanged` 不存在 / 断言不成立；`incremental` 关键字参数报 `TypeError`）

- [ ] **Step 3: 改 `IndexReport`** — `src/mdgraph/indexer.py` 第 20-28 行，加两字段：

```python
@dataclass
class IndexReport:
    indexed: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    unresolved_links: int = 0
    removed: int = 0
    entities: int = 0
    unchanged: int = 0
    reclaimed: int = 0
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: 改 `index`** — 把 `src/mdgraph/indexer.py` 第 51-114 行的 `index` 方法整体替换为（加 `incremental` 参数、按 hash 分流出 `built`、build/links/embed/extract 仅用 `built`、末尾回收）：

```python
    def index(
        self,
        paths,
        root=None,
        max_chars: int = 1200,
        overlap: int = 150,
        incremental: bool = True,
    ) -> IndexReport:
        report = IndexReport()
        root_path = Path(root).resolve() if root else None
        docs: list[_DocCtx] = []
        self.title_index: dict[str, str] = {}
        self.path_index: dict[str, str] = {}
        self.slug_index: dict[str, dict[str, int]] = {}

        for f in discover(paths):
            relpath = self._relpath(f, root_path)
            try:
                text, h, mtime = read_file(f)
                pd = parse_document(relpath, text)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((str(f), repr(exc)))
                continue
            did = make_doc_id(relpath)
            doc = Document(id=did, path=relpath, hash=h, mtime=mtime, frontmatter=pd.frontmatter)
            chunks = chunk_sections(pd, max_chars=max_chars, overlap=overlap)
            report.warnings.extend(pd.warnings)
            stem = Path(relpath).stem.lower()
            if stem in self.title_index:
                report.warnings.append(f"duplicate title stem: {stem}")
            else:
                self.title_index[stem] = did
            self.path_index[relpath] = did
            self.slug_index[did] = {
                _slug(sec.heading_path.split(SECTION_PATH_SEP)[-1]): sec.sec_idx
                for sec in pd.sections
                if sec.heading_path
            }
            docs.append(_DocCtx(relpath, did, doc, pd, chunks))

        # 按 content-hash 分流：unchanged 跳过，built = new/changed（全量模式下全部）
        stored = dict(self.store.list_documents())
        built: list[_DocCtx] = []
        for ctx in docs:
            if incremental and stored.get(ctx.did) == ctx.doc.hash:
                report.unchanged += 1
            else:
                built.append(ctx)

        # reconcile：用全部 discovered（unchanged 不算 removed）
        discovered = {ctx.did for ctx in docs}
        for stored_id, _ in self.store.list_documents():
            if stored_id not in discovered:
                self._purge_vectors(stored_id)
                self.store.delete_document(stored_id)
                report.removed += 1

        for ctx in built:
            try:
                self._build_doc(ctx, report)
                report.indexed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append((ctx.relpath, repr(exc)))

        # Pass 3: 仅对 built 解析跨文档链接（unchanged doc 的链接原样保留）
        for ctx in built:
            if any(r for r in report.errors if r[0] == ctx.relpath):
                continue
            try:
                with self.store.transaction():
                    chunks_by_sec = self._make_chunks_by_sec(ctx)
                    self._build_links(ctx, chunks_by_sec, report)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((ctx.relpath, repr(exc)))

        if self.vector_store is not None and self.embedder is not None:
            self._embed_and_store(built, report)
        if self.llm is not None:
            self._extract_and_store(built, report)

        # 孤儿回收：在 reconcile + build + extract 之后，确保不误删待重建的实体
        report.reclaimed = self.store.reclaim_orphans()
        return report
```

- [ ] **Step 5: 改 `engine.build` 透传** — `src/mdgraph/engine.py` 第 35-39 行替换为：

```python
    def build(
        self,
        paths,
        root=None,
        max_chars: int = 1200,
        overlap: int = 150,
        incremental: bool = True,
    ) -> IndexReport:
        paths = [Path(p) for p in paths]
        if root is None and len(paths) == 1 and paths[0].is_dir():
            root = paths[0]
        return self.indexer.index(
            paths, root=root, max_chars=max_chars, overlap=overlap, incremental=incremental
        )
```

- [ ] **Step 6: 运行新测试 + 全量索引回归**

Run: `python -m pytest tests/test_indexer_incremental.py tests/test_indexer_structure.py tests/test_indexer_embed.py tests/test_indexer_extract.py tests/test_indexer_links.py -v`
Expected: PASS（新测试 3 个全过；现有 indexer 测试不回归——重 index 测试走 unchanged 路径，`stats`/`vs.count()`/`removed` 断言仍成立）

- [ ] **Step 7: Commit**

```bash
git add src/mdgraph/indexer.py src/mdgraph/engine.py tests/test_indexer_incremental.py
git commit -m "$(cat <<'EOF'
feat: incremental indexing (content-hash skip) + auto orphan reclaim

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: CLI 骨架 + dotted-path 加载 + `index` + `query`

**Files:**
- Create: `src/mdgraph/cli.py`
- Modify: `pyproject.toml`（加 `[project.scripts]`）
- Test: `tests/test_cli.py`（新）

**Interfaces:**
- Consumes: `MarkdownGraph(store_dir, embedder=None, llm=None)`、`.build(paths, incremental=..., max_chars=..., overlap=...)`、`.retrieve(text, k=...)`、`.close()`；`RetrievalResult.model_dump_json()`。
- Produces:
  - `mdgraph.cli.app`（`typer.Typer`）、`mdgraph.cli.main()`（console_scripts 入口）。
  - `mdgraph.cli._load(dotted: str)`：`importlib.import_module(mod)` 后 `getattr(mod, attr)()`，失败抛 `typer.BadParameter`。
  - 命令 `index`、`query`（Task 5 再加 `stats`、`graph export`）。

- [ ] **Step 1: 写失败测试** — `tests/test_cli.py`

```python
import json

from typer.testing import CliRunner

from mdgraph.cli import app

runner = CliRunner()
EMB = "mdgraph.providers.mock:DeterministicEmbeddingProvider"
LLM = "mdgraph.providers.mock:MockLLMProvider"


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_index_then_query(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha topic body\n")
    write(src, "b.md", "# B\n\nbeta topic body\n")
    store = tmp_path / "store"
    r = runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    assert r.exit_code == 0, r.output
    assert "indexed=2" in r.output

    r = runner.invoke(
        app, ["query", "alpha", "--store", str(store), "--embedder", EMB, "-k", "3"]
    )
    assert r.exit_code == 0, r.output
    assert "a.md" in r.output


def test_query_json_output(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    store = tmp_path / "store"
    runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    r = runner.invoke(
        app, ["query", "alpha", "--store", str(store), "--embedder", EMB, "--json"]
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert "contexts" in payload and "subgraph" in payload


def test_query_without_embedder_errors(tmp_path):
    r = runner.invoke(app, ["query", "alpha", "--store", str(tmp_path / "store")])
    assert r.exit_code != 0
    assert "embedder" in r.output.lower()


def test_bad_dotted_path_errors(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nx\n")
    r = runner.invoke(
        app,
        ["index", str(src), "--store", str(tmp_path / "s"), "--embedder", "no.such:Thing"],
    )
    assert r.exit_code != 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mdgraph.cli'`）

- [ ] **Step 3: 实现 `src/mdgraph/cli.py`**（骨架 + `_load` + `index` + `query`）：

```python
"""mdgraph 命令行：index / query / stats / graph export。

provider 无关：embedder/llm 经 dotted-path `pkg.mod:attr` 动态加载，CLI 不绑定
任何具体 provider 实现。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Optional

import typer

from mdgraph.engine import MarkdownGraph

app = typer.Typer(add_completion=False, help="markdown 图谱 + 向量双引擎检索引擎")


def _load(dotted: str):
    """加载 dotted-path `pkg.mod:attr` 指向的 provider 并无参构造。"""
    if ":" not in dotted:
        raise typer.BadParameter(f"provider 须为 'pkg.mod:attr' 形式：{dotted}")
    mod_path, _, attr = dotted.partition(":")
    try:
        obj = getattr(importlib.import_module(mod_path), attr)
    except (ImportError, AttributeError) as exc:
        raise typer.BadParameter(f"无法加载 provider {dotted}: {exc}")
    try:
        return obj()
    except Exception as exc:  # noqa: BLE001
        raise typer.BadParameter(f"构造 provider {dotted} 失败: {exc}")


@app.command()
def index(
    paths: List[Path] = typer.Argument(..., help="markdown 文件或目录"),
    store: Path = typer.Option(Path(".mdgraph"), "--store", help="存储目录"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help="pkg.mod:attr"),
    llm: Optional[str] = typer.Option(None, "--llm", help="pkg.mod:attr"),
    full: bool = typer.Option(False, "--full", help="全量重建（不增量）"),
    max_chars: int = typer.Option(1200, "--max-chars"),
    overlap: int = typer.Option(150, "--overlap"),
) -> None:
    emb = _load(embedder) if embedder else None
    llm_obj = _load(llm) if llm else None
    mg = MarkdownGraph(store, embedder=emb, llm=llm_obj)
    report = mg.build(
        paths, incremental=not full, max_chars=max_chars, overlap=overlap
    )
    typer.echo(
        f"indexed={report.indexed} unchanged={report.unchanged} "
        f"removed={report.removed} reclaimed={report.reclaimed} "
        f"entities={report.entities} errors={len(report.errors)}"
    )
    for path, err in report.errors:
        typer.echo(f"  error: {path}: {err}", err=True)
    mg.close()


@app.command()
def query(
    text: str = typer.Argument(..., help="查询文本"),
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help="pkg.mod:attr"),
    k: int = typer.Option(8, "-k", "--k", help="返回条数"),
    json_out: bool = typer.Option(False, "--json", help="输出完整 JSON"),
) -> None:
    if not embedder:
        typer.echo(
            "query 需要 --embedder pkg.mod:attr 配置 embedding provider", err=True
        )
        raise typer.Exit(code=1)
    emb = _load(embedder)
    mg = MarkdownGraph(store, embedder=emb)
    res = mg.retrieve(text, k=k)
    if json_out:
        typer.echo(res.model_dump_json(indent=2))
    else:
        for c in res.contexts:
            typer.echo(f"[{c.score:.4f}] {c.source_path} :: {c.heading_path}")
            typer.echo(f"    {c.text[:200].replace(chr(10), ' ')}")
    mg.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 加 console_scripts 入口** — `pyproject.toml` 在 `[project]` 表（`dependencies` 之后、`[project.optional-dependencies]` 之前）插入：

```toml
[project.scripts]
mdgraph = "mdgraph.cli:main"
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: Commit**

```bash
git add src/mdgraph/cli.py pyproject.toml tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat: mdgraph CLI (index/query) with dotted-path provider loading

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: CLI `stats` + `graph export` + 端到端集成

**Files:**
- Modify: `src/mdgraph/cli.py`（加 `stats`、`graph export` 子命令）
- Test: `tests/test_cli.py`（追加用例）

**Interfaces:**
- Consumes: `MarkdownGraph.stats() -> dict`、`MarkdownGraph.graph_store`（`GraphStore`）、`GraphStore.expand(seed_ids, hops=...)`、`GraphStore.subgraph(node_ids)`、`GraphStore.export_graph()`。
- Produces: 命令 `stats`、子命令组 `graph` 下的 `export`。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_cli.py` 末尾追加：

```python
def test_stats_command(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    store = tmp_path / "store"
    runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    r = runner.invoke(app, ["stats", "--store", str(store), "--embedder", EMB])
    assert r.exit_code == 0, r.output
    assert "documents:" in r.output
    assert "vectors:" in r.output


def test_graph_export_full_json(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha relates to Beta\n")
    store = tmp_path / "store"
    runner.invoke(
        app, ["index", str(src), "--store", str(store), "--embedder", EMB, "--llm", LLM]
    )
    r = runner.invoke(app, ["graph", "export", "--store", str(store)])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert any(n["type"] == "entity" for n in data["nodes"])


def test_graph_export_to_file_with_seeds(tmp_path):
    from mdgraph.ids import doc_id

    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    store = tmp_path / "store"
    runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    out = tmp_path / "sub.json"
    r = runner.invoke(
        app,
        ["graph", "export", "--store", str(store),
         "--seeds", doc_id("a.md"), "--hops", "2", "-o", str(out)],
    )
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert any(n["id"] == doc_id("a.md") for n in data["nodes"])
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_cli.py -k "stats or graph_export" -v`
Expected: FAIL（`stats` / `graph` 命令不存在，typer 报 `No such command` → exit_code != 0）

- [ ] **Step 3: 实现 `stats` + `graph export`** — 在 `src/mdgraph/cli.py` 的 `query` 命令之后、`def main()` 之前插入：

```python
@app.command()
def stats(
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help="pkg.mod:attr"),
) -> None:
    emb = _load(embedder) if embedder else None
    mg = MarkdownGraph(store, embedder=emb)
    for key, value in mg.stats().items():
        typer.echo(f"{key}: {value}")
    mg.close()


graph_app = typer.Typer(help="图谱导出 / 检查")
app.add_typer(graph_app, name="graph")


@graph_app.command("export")
def graph_export(
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    seeds: Optional[str] = typer.Option(None, "--seeds", help="逗号分隔的种子节点 id"),
    hops: int = typer.Option(2, "--hops"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="写入文件"),
) -> None:
    import json as _json

    mg = MarkdownGraph(store)
    gs = mg.graph_store
    if seeds:
        seed_ids = [s.strip() for s in seeds.split(",") if s.strip()]
        dist = gs.expand(seed_ids, hops=hops)
        data = gs.subgraph(seed_ids + list(dist))
    else:
        data = gs.export_graph()
    text = _json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        output.write_text(text, encoding="utf-8")
        typer.echo(
            f"wrote {len(data['nodes'])} nodes, {len(data['edges'])} edges to {output}"
        )
    else:
        typer.echo(text)
    mg.close()
```

- [ ] **Step 4: 运行新用例**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 全套回归**

Run: `python -m pytest -q`
Expected: PASS（全绿，无回归）

- [ ] **Step 6: Commit**

```bash
git add src/mdgraph/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat: mdgraph CLI stats + graph export

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 任务依赖与顺序

1. **Task 1**（get_chunks + _dual）— 独立。
2. **Task 2**（reclaim_orphans + export_graph）— 独立。
3. **Task 3**（增量 + 回收）— 依赖 Task 2 的 `reclaim_orphans`。
4. **Task 4**（CLI index/query）— 依赖 Task 3 的 `build(incremental=...)`。
5. **Task 5**（CLI stats/graph export）— 依赖 Task 2 的 `export_graph` 与 Task 4 的 CLI 骨架。

按 1→2→3→4→5 顺序执行。

## Self-Review

**1. Spec 覆盖：**
- §3 get_chunks → Task 1 ✓；reclaim_orphans → Task 2 ✓；export_graph → Task 2 ✓；indexer 增量 → Task 3 ✓；`_dual` 批量 → Task 1 ✓；engine 透传 → Task 3 ✓；cli.py → Task 4/5 ✓。
- §5 回收谓词（ENTITY 无 MENTIONS / TAG 无 TAGGED + 连带删边）→ Task 2 实现 + 测试 ✓。
- §6 `_dual` 改写（批量取 chunk + 按 doc_id 去重批量取 document）→ Task 1 Step 5 ✓。
- §7 四命令 + dotted-path 加载 → Task 4/5 ✓；`--store` 默认 `.mdgraph` ✓；`query` 必需 embedder ✓；`graph export` 无 seeds 全图 / 有 seeds expand+subgraph ✓。
- §8 错误处理（dotted-path 失败 → BadParameter、query 无 embedder 退出码非 0）→ Task 4 测试 ✓。
- §9 测试策略 → 各 Task 测试覆盖（get_chunks/reclaim/export/增量/自动回收/_dual 等价/CLI 端到端）✓。
- §2 score docstring → Task 1 Step 5 ✓。

**2. Placeholder 扫描：** 无 TBD/TODO；每个改码步骤都含完整代码块。✓

**3. 类型一致性：**
- `get_chunks(ids: list[str]) -> dict[str, Chunk]` 在 Task 1 定义、Task 1 `_dual` 消费——签名一致 ✓。
- `reclaim_orphans() -> int` Task 2 定义、Task 3 消费 ✓。
- `export_graph() -> dict` Task 2 定义、Task 5 消费 ✓。
- `IndexReport.unchanged/reclaimed` Task 3 定义、Task 4 CLI 读取 ✓。
- `build(..., incremental=True)` Task 3 定义、Task 4 CLI `incremental=not full` 消费 ✓。
- `_load`/`app`/`main` Task 4 定义、Task 5 复用 ✓。
- CLI 用 `List[Path]`/`Optional[str]`（`from typing import`）以兼容 typer 0.9 ✓。
