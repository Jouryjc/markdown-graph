from mdgraph.engine import MarkdownGraph
from mdgraph.ids import doc_id, section_id
from mdgraph.models import EdgeType, NodeType


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_wiki_link_resolves_to_target_document(tmp_path):
    write(tmp_path, "a.md", "# A\n\nlink to [[b]]\n")
    write(tmp_path, "b.md", "# B\n\nhi\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    bdid = doc_id("b.md")
    assert any(v == bdid for _, v in links)
    mg.close()


def test_md_relative_link_resolves(tmp_path):
    write(tmp_path, "a.md", "# A\n\nsee [b](sub/b.md)\n")
    write(tmp_path, "sub/b.md", "# B\n\nhi\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    assert any(v == doc_id("sub/b.md") for _, v in links)
    mg.close()


def test_anchor_link_resolves_to_section(tmp_path):
    write(tmp_path, "a.md", "# A\n\ngo [[b#Details]]\n")
    write(tmp_path, "b.md", "# B\n\nintro\n\n## Details\n\ndeep\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    bdid = doc_id("b.md")
    assert any(v == section_id(bdid, 1) for _, v in links)
    mg.close()


def test_dangling_link_recorded_in_meta_not_edge(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbroken [[Nonexistent]]\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    report = mg.build([tmp_path])
    assert report.unresolved_links == 1
    links = edges_of(mg.graph_store, EdgeType.LINKS_TO)
    assert links == set()
    g = mg.graph_store.to_networkx()
    metas = [d["meta"].get("unresolved_links") for _, d in g.nodes(data=True) if d["type"] == NodeType.CHUNK.value]
    assert any(m and "[[Nonexistent]]" in m for m in metas)
    mg.close()
