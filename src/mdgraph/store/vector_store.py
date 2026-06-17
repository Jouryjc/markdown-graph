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
        existing = self.db.list_tables()
        table_list = existing.tables if hasattr(existing, "tables") else list(existing)
        if self.table_name in table_list:
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
