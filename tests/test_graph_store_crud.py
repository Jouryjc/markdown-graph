from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def make_store(tmp_path):
    return GraphStore(tmp_path / "graph.db")


def test_document_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    doc = Document(id="d1", path="/a.md", hash="h1", mtime=1.5, frontmatter={"title": "A"})
    store.upsert_document(doc)
    got = store.get_document("d1")
    assert got is not None
    assert got.path == "/a.md"
    assert got.frontmatter == {"title": "A"}
    store.close()


def test_document_upsert_is_idempotent_update(tmp_path):
    store = make_store(tmp_path)
    store.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    store.upsert_document(Document(id="d1", path="/a.md", hash="h2", mtime=2.0))
    got = store.get_document("d1")
    assert got.hash == "h2"
    assert store.stats()["documents"] == 1
    store.close()


def test_node_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    store.upsert_node(Node(id="n1", type=NodeType.ENTITY, meta={"name": "X"}))
    got = store.get_node("n1")
    assert got.type is NodeType.ENTITY
    assert got.meta["name"] == "X"
    store.close()


def test_chunk_upsert_and_get(tmp_path):
    store = make_store(tmp_path)
    store.upsert_chunk(
        Chunk(id="c1", doc_id="d1", section_path="H1", text="hi", char_start=0, char_end=2)
    )
    got = store.get_chunk("c1")
    assert got.text == "hi"
    assert got.char_end == 2
    store.close()


def test_edge_upsert_idempotent(tmp_path):
    store = make_store(tmp_path)
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.LINKS_TO, weight=1.0))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.LINKS_TO, weight=2.0))
    assert store.stats()["edges"] == 1
    store.close()


def test_get_missing_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.get_document("nope") is None
    assert store.get_node("nope") is None
    assert store.get_chunk("nope") is None
    store.close()


def test_persists_across_reopen(tmp_path):
    db = tmp_path / "graph.db"
    s1 = GraphStore(db)
    s1.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    s1.close()
    s2 = GraphStore(db)
    assert s2.get_document("d1") is not None
    s2.close()
