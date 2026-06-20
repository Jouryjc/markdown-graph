import pytest

from mdgraph.providers.anthropic_extractor import ClaudeExtractor


class _Block:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "record_extraction"
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]


class _FakeMessages:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._exc:
            raise self._exc
        return self._resp


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self.messages = _FakeMessages(resp, exc)


def test_parses_tool_use_into_extraction_result():
    payload = {
        "entities": [
            {"name": "RAG", "type": "技术", "description": "检索增强生成"},
            {"name": "Embedding", "type": "技术", "description": "向量表示"},
        ],
        "relations": [{"source": "RAG", "target": "Embedding", "type": "依赖"}],
    }
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp(payload)))
    res = ext.extract("RAG 依赖 Embedding。")
    assert [e.name for e in res.entities] == ["RAG", "Embedding"]
    assert res.entities[0].type == "技术"
    assert res.entities[0].description == "检索增强生成"
    assert (res.relations[0].source, res.relations[0].target, res.relations[0].type) == (
        "RAG", "Embedding", "依赖",
    )


def test_api_error_degrades_to_empty():
    ext = ClaudeExtractor(client=_FakeClient(exc=RuntimeError("boom")))
    res = ext.extract("anything")
    assert res.entities == [] and res.relations == []


def test_malformed_payload_degrades_to_empty():
    # tool_use.input 缺 entities/relations 键 → 降级空，不抛
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp({"foo": "bar"})))
    res = ext.extract("anything")
    assert res.entities == [] and res.relations == []


def test_default_model_and_override(monkeypatch):
    ext = ClaudeExtractor(client=_FakeClient(resp=_Resp({"entities": [], "relations": []})))
    assert ext._model == "claude-sonnet-4-6"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    ext2 = ClaudeExtractor(client=_FakeClient(resp=_Resp({"entities": [], "relations": []})))
    assert ext2._model == "claude-haiku-4-5"


def test_auth_token_branch(monkeypatch):
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("anthropic.Anthropic", _Fake)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.example.com")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ClaudeExtractor()
    assert captured.get("auth_token") == "tok"
    assert captured.get("base_url") == "https://relay.example.com"
    assert "api_key" not in captured


def test_api_key_fallback_branch(monkeypatch):
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("anthropic.Anthropic", _Fake)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xxx")
    ClaudeExtractor()
    assert captured.get("api_key") == "sk-xxx"
    assert "auth_token" not in captured


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ClaudeExtractor()
