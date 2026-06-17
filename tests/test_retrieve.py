from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.retrieve import Context, RetrievalResult, Retriever
from mdgraph.store.vector_store import VectorStore


def make(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    return emb, vs


def test_retrieve_empty_query_returns_empty(tmp_path):
    emb, vs = make(tmp_path)
    res = Retriever(vs, emb).retrieve("   ")
    assert isinstance(res, RetrievalResult)
    assert res.contexts == []


def test_retrieve_empty_index_returns_empty(tmp_path):
    emb, vs = make(tmp_path)
    assert Retriever(vs, emb).retrieve("alpha").contexts == []


def test_retrieve_ranks_closest_first_with_meta(tmp_path):
    emb, vs = make(tmp_path)
    texts = ["alpha alpha", "beta beta", "gamma gamma"]
    metas = [
        {"source_path": "a.md", "heading_path": "A"},
        {"source_path": "b.md", "heading_path": "B"},
        {"source_path": "c.md", "heading_path": "C"},
    ]
    vs.add(["c1", "c2", "c3"], emb.embed(texts), texts, metas)
    res = Retriever(vs, emb).retrieve("beta beta", k=3)
    assert isinstance(res.contexts[0], Context)
    assert res.contexts[0].chunk_id == "c2"
    assert res.contexts[0].source_path == "b.md"
    assert res.contexts[0].heading_path == "B"
    scores = [c.score for c in res.contexts]
    assert scores == sorted(scores, reverse=True)
    assert 0.0 < res.contexts[0].score <= 1.0
    assert res.subgraph == {"nodes": [], "edges": []}


def test_retrieve_exact_match_scores_near_one(tmp_path):
    emb, vs = make(tmp_path)
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{}])
    res = Retriever(vs, emb).retrieve("alpha", k=1)
    assert res.contexts[0].score > 0.99
    assert res.contexts[0].source_path == ""  # empty meta -> default
