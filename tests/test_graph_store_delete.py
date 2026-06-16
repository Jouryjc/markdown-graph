from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def seed(store):
    # 文档 d1：含一个章节节点 s1、一个块 c1，块指向另一文档 d2 的链接边
    store.upsert_document(Document(id="d1", path="/a.md", hash="h1", mtime=1.0))
    store.upsert_node(Node(id="s1", type=NodeType.SECTION, doc_id="d1"))
    store.upsert_chunk(
        Chunk(id="c1", doc_id="d1", section_path="H1", text="x", char_start=0, char_end=1)
    )
    store.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    store.upsert_edge(Edge(src="d1", dst="s1", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="c1", dst="d2", type=EdgeType.LINKS_TO))


def test_delete_document_cascades(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    seed(store)
    store.delete_document("d1")
    s = store.stats()
    assert s["documents"] == 0
    assert s["nodes"] == 0  # s1、c1 节点随 doc_id=d1 一并删除
    assert s["chunks"] == 0
    assert s["edges"] == 0  # CONTAINS 与 LINKS_TO（src 在 d1 内）都被清理
    store.close()


def test_delete_document_only_affects_target(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    seed(store)
    store.upsert_document(Document(id="dX", path="/x.md", hash="hx", mtime=1.0))
    store.upsert_node(Node(id="nX", type=NodeType.CHUNK, doc_id="dX"))
    store.delete_document("d1")
    assert store.get_document("dX") is not None
    assert store.get_node("nX") is not None
    store.close()
