from mdgraph.engine import MarkdownGraph
from mdgraph.ids import chunk_id, doc_id, entity_id
from mdgraph.providers.mock import DeterministicEmbeddingProvider, MockLLMProvider


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_dual_engine_surfaces_co_mentioned_chunk_and_subgraph(tmp_path):
    # a、b 都提及 "Shared" -> 经实体共提及（2 跳）相连
    write(tmp_path, "a.md", "# A\n\nalpha content with Shared\n")
    write(tmp_path, "b.md", "# B\n\ntotally unrelated words Shared\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb, llm=MockLLMProvider())
    mg.build([tmp_path])
    res = mg.retrieve("alpha content with Shared", k=8)
    ids = [c.chunk_id for c in res.contexts]
    a_chunk = chunk_id(doc_id("a.md"), 0, 0)
    b_chunk = chunk_id(doc_id("b.md"), 0, 0)
    assert a_chunk in ids
    assert b_chunk in ids
    # 子图含连接两块的 Shared 实体节点
    assert any(n["id"] == entity_id("Shared") for n in res.subgraph["nodes"])
    mg.close()


def test_retrieve_without_embedder_still_raises(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no embedder
    mg.build([tmp_path])
    import pytest

    with pytest.raises(RuntimeError):
        mg.retrieve("x")
    mg.close()
