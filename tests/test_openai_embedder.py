from mdgraph.providers.openai_embedder import OpenAIEmbeddingProvider


# --- fake openai client：embeddings.create(model=, input=) -> resp.data[i].embedding ---
class _Item:
    def __init__(self, emb):
        self.embedding = emb


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    """每条文本回一个可区分的向量：[float(idx), 0.0, 0.0, 0.0]（idx 跨调用全局递增）。

    这样能断言批处理后拼接顺序与输入一致。
    """

    def __init__(self, dim=4):
        self.dim = dim
        self.calls = []
        self._counter = 0

    def create(self, model, input):
        items = []
        for _ in input:
            vec = [float(self._counter)] + [0.0] * (self.dim - 1)
            items.append(_Item(vec))
            self._counter += 1
        self.calls.append({"model": model, "input": list(input)})
        return _Resp(items)


class _FakeClient:
    def __init__(self, dim=4):
        self.embeddings = _FakeEmbeddings(dim)


def test_dim_probed_from_model():
    p = OpenAIEmbeddingProvider(client=_FakeClient(dim=4))
    assert p.dim == 4  # 探针 embed(["x"]) 测出


def test_name_sanitization():
    assert OpenAIEmbeddingProvider(model="nomic-embed-text", client=_FakeClient()).name == "nomic-embed-text"
    assert OpenAIEmbeddingProvider(model="BAAI/bge-m3", client=_FakeClient()).name == "BAAI_bge-m3"
    assert (
        OpenAIEmbeddingProvider(model="text-embedding-3-small", client=_FakeClient()).name
        == "text-embedding-3-small"
    )
    assert OpenAIEmbeddingProvider(model="qwen:0.5b", client=_FakeClient()).name == "qwen_0.5b"


def test_embed_returns_float_lists_matching_input_length():
    p = OpenAIEmbeddingProvider(client=_FakeClient(dim=4))
    vecs = p.embed(["a", "b", "c"])
    assert len(vecs) == 3
    assert all(isinstance(x, float) for v in vecs for x in v)
    assert all(len(v) == 4 for v in vecs)


def test_embed_model_passed_to_create():
    client = _FakeClient(dim=4)
    p = OpenAIEmbeddingProvider(model="my-model", client=client)
    p.embed(["x"])
    assert all(c["model"] == "my-model" for c in client.embeddings.calls)


def test_batching_across_boundary_and_order():
    # batch_size=2、5 条 → 3 次 create（2/2/1），返回顺序与输入一致。
    client = _FakeClient(dim=4)
    p = OpenAIEmbeddingProvider(client=client, batch_size=2)
    # 构造时探针消耗一条（counter 0 -> 1），重置计数器以便干净断言批处理。
    client.embeddings.calls.clear()
    client.embeddings._counter = 0
    vecs = p.embed(["t0", "t1", "t2", "t3", "t4"])
    # 3 次调用，分块大小 2/2/1
    assert [len(c["input"]) for c in client.embeddings.calls] == [2, 2, 1]
    # 第一维携带全局递增计数器 → 验证拼接顺序与输入一致
    assert [v[0] for v in vecs] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_batching_3_inputs_batch_size_2():
    client = _FakeClient(dim=4)
    p = OpenAIEmbeddingProvider(client=client, batch_size=2)
    client.embeddings.calls.clear()
    vecs = p.embed(["a", "b", "c"])
    assert len(client.embeddings.calls) == 2  # 2 次 create（2 + 1）
    assert len(vecs) == 3


def test_empty_input_returns_empty_no_create():
    client = _FakeClient(dim=4)
    p = OpenAIEmbeddingProvider(client=client)
    client.embeddings.calls.clear()
    assert p.embed([]) == []
    assert client.embeddings.calls == []  # 空输入不调用 create


# --- env 注入：monkeypatch openai.OpenAI 捕获 kwargs（同 LLM 测试，不真连） ---
def test_default_endpoint_and_model(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)
            self.embeddings = _FakeEmbeddings(dim=4)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    for k in ("MDGRAPH_EMBED_BASE_URL", "MDGRAPH_EMBED_API_KEY", "MDGRAPH_EMBED_MODEL"):
        monkeypatch.delenv(k, raising=False)
    p = OpenAIEmbeddingProvider()
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"
    assert p._model == "nomic-embed-text"


def test_env_overrides(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)
            self.embeddings = _FakeEmbeddings(dim=4)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setenv("MDGRAPH_EMBED_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("MDGRAPH_EMBED_API_KEY", "sk-test")
    monkeypatch.setenv("MDGRAPH_EMBED_MODEL", "text-embedding-3-small")
    p = OpenAIEmbeddingProvider()
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["api_key"] == "sk-test"
    assert p._model == "text-embedding-3-small"
