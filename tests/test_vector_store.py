from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.store.vector_store import VectorStore


def make_store(tmp_path, dim=16):
    return VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=dim)


def test_table_name_is_versioned_by_model_and_dim(tmp_path):
    store = make_store(tmp_path)
    assert store.table_name == "vectors_mock_embed_16"
    store.close()


def test_add_and_count(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta", "gamma"]
    vecs = emb.embed(texts)
    store.add(["c1", "c2", "c3"], vecs, texts)
    assert store.count() == 3
    store.close()


def test_search_returns_closest_first(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta", "gamma"]
    vecs = emb.embed(texts)
    store.add(["c1", "c2", "c3"], vecs, texts)
    # 用 "beta" 的向量查询，最近的应是 c2
    query = emb.embed(["beta"])[0]
    results = store.search(query, k=3)
    assert results[0]["chunk_id"] == "c2"
    assert len(results) == 3
    assert "distance" in results[0]
    assert "score" not in results[0]
    store.close()


def test_delete_removes_rows(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta"]
    store.add(["c1", "c2"], emb.embed(texts), texts)
    store.delete(["c1"])
    assert store.count() == 1
    remaining = [r["chunk_id"] for r in store.search(emb.embed(["beta"])[0], k=5)]
    assert "c1" not in remaining
    store.close()


def test_empty_add_is_noop(tmp_path):
    store = make_store(tmp_path)
    store.add([], [], [])
    assert store.count() == 0
    store.close()


def test_reopen_keeps_data(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    s1 = VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=16)
    s1.add(["c1"], emb.embed(["alpha"]), ["alpha"])
    s1.close()
    s2 = VectorStore(tmp_path / "vectors", model_name="mock-embed", dim=16)
    assert s2.count() == 1
    s2.close()


def test_add_with_meta_roundtrips_in_search(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    texts = ["alpha", "beta"]
    metas = [{"source_path": "/a.md", "heading_path": "H1"}, {"source_path": "/b.md"}]
    store.add(["c1", "c2"], emb.embed(texts), texts, metas)
    results = store.search(emb.embed(["alpha"])[0], k=2)
    top = results[0]
    assert top["chunk_id"] == "c1"
    assert top["meta"] == {"source_path": "/a.md", "heading_path": "H1"}
    store.close()


def test_add_without_meta_defaults_to_empty_dict(tmp_path):
    store = make_store(tmp_path)
    emb = DeterministicEmbeddingProvider(dim=16)
    store.add(["c1"], emb.embed(["alpha"]), ["alpha"])
    results = store.search(emb.embed(["alpha"])[0], k=1)
    assert results[0]["meta"] == {}
    store.close()
