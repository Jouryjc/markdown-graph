from mdgraph.ids import entity_id
from mdgraph.indexer import StructuralIndexer
from mdgraph.models import EdgeType, NodeType
from mdgraph.providers.mock import MockLLMProvider
from mdgraph.store.graph_store import GraphStore


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def test_extract_builds_entities_and_edges(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha relates to Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    report = idx.index([src], root=src)
    g = gs.to_networkx()
    ent = {n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value}
    assert entity_id("Alpha") in ent
    assert entity_id("Beta") in ent
    assert report.entities >= 2
    mentions = edges_of(gs, EdgeType.MENTIONS)
    assert any(v == entity_id("Alpha") for _, v in mentions)
    assert (entity_id("Alpha"), entity_id("Beta")) in edges_of(gs, EdgeType.RELATES_TO)
    gs.close()


def test_same_entity_two_docs_one_node_two_mentions(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha here\n")
    write(src, "b.md", "# B\n\nAlpha there\n")
    gs = GraphStore(tmp_path / "g.db")
    StructuralIndexer(gs, llm=MockLLMProvider()).index([src], root=src)
    g = gs.to_networkx()
    alpha = entity_id("Alpha")
    assert alpha in g
    to_alpha = [
        (u, v)
        for u, v, k in g.edges(keys=True)
        if k == EdgeType.MENTIONS.value and v == alpha
    ]
    assert len(to_alpha) == 2
    gs.close()


def test_rebuild_idempotent_with_llm(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha relates to Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    idx.index([src], root=src)
    s1 = gs.stats()
    idx.index([src], root=src)
    s2 = gs.stats()
    assert s1 == s2
    gs.close()


def test_no_llm_no_entities(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nAlpha Beta\n")
    gs = GraphStore(tmp_path / "g.db")
    StructuralIndexer(gs).index([src], root=src)  # no llm
    g = gs.to_networkx()
    ent = [n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value]
    assert ent == []
    gs.close()


def test_extract_skip_errored_doc_is_warned(tmp_path, monkeypatch):
    src = tmp_path / "src"
    write(src, "good.md", "# G\n\nAlpha here\n")
    write(src, "bad.md", "# B\n\nBeta there\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs, llm=MockLLMProvider())
    orig = idx._build_doc

    def maybe_fail(ctx, report):
        if ctx.relpath == "bad.md":
            raise RuntimeError("boom")
        return orig(ctx, report)

    monkeypatch.setattr(idx, "_build_doc", maybe_fail)
    report = idx.index([src], root=src)
    assert any("bad.md" in e[0] for e in report.errors)
    assert any("bad.md" in w and "extraction" in w for w in report.warnings)
    gs.close()
