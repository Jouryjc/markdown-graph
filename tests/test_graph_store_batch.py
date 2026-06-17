import pytest

from mdgraph.models import Chunk, Document, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_transaction_commits_once_on_success(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    with store.transaction():
        store.upsert_document(
            Document(id="d1", path="a.md", hash="h", mtime=1.0), commit=False
        )
        store.upsert_node(Node(id="n1", type=NodeType.CHUNK, doc_id="d1"), commit=False)
    assert store.get_document("d1") is not None
    assert store.get_node("n1") is not None
    store.close()


def test_transaction_rolls_back_on_exception(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_document(
                Document(id="d1", path="a.md", hash="h", mtime=1.0), commit=False
            )
            raise RuntimeError("boom")
    assert store.get_document("d1") is None
    store.close()


def test_list_chunks_by_doc(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_chunk(Chunk(id="d1_s0_c0", doc_id="d1", section_path="A", text="x", char_start=0, char_end=1))
    store.upsert_chunk(Chunk(id="d1_s0_c1", doc_id="d1", section_path="A", text="y", char_start=1, char_end=2))
    store.upsert_chunk(Chunk(id="d2_s0_c0", doc_id="d2", section_path="B", text="z", char_start=0, char_end=1))
    got = store.list_chunks_by_doc("d1")
    assert [c.id for c in got] == ["d1_s0_c0", "d1_s0_c1"]
    store.close()


def test_list_documents_returns_id_and_hash(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_document(Document(id="d1", path="a.md", hash="h1", mtime=1.0))
    store.upsert_document(Document(id="d2", path="b.md", hash="h2", mtime=1.0))
    assert sorted(store.list_documents()) == [("d1", "h1"), ("d2", "h2")]
    store.close()
