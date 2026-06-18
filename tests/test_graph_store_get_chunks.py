from mdgraph.models import Chunk
from mdgraph.store.graph_store import GraphStore


def _mk(store, cid, doc="d1", text="x"):
    store.upsert_chunk(
        Chunk(id=cid, doc_id=doc, section_path="A", text=text, char_start=0, char_end=1)
    )


def test_get_chunks_returns_map(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    _mk(store, "c1", text="alpha")
    _mk(store, "c2", text="beta")
    got = store.get_chunks(["c1", "c2"])
    assert set(got) == {"c1", "c2"}
    assert got["c1"].text == "alpha"
    assert got["c2"].text == "beta"
    store.close()


def test_get_chunks_skips_missing_ids(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    _mk(store, "c1")
    got = store.get_chunks(["c1", "nope"])
    assert set(got) == {"c1"}
    store.close()


def test_get_chunks_empty(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    assert store.get_chunks([]) == {}
    store.close()
