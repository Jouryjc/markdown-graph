from mdgraph.engine import MarkdownGraph
from mdgraph.ids import entity_id
from mdgraph.models import EdgeType, NodeType
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def edges_of(store, etype):
    g = store.to_networkx()
    return {(u, v) for u, v, k in g.edges(keys=True) if k == etype.value}


def test_build_with_llm_creates_semantic_layer(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha relates to Beta\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph", llm=MockLLMProvider())
    report = mg.build([tmp_path])
    assert report.entities >= 2
    assert (entity_id("Alpha"), entity_id("Beta")) in edges_of(
        mg.graph_store, EdgeType.RELATES_TO
    )
    mg.close()


def test_llm_and_embedder_together(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha content about cats\n")
    mg = MarkdownGraph(
        tmp_path / ".mdgraph",
        embedder=DeterministicEmbeddingProvider(dim=16),
        llm=MockLLMProvider(),
    )
    mg.build([tmp_path])
    res = mg.retrieve("Alpha content about cats")
    assert res.contexts
    g = mg.graph_store.to_networkx()
    assert any(d["type"] == NodeType.ENTITY.value for _, d in g.nodes(data=True))
    mg.close()


def test_llm_none_no_entities(tmp_path):
    write(tmp_path, "a.md", "# A\n\nAlpha Beta\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no llm, no embedder
    mg.build([tmp_path])
    g = mg.graph_store.to_networkx()
    assert [n for n, d in g.nodes(data=True) if d["type"] == NodeType.ENTITY.value] == []
    mg.close()
