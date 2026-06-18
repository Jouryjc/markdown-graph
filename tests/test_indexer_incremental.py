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
    assert report.removed == 0
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
    assert report.reclaimed == 0
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


def test_incremental_shared_entity_meta_is_lossy_known_boundary(tmp_path):
    """已知增量边界（非缺陷，见 spec §4）：只改裸提及某实体的文档时，
    增量重抽取会把该实体来自未变更文档的富 meta 覆盖为裸值。--full 可恢复。"""
    from mdgraph.ids import entity_id
    from mdgraph.providers.base import ExtractedEntity, ExtractionResult

    class _RichLLM:
        # text 含 "RICH" → 富 Alpha；否则裸 Alpha
        def extract(self, text):
            if "RICH" in text:
                return ExtractionResult(
                    entities=[ExtractedEntity(name="Alpha", type="person", description="canonical")]
                )
            return ExtractionResult(entities=[ExtractedEntity(name="Alpha")])

    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nRICH alpha source\n")   # 富 meta 来源
    write(src, "b.md", "# B\n\nplain alpha\n")          # 裸提及
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=_RichLLM())
    idx.index([src], root=src)
    alpha = entity_id("Alpha")
    assert gs.get_node(alpha).meta["description"] == "canonical"  # 初次富 meta

    # 只改 b.md（a.md 不变）→ 增量只重抽 b.md → Alpha meta 被覆盖为裸值
    write(src, "b.md", "# B\n\nplain alpha changed\n")
    idx.index([src], root=src)
    assert gs.get_node(alpha).meta["description"] == ""  # 降级（已知边界）

    # --full 全量重建恢复富 meta
    idx.index([src], root=src, incremental=False)
    assert gs.get_node(alpha).meta["description"] == "canonical"
    gs.close()
