"""SAGStore：独立 sqlite(store_dir/sag.db) 持久化事件/实体双层与联结表。

镜像 graph_store.py 风格（sqlite3、row_factory=Row、executescript(SCHEMA)、transaction() ctx、
commit 参数）。与 dual/vector/file 的 graph.db 完全隔离。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sag_events (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    embedding_json TEXT,
    rank INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sag_entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sag_event_entities (
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    PRIMARY KEY (event_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_sag_events_chunk ON sag_events(chunk_id);
CREATE INDEX IF NOT EXISTS idx_sag_ee_entity ON sag_event_entities(entity_id, event_id);
CREATE INDEX IF NOT EXISTS idx_sag_ee_event ON sag_event_entities(event_id, entity_id);
CREATE INDEX IF NOT EXISTS idx_sag_entities_norm ON sag_entities(normalized_name);
"""


class SAGStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        """批量写：块内用 commit=False，退出时一次提交；异常回滚。"""
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def clear(self, commit: bool = True) -> None:
        """删除三表全部行（full 重建用）。"""
        self.conn.execute("DELETE FROM sag_event_entities")
        self.conn.execute("DELETE FROM sag_entities")
        self.conn.execute("DELETE FROM sag_events")
        if commit:
            self.conn.commit()

    def delete_event_by_chunk(self, chunk_id: str, commit: bool = True) -> None:
        """删该 chunk 的 event 及其在 sag_event_entities 的链接（按 event_id）。

        孤立 entity 不必即时回收（查询只看有链接的）。
        """
        ev_ids = [
            row["id"]
            for row in self.conn.execute(
                "SELECT id FROM sag_events WHERE chunk_id = ?", (chunk_id,)
            ).fetchall()
        ]
        for ev_id in ev_ids:
            self.conn.execute(
                "DELETE FROM sag_event_entities WHERE event_id = ?", (ev_id,)
            )
        self.conn.execute("DELETE FROM sag_events WHERE chunk_id = ?", (chunk_id,))
        if commit:
            self.conn.commit()

    def upsert_event(
        self,
        *,
        id: str,
        doc_id: str,
        chunk_id: str,
        title: str,
        summary: str,
        content: str,
        category: str,
        keywords: list[str],
        embedding: list[float] | None,
        rank: int = 0,
        commit: bool = True,
    ) -> None:
        self.conn.execute(
            "INSERT INTO sag_events "
            "(id, doc_id, chunk_id, title, summary, content, category, "
            "keywords_json, embedding_json, rank) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET doc_id=excluded.doc_id, "
            "chunk_id=excluded.chunk_id, title=excluded.title, "
            "summary=excluded.summary, content=excluded.content, "
            "category=excluded.category, keywords_json=excluded.keywords_json, "
            "embedding_json=excluded.embedding_json, rank=excluded.rank",
            (
                id,
                doc_id,
                chunk_id,
                title,
                summary,
                content,
                category,
                json.dumps(keywords),
                json.dumps(embedding) if embedding is not None else None,
                rank,
            ),
        )
        if commit:
            self.conn.commit()

    def upsert_entity(
        self,
        *,
        id: str,
        type: str,
        name: str,
        normalized_name: str,
        description: str,
        commit: bool = True,
    ) -> None:
        """ON CONFLICT(id) 仅在原值为空时补 type/description（去重合并，类似 extract.py）。"""
        self.conn.execute(
            "INSERT INTO sag_entities (id, type, name, normalized_name, description) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "type=CASE WHEN sag_entities.type = '' THEN excluded.type "
            "ELSE sag_entities.type END, "
            "description=CASE WHEN sag_entities.description = '' "
            "THEN excluded.description ELSE sag_entities.description END",
            (id, type, name, normalized_name, description),
        )
        if commit:
            self.conn.commit()

    def link(self, event_id: str, entity_id: str, commit: bool = True) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO sag_event_entities (event_id, entity_id) "
            "VALUES (?, ?)",
            (event_id, entity_id),
        )
        if commit:
            self.conn.commit()

    def counts(self) -> dict:
        return {
            "events": self.conn.execute(
                "SELECT COUNT(*) FROM sag_events"
            ).fetchone()[0],
            "entities": self.conn.execute(
                "SELECT COUNT(*) FROM sag_entities"
            ).fetchone()[0],
            "links": self.conn.execute(
                "SELECT COUNT(*) FROM sag_event_entities"
            ).fetchone()[0],
        }

    def match_entities_by_name(self, tokens: list[str], limit: int = 50) -> list[dict]:
        """对每个 token 做 normalized_name LIKE %tok%，合并去重（embedder-free 种子匹配）。

        返回 [{id,name,type,normalized_name}]，按 id 排序确定性，截到 limit。
        """
        tokens = [t for t in tokens if t]
        if not tokens:
            return []
        seen: dict[str, dict] = {}
        for tok in tokens:
            rows = self.conn.execute(
                "SELECT id, name, type, normalized_name FROM sag_entities "
                "WHERE normalized_name LIKE ?",
                (f"%{tok}%",),
            ).fetchall()
            for r in rows:
                if r["id"] not in seen:
                    seen[r["id"]] = {
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "normalized_name": r["normalized_name"],
                    }
        out = sorted(seen.values(), key=lambda e: e["id"])
        return out[:limit]

    def event_ids_for_entities(
        self, entity_ids: list[str], exclude: set[str] | None = None
    ) -> list[str]:
        """JOIN sag_event_entities，去重、排除 exclude，按 event_id 排序。"""
        entity_ids = list(entity_ids)
        if not entity_ids:
            return []
        exclude = exclude or set()
        qmarks = ",".join("?" * len(entity_ids))
        rows = self.conn.execute(
            f"SELECT DISTINCT event_id FROM sag_event_entities "
            f"WHERE entity_id IN ({qmarks})",
            entity_ids,
        ).fetchall()
        return sorted(r["event_id"] for r in rows if r["event_id"] not in exclude)

    def entity_ids_for_events(self, event_ids: list[str]) -> dict[str, list[str]]:
        """每 event 的 entity_id 列表（确定性排序）。"""
        event_ids = list(event_ids)
        if not event_ids:
            return {}
        qmarks = ",".join("?" * len(event_ids))
        rows = self.conn.execute(
            f"SELECT event_id, entity_id FROM sag_event_entities "
            f"WHERE event_id IN ({qmarks}) ORDER BY event_id, entity_id",
            event_ids,
        ).fetchall()
        out: dict[str, list[str]] = {eid: [] for eid in event_ids}
        for r in rows:
            out[r["event_id"]].append(r["entity_id"])
        return out

    def events_by_ids(self, ids: list[str]) -> dict[str, dict]:
        """批量取 event 行（含 keywords 解析、embedding 解析）。"""
        ids = list(ids)
        if not ids:
            return {}
        qmarks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM sag_events WHERE id IN ({qmarks})", ids
        ).fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            out[r["id"]] = {
                "id": r["id"],
                "doc_id": r["doc_id"],
                "chunk_id": r["chunk_id"],
                "title": r["title"],
                "summary": r["summary"],
                "content": r["content"],
                "category": r["category"],
                "keywords": json.loads(r["keywords_json"]),
                "embedding": (
                    json.loads(r["embedding_json"])
                    if r["embedding_json"] is not None
                    else None
                ),
                "rank": r["rank"],
            }
        return out

    def entities_by_ids(self, ids: list[str]) -> dict[str, dict]:
        """批量取 entity 行。"""
        ids = list(ids)
        if not ids:
            return {}
        qmarks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM sag_entities WHERE id IN ({qmarks})", ids
        ).fetchall()
        return {
            r["id"]: {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "normalized_name": r["normalized_name"],
                "description": r["description"],
            }
            for r in rows
        }

    def iter_event_embeddings(self) -> list[tuple[str, list[float]]]:
        """有 embedding 的 (event_id, vec)。"""
        rows = self.conn.execute(
            "SELECT id, embedding_json FROM sag_events "
            "WHERE embedding_json IS NOT NULL ORDER BY id"
        ).fetchall()
        return [(r["id"], json.loads(r["embedding_json"])) for r in rows]

    def all_event_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT id FROM sag_events ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]
