from mdgraph.extract import EntityRecord, ExtractionBundle, extract_graph
from mdgraph.ids import entity_id
from mdgraph.providers.base import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LLMProvider,
)
from mdgraph.providers.mock import MockLLMProvider


def test_extract_aggregates_entities_mentions_relations():
    chunks = [("c1", "Alpha relates Beta"), ("c2", "Alpha and Gamma")]
    bundle = extract_graph(chunks, MockLLMProvider())
    assert isinstance(bundle, ExtractionBundle)
    ids = {e.id for e in bundle.entities}
    assert {entity_id("Alpha"), entity_id("Beta"), entity_id("Gamma")} <= ids
    assert len(bundle.entities) == 3  # Alpha merged across chunks
    alpha = entity_id("Alpha")
    assert ("c1", alpha) in bundle.mentions
    assert ("c2", alpha) in bundle.mentions
    assert (entity_id("Alpha"), entity_id("Beta"), "related_to") in bundle.relations
    assert (entity_id("Alpha"), entity_id("Gamma"), "related_to") in bundle.relations


def test_extract_dedupes_mentions_and_relations():
    chunks = [("c1", "Alpha Beta"), ("c1", "Alpha Beta")]
    bundle = extract_graph(chunks, MockLLMProvider())
    assert len(bundle.mentions) == len(set(bundle.mentions))
    assert len(bundle.relations) == len(set(bundle.relations))


def test_extract_records_failed_chunks():
    class FailingLLM(LLMProvider):
        def extract(self, text):
            if "boom" in text:
                raise RuntimeError("boom")
            return ExtractionResult(entities=[ExtractedEntity(name="Ok")], relations=[])

    bundle = extract_graph([("c1", "boom here"), ("c2", "Ok stuff")], FailingLLM())
    assert bundle.failed_chunks == ["c1"]
    assert any(e.name == "Ok" for e in bundle.entities)


def test_extract_collects_aliases_canonical_is_first():
    class AliasLLM(LLMProvider):
        def __init__(self):
            self.i = 0

        def extract(self, text):
            self.i += 1
            name = "Foo Bar" if self.i == 1 else "foo, bar"
            return ExtractionResult(entities=[ExtractedEntity(name=name)], relations=[])

    bundle = extract_graph([("c1", "x"), ("c2", "y")], AliasLLM())
    assert len(bundle.entities) == 1
    e = bundle.entities[0]
    assert e.name == "Foo Bar"
    assert "foo, bar" in e.aliases


def test_relation_dropped_when_endpoint_not_an_entity():
    class RelLLM(LLMProvider):
        def extract(self, text):
            return ExtractionResult(
                entities=[ExtractedEntity(name="Solo")],
                relations=[ExtractedRelation(source="Solo", target="Ghost", type="x")],
            )

    bundle = extract_graph([("c1", "z")], RelLLM())
    assert bundle.relations == []
