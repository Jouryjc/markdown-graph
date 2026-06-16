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

    def stats(self) -> dict[str, int]:
        return {
            "documents": self.conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0],
            "nodes": self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "chunks": self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
