"""GraphStore：SQLite 为真源持久化结构/语义图，NetworkX 做遍历（见后续方法）。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import networkx as nx

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
    def upsert_document(self, doc: Document, commit: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO documents (id, path, hash, mtime, frontmatter_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET path=excluded.path, hash=excluded.hash, "
            "mtime=excluded.mtime, frontmatter_json=excluded.frontmatter_json",
            (doc.id, doc.path, doc.hash, doc.mtime, json.dumps(doc.frontmatter)),
        )
        if commit:
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
    def upsert_node(self, node: Node, commit: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO nodes (id, type, doc_id, meta_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET type=excluded.type, doc_id=excluded.doc_id, "
            "meta_json=excluded.meta_json",
            (node.id, node.type.value, node.doc_id, json.dumps(node.meta)),
        )
        if commit:
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
    def upsert_edge(self, edge: Edge, commit: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO edges (src, dst, type, weight, meta_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(src, dst, type) DO UPDATE SET weight=excluded.weight, "
            "meta_json=excluded.meta_json",
            (edge.src, edge.dst, edge.type.value, edge.weight, json.dumps(edge.meta)),
        )
        if commit:
            self.conn.commit()

    # --- chunks ---
    def upsert_chunk(self, chunk: Chunk, commit: bool = True) -> None:
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
        if commit:
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

    def delete_document(self, doc_id: str, commit: bool = True) -> None:
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
        if commit:
            self.conn.commit()

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

    def expand(
        self,
        seed_ids: list[str],
        edge_types: list[EdgeType] | None = None,
        hops: int = 1,
    ) -> dict[str, int]:
        """多源无向 BFS：一次建图，从所有种子一起扩 hops 跳。

        返回 {node_id: 最小跳距}，不含种子自身，忽略不在图中的种子。
        """
        g = self.to_networkx()
        allowed = {e.value for e in edge_types} if edge_types else None
        frontier = {s for s in seed_ids if s in g}
        visited = set(frontier)
        dist: dict[str, int] = {}
        for h in range(1, hops + 1):
            nxt: set[str] = set()
            for n in frontier:
                for _, d, key in g.out_edges(n, keys=True):
                    if (allowed is None or key in allowed) and d not in visited:
                        nxt.add(d)
                for s, _, key in g.in_edges(n, keys=True):
                    if (allowed is None or key in allowed) and s not in visited:
                        nxt.add(s)
            for node in nxt:
                dist[node] = h
            visited |= nxt
            frontier = nxt
        return dist

    @contextmanager
    def transaction(self):
        """批量写：块内用 commit=False，退出时一次提交；异常回滚。"""
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def list_chunks_by_doc(self, doc_id: str) -> list[Chunk]:
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY id", (doc_id,)
        ).fetchall()
        return [
            Chunk(
                id=r["id"],
                doc_id=r["doc_id"],
                section_path=r["section_path"],
                text=r["text"],
                char_start=r["char_start"],
                char_end=r["char_end"],
            )
            for r in rows
        ]

    def list_documents(self) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT id, hash FROM documents ORDER BY id"
        ).fetchall()
        return [(r["id"], r["hash"]) for r in rows]

    def stats(self) -> dict[str, int]:
        return {
            "documents": self.conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0],
            "nodes": self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "chunks": self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
