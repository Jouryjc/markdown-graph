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
