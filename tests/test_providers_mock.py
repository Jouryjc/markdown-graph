from mdgraph.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    ExtractionResult,
)
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)


def test_embedding_provider_is_subclass_and_reports_dim_name():
    emb = DeterministicEmbeddingProvider(dim=16, name="mock-embed")
    assert isinstance(emb, EmbeddingProvider)
    assert emb.dim == 16
    assert emb.name == "mock-embed"


def test_embedding_is_deterministic_and_correct_dim():
    emb = DeterministicEmbeddingProvider(dim=16)
    a = emb.embed(["hello world"])
    b = emb.embed(["hello world"])
    assert a == b
    assert len(a) == 1
    assert len(a[0]) == 16


def test_embedding_is_unit_normalized_for_nonempty_text():
    emb = DeterministicEmbeddingProvider(dim=16)
    vec = emb.embed(["alpha beta gamma"])[0]
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_different_text_gives_different_vector():
    emb = DeterministicEmbeddingProvider(dim=16)
    assert emb.embed(["cat"])[0] != emb.embed(["dog"])[0]


def test_mock_llm_extracts_capitalized_entities_and_chain_relations():
    llm = MockLLMProvider()
    assert isinstance(llm, LLMProvider)
    result = llm.extract("Alpha relates to Beta and Gamma here.")
    assert isinstance(result, ExtractionResult)
    names = [e.name for e in result.entities]
    assert names == ["Alpha", "Beta", "Gamma"]
    rels = [(r.source, r.target) for r in result.relations]
    assert rels == [("Alpha", "Beta"), ("Beta", "Gamma")]


def test_mock_llm_dedupes_entities():
    llm = MockLLMProvider()
    result = llm.extract("Alpha and Alpha again.")
    assert [e.name for e in result.entities] == ["Alpha"]
    assert result.relations == []
