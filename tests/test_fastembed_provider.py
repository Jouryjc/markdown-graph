from mdgraph.providers.fastembed_embedder import FastEmbedProvider


class _FakeModel:
    """模拟 fastembed.TextEmbedding：embed 返回 generator，每条 4 维。"""
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        return (([0.1, 0.2, 0.3, 0.4]) for _ in texts)


def test_dim_probed_from_model():
    p = FastEmbedProvider(model_name="BAAI/bge-small-zh-v1.5", model=_FakeModel())
    assert p.dim == 4  # 探针 embed(["x"]) 测出


def test_name_sanitized_for_table_versioning():
    p = FastEmbedProvider(model_name="BAAI/bge-small-zh-v1.5", model=_FakeModel())
    assert p.name == "BAAI_bge-small-zh-v1.5"  # 斜杠清洗，VectorStore 表名安全


def test_embed_returns_list_of_float_lists():
    p = FastEmbedProvider(model_name="m", model=_FakeModel())
    vecs = p.embed(["a", "b"])
    assert vecs == [[0.1, 0.2, 0.3, 0.4], [0.1, 0.2, 0.3, 0.4]]
    assert all(isinstance(x, float) for x in vecs[0])  # generator→list、float 转换


def test_embed_empty():
    p = FastEmbedProvider(model_name="m", model=_FakeModel())
    assert p.embed([]) == []
