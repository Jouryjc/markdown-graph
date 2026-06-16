from mdgraph.models import (
    NodeType,
    EdgeType,
    Document,
    Chunk,
    Node,
    Edge,
)


def test_enums_have_expected_values():
    assert NodeType.DOCUMENT.value == "document"
    assert NodeType.CHUNK.value == "chunk"
    assert EdgeType.LINKS_TO.value == "links_to"
    assert EdgeType.MENTIONS.value == "mentions"


def test_document_defaults_frontmatter_to_empty_dict():
    doc = Document(id="d1", path="/a.md", hash="abc", mtime=1.0)
    assert doc.frontmatter == {}


def test_chunk_roundtrip_fields():
    c = Chunk(
        id="c1",
        doc_id="d1",
        section_path="H1>H2",
        text="hello",
        char_start=0,
        char_end=5,
    )
    assert c.doc_id == "d1"
    assert c.char_end == 5


def test_node_and_edge_construct():
    n = Node(id="n1", type=NodeType.ENTITY, doc_id=None, meta={"name": "X"})
    e = Edge(src="a", dst="b", type=EdgeType.RELATES_TO, weight=0.5)
    assert n.type is NodeType.ENTITY
    assert n.meta["name"] == "X"
    assert e.weight == 0.5
    assert e.meta == {}
