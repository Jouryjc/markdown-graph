import pytest

from mdgraph.providers.local_llm_extractor import (
    LocalLLMExtractor,
    _extract_json,
    _first_balanced_object,
)


# --- fake openai client（chat.completions.create -> resp.choices[0].message.content）---
class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, content=None, exc=None):
        self._content, self._exc = content, exc
        self.kwargs = None

    def create(self, **kw):
        self.kwargs = kw
        if self._exc:
            raise self._exc
        return _Resp(self._content)


class _FakeClient:
    def __init__(self, content=None, exc=None):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content, exc)})()


# --- _extract_json / _first_balanced_object ---
def test_extract_json_bare():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_surrounded_by_text():
    assert _extract_json('好的，结果如下：{"a": 1} 希望有帮助') == {"a": 1}


def test_extract_json_nested():
    assert _extract_json('{"x": {"y": 2}}') == {"x": {"y": 2}}


def test_extract_json_no_json():
    assert _extract_json("这里没有 JSON") is None


def test_extract_json_empty():
    assert _extract_json("") is None


def test_first_balanced_object():
    assert _first_balanced_object('xx {"a": {"b": 1}} yy') == '{"a": {"b": 1}}'
    assert _first_balanced_object("no brace") is None


# --- extract() ---
def test_extract_parses_entities_and_relations():
    content = (
        '{"entities":[{"name":"RAG","type":"技术","description":"检索增强生成"},'
        '{"name":"Embedding","type":"技术","description":"向量表示"}],'
        '"relations":[{"source":"RAG","target":"Embedding","type":"依赖"}]}'
    )
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("RAG 依赖 Embedding。")
    assert [e.name for e in res.entities] == ["RAG", "Embedding"]
    assert res.entities[0].type == "技术"
    assert res.entities[0].description == "检索增强生成"
    assert (res.relations[0].source, res.relations[0].target, res.relations[0].type) == (
        "RAG", "Embedding", "依赖",
    )


def test_extract_handles_fenced_and_missing_optional_fields():
    content = '```json\n{"entities":[{"name":"A"}],"relations":[]}\n```'
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert res.entities[0].name == "A"
    assert res.entities[0].type == "concept"      # 缺 type → 默认
    assert res.entities[0].description == ""        # 缺 description → 默认


def test_extract_relations_as_array_triples():
    # 小模型把 relation 输出成数组三元组 [source, type, target]（观测到的真实形态）
    content = (
        '{"entities":[{"name":"Claude","type":"product","description":"LLM"}],'
        '"relations":[["Claude","is a","product"],["Claude","made by","Anthropic"]]}'
    )
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert [e.name for e in res.entities] == ["Claude"]
    assert [(r.source, r.type, r.target) for r in res.relations] == [
        ("Claude", "is a", "product"),
        ("Claude", "made by", "Anthropic"),
    ]


def test_extract_relations_array_pair_defaults_type():
    # 二元数组 [source, target] → type 缺省 related_to
    content = '{"entities":[],"relations":[["A","B"]]}'
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert [(r.source, r.target, r.type) for r in res.relations] == [("A", "B", "related_to")]


def test_extract_malformed_relations_preserve_entities():
    # relations 整体畸形（缺字段 / 混入字符串 / 空数组），entities 必须全部保留，坏 relation 跳过
    content = (
        '{"entities":[{"name":"RAG"},{"name":"Embedding"}],'
        '"relations":[{"source":"RAG"},"乱入字符串",[],'
        '{"source":"RAG","target":"Embedding","type":"依赖"}]}'
    )
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert [e.name for e in res.entities] == ["RAG", "Embedding"]
    # 仅最后一条合法 relation 被保留
    assert [(r.source, r.target, r.type) for r in res.relations] == [("RAG", "Embedding", "依赖")]


def test_extract_skips_entity_missing_name():
    # 缺 name（或 name 为空）的实体跳过，其余实体正常产出
    content = (
        '{"entities":[{"type":"x"},{"name":""},{"name":"OK","type":"概念"}],'
        '"relations":[]}'
    )
    res = LocalLLMExtractor(client=_FakeClient(content=content)).extract("x")
    assert [e.name for e in res.entities] == ["OK"]
    assert res.entities[0].type == "概念"


def test_extract_malformed_degrades_to_empty():
    res = LocalLLMExtractor(client=_FakeClient(content="抱歉，我无法完成")).extract("x")
    assert res.entities == [] and res.relations == []


def test_extract_api_error_degrades_to_empty():
    res = LocalLLMExtractor(client=_FakeClient(exc=RuntimeError("connection refused"))).extract("x")
    assert res.entities == [] and res.relations == []


# --- 端点/模型 env 注入（monkeypatch openai.OpenAI 捕获 kwargs）---
def test_default_endpoint_and_model(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    for k in ("MDGRAPH_LLM_BASE_URL", "MDGRAPH_LLM_MODEL", "MDGRAPH_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ext = LocalLLMExtractor()
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "ollama"
    assert ext._model == "qwen2.5:3b"


def test_env_overrides(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    monkeypatch.setenv("MDGRAPH_LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("MDGRAPH_LLM_MODEL", "qwen2.5:7b")
    ext = LocalLLMExtractor()
    assert captured["base_url"] == "http://localhost:1234/v1"
    assert ext._model == "qwen2.5:7b"
