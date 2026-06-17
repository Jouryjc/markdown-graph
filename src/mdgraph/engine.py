"""MarkdownGraph：结构索引门面（检索能力在后续切片扩展）。"""

from __future__ import annotations

from pathlib import Path

from mdgraph.indexer import IndexReport, StructuralIndexer
from mdgraph.store.graph_store import GraphStore


class MarkdownGraph:
    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.graph_store = GraphStore(self.store_dir / "graph.db")
        self.indexer = StructuralIndexer(self.graph_store)

    def build(self, paths, root=None, max_chars: int = 1200, overlap: int = 150) -> IndexReport:
        paths = [Path(p) for p in paths]
        if root is None and len(paths) == 1 and paths[0].is_dir():
            root = paths[0]
        return self.indexer.index(paths, root=root, max_chars=max_chars, overlap=overlap)

    def stats(self) -> dict[str, int]:
        return self.graph_store.stats()

    def close(self) -> None:
        self.graph_store.close()
