import pytest

from mdgraph.embed import embed_texts
from mdgraph.providers.mock import DeterministicEmbeddingProvider


class CountingEmbedder(DeterministicEmbeddingProvider):
    def __init__(self, dim=8):
        super().__init__(dim=dim)
        self.batch_sizes = []

    def embed(self, texts):
        self.batch_sizes.append(len(texts))
        return super().embed(texts)


def test_embed_texts_empty_returns_empty():
    emb = DeterministicEmbeddingProvider(dim=8)
    assert embed_texts(emb, []) == []


def test_embed_texts_splits_into_batches():
    emb = CountingEmbedder(dim=8)
    texts = [f"t{i}" for i in range(10)]
    vecs = embed_texts(emb, texts, batch_size=4)
    assert len(vecs) == 10
    assert all(len(v) == 8 for v in vecs)
    assert emb.batch_sizes == [4, 4, 2]


def test_embed_texts_preserves_order():
    emb = DeterministicEmbeddingProvider(dim=8)
    texts = ["alpha", "beta", "gamma"]
    assert embed_texts(emb, texts, batch_size=1) == emb.embed(texts)


def test_embed_texts_rejects_bad_batch_size():
    emb = DeterministicEmbeddingProvider(dim=8)
    with pytest.raises(ValueError):
        embed_texts(emb, ["a"], batch_size=0)
