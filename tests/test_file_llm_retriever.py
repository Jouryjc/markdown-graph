import json

from mdgraph.providers.file_llm_retriever import (
    FileLLMRetriever,
    _extract_json_array,
    _first_balanced_array,
)


# --- fake openai client（chat.completions.create -> resp.choices[0].message.content）---
class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, contents=None, exc=None):
        # contents: 每次 create 返回的内容（按批次顺序）；单值则每次都返回它
        self._contents = contents
        self._exc = exc
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        if isinstance(self._contents, list):
            idx = len(self.calls) - 1
            content = self._contents[idx] if idx < len(self._contents) else "[]"
        else:
            content = self._contents
        return _Resp(content)


class _FakeClient:
    def __init__(self, contents=None, exc=None):
        self.completions = _FakeCompletions(contents, exc)
        self.chat = type("Chat", (), {"completions": self.completions})()


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


# --- _extract_json_array / _first_balanced_array ---
def test_extract_json_array_bare():
    assert _extract_json_array('[{"path":"a.md","snippet":"x"}]') == [
        {"path": "a.md", "snippet": "x"}
    ]


def test_extract_json_array_fenced():
    assert _extract_json_array('```json\n[{"path":"a.md","snippet":"x"}]\n```') == [
        {"path": "a.md", "snippet": "x"}
    ]


def test_extract_json_array_surrounded_by_text():
    assert _extract_json_array('结果：[{"path":"a.md","snippet":"x"}] 完毕') == [
        {"path": "a.md", "snippet": "x"}
    ]


def test_extract_json_array_rejects_object():
    # 顶层是 dict（非 list）→ None
    assert _extract_json_array('{"path":"a.md"}') is None


def test_extract_json_array_empty_text():
    assert _extract_json_array("") is None
    assert _extract_json_array("这里没有 JSON") is None


def test_first_balanced_array():
    assert _first_balanced_array('xx [{"a":[1]}] yy') == '[{"a":[1]}]'
    assert _first_balanced_array("no bracket") is None


# --- retrieve() 映射 ---
def test_retrieve_maps_contexts(tmp_path):
    write(tmp_path, "doc1.md", "# Doc1\n\nalpha about cats\n")
    write(tmp_path, "sub/doc2.md", "# Doc2\n\nbeta about dogs\n")
    content = json.dumps(
        [
            {"path": "doc1.md", "snippet": "alpha about cats"},
            {"path": "sub/doc2.md", "snippet": "beta about dogs"},
        ]
    )
    r = FileLLMRetriever(client=_FakeClient(contents=content))
    ctxs = r.retrieve("cats and dogs", tmp_path, k=8)
    assert [c.source_path for c in ctxs] == ["doc1.md", "sub/doc2.md"]
    assert [c.text for c in ctxs] == ["alpha about cats", "beta about dogs"]
    assert ctxs[0].chunk_id == "file::doc1.md::0"
    assert ctxs[1].chunk_id == "file::sub/doc2.md::1"
    # score 按 LLM 给出顺序的 rank 分（越靠前越大）
    assert ctxs[0].score > ctxs[1].score
    assert ctxs[0].score == (8 - 0) / 8
    # from_graph 是 webapp schema 层字段；引擎 Context 不携带它，故只断言引擎字段。
    assert all(c.heading_path == "" and c.doc_id == "" for c in ctxs)


def test_retrieve_defends_unknown_and_empty_paths(tmp_path):
    write(tmp_path, "real.md", "# Real\n\nreal content\n")
    content = json.dumps(
        [
            {"path": "ghost.md", "snippet": "臆造路径"},   # 不属于已知文件集 → 丢
            {"path": "", "snippet": "空 path"},             # 空 path → 丢
            {"path": "real.md", "snippet": ""},             # 空 snippet → 丢
            {"path": "real.md", "snippet": "real content"}, # 合法
            "乱入字符串",                                    # 非 dict → 丢
            {"snippet": "缺 path"},                          # 缺 path → 丢
        ]
    )
    r = FileLLMRetriever(client=_FakeClient(contents=content))
    ctxs = r.retrieve("q", tmp_path, k=8)
    assert [(c.source_path, c.text) for c in ctxs] == [("real.md", "real content")]


def test_retrieve_truncates_to_k(tmp_path):
    write(tmp_path, "a.md", "line1\nline2\nline3\n")
    content = json.dumps(
        [{"path": "a.md", "snippet": f"line{i}"} for i in range(1, 4)]
    )
    r = FileLLMRetriever(client=_FakeClient(contents=content))
    ctxs = r.retrieve("q", tmp_path, k=2)
    assert len(ctxs) == 2
    assert [c.text for c in ctxs] == ["line1", "line2"]


def test_retrieve_client_error_returns_empty(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    r = FileLLMRetriever(client=_FakeClient(exc=RuntimeError("connection refused")))
    assert r.retrieve("q", tmp_path, k=8) == []


def test_retrieve_malformed_json_returns_empty(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    r = FileLLMRetriever(client=_FakeClient(contents="抱歉，我无法完成"))
    assert r.retrieve("q", tmp_path, k=8) == []


def test_retrieve_no_md_files_returns_empty(tmp_path):
    (tmp_path / "empty").mkdir()
    r = FileLLMRetriever(client=_FakeClient(contents="[]"))
    assert r.retrieve("q", tmp_path / "empty", k=8) == []


def test_retrieve_missing_source_dir_returns_empty(tmp_path):
    r = FileLLMRetriever(client=_FakeClient(contents="[]"))
    assert r.retrieve("q", tmp_path / "nope", k=8) == []


def test_retrieve_batches_by_char_budget(tmp_path):
    # 两个大文档，小预算 → 应分两批，各一次 LLM 调用
    write(tmp_path, "a.md", "a" * 8000)
    write(tmp_path, "b.md", "b" * 8000)
    contents = [
        json.dumps([{"path": "a.md", "snippet": "a" * 8000}]),
        json.dumps([{"path": "b.md", "snippet": "b" * 8000}]),
    ]
    client = _FakeClient(contents=contents)
    r = FileLLMRetriever(client=client, max_chars_per_batch=10000)
    ctxs = r.retrieve("q", tmp_path, k=8)
    assert len(client.completions.calls) == 2
    assert [c.source_path for c in ctxs] == ["a.md", "b.md"]


def test_retrieve_one_bad_batch_does_not_sink_others(tmp_path):
    write(tmp_path, "a.md", "a" * 8000)
    write(tmp_path, "b.md", "b" * 8000)
    # 第一批返回乱码（解析空），第二批正常 → 仍能拿到第二批结果
    contents = ["不是 JSON", json.dumps([{"path": "b.md", "snippet": "good"}])]
    r = FileLLMRetriever(client=_FakeClient(contents=contents), max_chars_per_batch=10000)
    ctxs = r.retrieve("q", tmp_path, k=8)
    assert [(c.source_path, c.text) for c in ctxs] == [("b.md", "good")]


# --- 端点/模型 env 注入 ---
def test_default_endpoint_and_model(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    for k in ("MDGRAPH_LLM_BASE_URL", "MDGRAPH_LLM_MODEL", "MDGRAPH_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r = FileLLMRetriever()
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"
    assert r._model == "qwen2.5:3b"


def test_env_overrides(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setenv("MDGRAPH_LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("MDGRAPH_LLM_MODEL", "qwen2.5:7b")
    r = FileLLMRetriever()
    assert captured["base_url"] == "http://localhost:1234/v1"
    assert r._model == "qwen2.5:7b"
