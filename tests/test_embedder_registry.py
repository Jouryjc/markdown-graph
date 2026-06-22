import pytest

from mdgraph.providers import registry
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.providers.registry import (
    EMBEDDER_REGISTRY,
    _parse_spec,
    resolve_embedder,
)


# --- _parse_spec：仅断言 (key, arg)，不构造任何 provider ---
def test_parse_spec_bare_dotted_path():
    assert _parse_spec("mdgraph.providers.mock:DeterministicEmbeddingProvider") == (
        "mdgraph.providers.mock",
        "DeterministicEmbeddingProvider",
    )


def test_parse_spec_shortname_no_arg():
    assert _parse_spec("fastembed") == ("fastembed", None)
    assert _parse_spec("openai") == ("openai", None)


def test_parse_spec_shortname_with_arg():
    assert _parse_spec("fastembed:BAAI/bge-m3") == ("fastembed", "BAAI/bge-m3")
    assert _parse_spec("openai:nomic-embed-text") == ("openai", "nomic-embed-text")


def test_parse_spec_model_name_with_slash_only():
    # 含 "/" 但不含 ":" → 整串当 key、arg None（落 dotted-path 分支）
    assert _parse_spec("BAAI/bge-m3") == ("BAAI/bge-m3", None)


def test_parse_spec_trailing_colon_empty_arg():
    assert _parse_spec("fastembed:") == ("fastembed", "")


# --- 短名分支：monkeypatch 工厂为返回 mock 的桩，断言收到正确 arg（不构造真实模型） ---
def test_resolve_fastembed_dispatches_with_arg(monkeypatch):
    seen = {}

    def fake_factory(arg):
        seen["arg"] = arg
        return DeterministicEmbeddingProvider(name="fake-fastembed")

    monkeypatch.setitem(EMBEDDER_REGISTRY, "fastembed", fake_factory)
    prov = resolve_embedder("fastembed:BAAI/bge-m3")
    assert seen["arg"] == "BAAI/bge-m3"
    assert prov.name == "fake-fastembed"


def test_resolve_fastembed_default_arg_none(monkeypatch):
    seen = {}

    def fake_factory(arg):
        seen["arg"] = arg
        return DeterministicEmbeddingProvider(name="fake")

    monkeypatch.setitem(EMBEDDER_REGISTRY, "fastembed", fake_factory)
    resolve_embedder("fastembed")
    assert seen["arg"] is None


def test_resolve_openai_dispatches_with_arg(monkeypatch):
    seen = {}

    def fake_factory(arg):
        seen["arg"] = arg
        return DeterministicEmbeddingProvider(name="fake-openai")

    monkeypatch.setitem(EMBEDDER_REGISTRY, "openai", fake_factory)
    prov = resolve_embedder("openai:somemodel")
    assert seen["arg"] == "somemodel"
    assert prov.name == "fake-openai"


def test_real_fastembed_factory_uses_default_model(monkeypatch):
    # 不下载：拦截 FastEmbedProvider.__init__ 捕获 model_name。
    captured = {}

    class _FakeFastEmbed(DeterministicEmbeddingProvider):
        def __init__(self, model_name=None, model=None):
            captured["model_name"] = model_name
            super().__init__(name="fake")

    monkeypatch.setattr(
        "mdgraph.providers.fastembed_embedder.FastEmbedProvider", _FakeFastEmbed
    )
    resolve_embedder("fastembed")
    assert captured["model_name"] == "BAAI/bge-small-zh-v1.5"
    captured.clear()
    resolve_embedder("fastembed:BAAI/bge-m3")
    assert captured["model_name"] == "BAAI/bge-m3"


def test_real_openai_factory_passes_model(monkeypatch):
    # 不联网：拦截 OpenAIEmbeddingProvider 捕获 model。
    captured = {}

    class _FakeOpenAIEmbed(DeterministicEmbeddingProvider):
        def __init__(self, model=None, **kw):
            captured["model"] = model
            super().__init__(name="fake")

    monkeypatch.setattr(
        "mdgraph.providers.openai_embedder.OpenAIEmbeddingProvider", _FakeOpenAIEmbed
    )
    resolve_embedder("openai:nomic-embed-text")
    assert captured["model"] == "nomic-embed-text"
    captured.clear()
    resolve_embedder("openai")
    assert captured["model"] is None  # 缺省 arg → None → provider 默认


# --- dotted-path 分支（向后兼容）：纯 Python、不下载的目标 ---
def test_resolve_dotted_path_colon_form():
    prov = resolve_embedder("mdgraph.providers.mock:DeterministicEmbeddingProvider")
    assert isinstance(prov, DeterministicEmbeddingProvider)


def test_resolve_dotted_path_dot_form():
    prov = resolve_embedder("mdgraph.providers.mock.DeterministicEmbeddingProvider")
    assert isinstance(prov, DeterministicEmbeddingProvider)


def test_default_spec_resolves_via_dotted_fallback(monkeypatch):
    # 默认 spec 含 ":" 但 key 不是注册短名 → 走 dotted-path；monkeypatch 构造避免下载。
    constructed = {}

    class _FakeFastEmbed:
        def __init__(self):
            constructed["ok"] = True

    monkeypatch.setattr(
        "mdgraph.providers.fastembed_embedder.FastEmbedProvider", _FakeFastEmbed
    )
    prov = resolve_embedder(
        "mdgraph.providers.fastembed_embedder:FastEmbedProvider"
    )
    assert constructed.get("ok") is True
    assert isinstance(prov, _FakeFastEmbed)


# --- 错误：清晰 ValueError，消息含 spec 原文 ---
def test_unimportable_module_raises_valueerror():
    with pytest.raises(ValueError) as ei:
        resolve_embedder("no.such.module:Thing")
    assert "no.such.module:Thing" in str(ei.value)


def test_missing_attr_raises_valueerror():
    with pytest.raises(ValueError) as ei:
        resolve_embedder("mdgraph.providers.mock:NoSuchClass")
    assert "mdgraph.providers.mock:NoSuchClass" in str(ei.value)


def test_bare_model_name_without_prefix_raises_valueerror():
    with pytest.raises(ValueError) as ei:
        resolve_embedder("BAAI/bge-m3")
    assert "BAAI/bge-m3" in str(ei.value)


def test_shortname_factory_error_raises_valueerror(monkeypatch):
    def boom(arg):
        raise RuntimeError("connection refused")

    monkeypatch.setitem(EMBEDDER_REGISTRY, "openai", boom)
    with pytest.raises(ValueError) as ei:
        resolve_embedder("openai:bad")
    assert "openai:bad" in str(ei.value)
