from mdgraph.engine import MarkdownGraph
from mdgraph.ids import doc_id, tag_id
from mdgraph.models import EdgeType, NodeType


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_build_creates_document_section_chunk_nodes(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n\n## Sub\n\nmore\n")
    store_dir = tmp_path / ".mdgraph"
    mg = MarkdownGraph(store_dir)
    report = mg.build([tmp_path])
    assert report.indexed == 1
    g = mg.graph_store.to_networkx()
    types = sorted({d["type"] for _, d in g.nodes(data=True)})
    assert NodeType.DOCUMENT.value in types
    assert NodeType.SECTION.value in types
    assert NodeType.CHUNK.value in types
    mg.close()


def test_contains_edges_link_doc_section_chunk(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    did = doc_id("a.md")
    contains = edges_of(mg.graph_store, EdgeType.CONTAINS)
    assert (did, f"{did}_s0") in contains
    assert (f"{did}_s0", f"{did}_s0_c0") in contains
    mg.close()


def test_frontmatter_and_inline_tags_create_tagged_edges(tmp_path):
    write(tmp_path, "a.md", "---\ntags:\n  - proj\n---\n# A\n\nhas #inline tag\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    did = doc_id("a.md")
    tagged = edges_of(mg.graph_store, EdgeType.TAGGED)
    assert (did, tag_id("proj")) in tagged
    assert any(v == tag_id("inline") for _, v in tagged)
    mg.close()


def test_rebuild_is_idempotent(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    s1 = mg.stats()
    mg.build([tmp_path])
    s2 = mg.stats()
    assert s1 == s2
    mg.close()


def test_pass2_error_is_isolated_and_reported(tmp_path, monkeypatch):
    write(tmp_path, "good.md", "# G\n\nok\n")
    write(tmp_path, "bad.md", "# B\n\nboom\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    orig = mg.indexer._build_doc

    def maybe_fail(ctx, report):
        if ctx.relpath == "bad.md":
            raise RuntimeError("boom")
        return orig(ctx, report)

    monkeypatch.setattr(mg.indexer, "_build_doc", maybe_fail)
    report = mg.build([tmp_path])
    assert report.indexed == 1
    assert any("bad.md" in e[0] for e in report.errors)
    mg.close()
