import json

from mdgraph.providers.sag_extractor import (
    SAG_ENTITY_TYPE_SPEC,
    SAG_ENTITY_TYPES,
    SAGExtractor,
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
        self.completions = _FakeCompletions(content, exc)
        self.chat = type("Chat", (), {"completions": self.completions})()


def _response(item: dict) -> str:
    return json.dumps({"type": "response", "data": {"items": [item]}}, ensure_ascii=False)


_GOOD = _response(
    {
        "id": 1,
        "title": "OpenAI 发布 GPT-4",
        "summary": "2024 年 OpenAI 发布 GPT-4。",
        "content": "2024 年，OpenAI 发布了 GPT-4。",
        "category": "产品发布",
        "keywords": ["GPT-4", "OpenAI"],
        "entities": [
            {"type": "organization", "name": "OpenAI", "description": "AI 公司"},
            {"type": "product", "name": "GPT-4", "description": "模型"},
        ],
    }
)


def test_extract_json_helpers():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json("无 JSON") is None
    assert _first_balanced_object('xx {"a": 1} yy') == '{"a": 1}'
    assert _first_balanced_object("none") is None


def test_extract_event_maps_event_and_entities():
    ext = SAGExtractor(client=_FakeClient(content=_GOOD))
    ev = ext.extract_event("2024 年，OpenAI 发布了 GPT-4。", heading="发布", doc_title="doc")
    assert ev is not None
    assert ev.title == "OpenAI 发布 GPT-4"
    assert ev.category == "产品发布"
    assert ev.keywords == ["GPT-4", "OpenAI"]
    assert [(e.type, e.name) for e in ev.entities] == [
        ("organization", "OpenAI"),
        ("product", "GPT-4"),
    ]


def test_extract_event_uses_json_object_and_temperature_zero():
    fake = _FakeClient(content=_GOOD)
    ext = SAGExtractor(client=fake)
    ext.extract_event("hi")
    kw = fake.completions.kwargs
    assert kw["temperature"] == 0
    assert kw["response_format"] == {"type": "json_object"}


def test_extract_event_heading_prefixed_as_h1():
    fake = _FakeClient(content=_GOOD)
    ext = SAGExtractor(client=fake)
    ext.extract_event("正文", heading="标题")
    user_msg = fake.completions.kwargs["messages"][-1]["content"]
    payload = json.loads(user_msg)
    assert payload["data"]["items"][0]["content"] == "# 标题\n\n正文"
    # meta 下发的是「带定义」的类型表（{type, description}），而非裸类型名，
    # 否则小模型把概念/技术都塞进 tags、实体类型层失去区分度。
    assert payload["data"]["meta"]["entity_types"] == SAG_ENTITY_TYPE_SPEC
    assert [t["type"] for t in payload["data"]["meta"]["entity_types"]] == SAG_ENTITY_TYPES


def test_entity_name_length_filter():
    content = _response(
        {
            "id": 1,
            "title": "T",
            "summary": "S",
            "content": "C",
            "category": "",
            "keywords": [],
            "entities": [
                {"type": "person", "name": "A", "description": ""},  # 长度=1 丢弃
                {"type": "person", "name": "  ", "description": ""},  # 空白丢弃
                {"type": "person", "name": "Alice", "description": ""},
            ],
        }
    )
    ev = SAGExtractor(client=_FakeClient(content=content)).extract_event("x")
    assert [e.name for e in ev.entities] == ["Alice"]


def test_out_of_taxonomy_type_coerced_to_tags():
    content = _response(
        {
            "id": 1,
            "title": "T",
            "summary": "S",
            "content": "C",
            "category": "",
            "keywords": [],
            "entities": [{"type": "made-up", "name": "Thing", "description": ""}],
        }
    )
    ev = SAGExtractor(client=_FakeClient(content=content)).extract_event("x")
    assert ev.entities[0].type == "tags"


def test_keywords_coerced_to_list_of_str():
    content = _response(
        {
            "id": 1,
            "title": "T",
            "summary": "S",
            "content": "C",
            "category": "",
            "keywords": "not-a-list",
            "entities": [],
        }
    )
    ev = SAGExtractor(client=_FakeClient(content=content)).extract_event("x")
    assert ev.keywords == []


def test_bad_json_returns_none():
    ev = SAGExtractor(client=_FakeClient(content="抱歉，我无法完成")).extract_event("x")
    assert ev is None


def test_empty_items_returns_none():
    content = json.dumps({"type": "response", "data": {"items": []}})
    ev = SAGExtractor(client=_FakeClient(content=content)).extract_event("x")
    assert ev is None


def test_empty_content_returns_none_without_calling_llm():
    fake = _FakeClient(content=_GOOD)
    ext = SAGExtractor(client=fake)
    assert ext.extract_event("   ") is None
    assert fake.completions.kwargs is None


def test_api_error_returns_none():
    ext = SAGExtractor(client=_FakeClient(exc=RuntimeError("connection refused")))
    assert ext.extract_event("x") is None


# --- 端点/模型 env 注入 ---
def test_default_endpoint_and_model(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    for k in ("MDGRAPH_LLM_BASE_URL", "MDGRAPH_LLM_MODEL", "MDGRAPH_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    ext = SAGExtractor()
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
    ext = SAGExtractor()
    assert captured["base_url"] == "http://localhost:1234/v1"
    assert ext._model == "qwen2.5:7b"
