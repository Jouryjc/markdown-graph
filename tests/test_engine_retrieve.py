import pytest

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.mock import DeterministicEmbeddingProvider


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_build_and_retrieve_end_to_end(tmp_path):
    write(tmp_path, "notes/alpha.md", "# Alpha\n\nalpha content about cats\n")
    write(tmp_path, "notes/beta.md", "# Beta\n\nbeta content about dogs\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path / "notes"])
    assert mg.stats()["vectors"] == mg.stats()["chunks"]
    res = mg.retrieve("alpha content about cats", k=3)
    assert res.contexts
    assert res.contexts[0].source_path == "alpha.md"
    assert res.contexts[0].heading_path == "Alpha"
    mg.close()


def test_retrieve_without_embedder_raises(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # no embedder
    mg.build([tmp_path])
    with pytest.raises(RuntimeError):
        mg.retrieve("x")
    assert "vectors" not in mg.stats()
    mg.close()


def test_removed_doc_purges_its_vectors(tmp_path):
    write(tmp_path, "a.md", "# A\n\nalpha\n")
    write(tmp_path, "b.md", "# B\n\nbeta\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path])
    v1 = mg.stats()["vectors"]
    (tmp_path / "b.md").unlink()
    mg.build([tmp_path])
    v2 = mg.stats()["vectors"]
    assert v2 < v1
    assert v2 == mg.stats()["chunks"]
    mg.close()


def test_rebuild_idempotent_with_vectors(tmp_path):
    write(tmp_path, "a.md", "# A\n\nalpha\n")
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=emb)
    mg.build([tmp_path])
    s1 = mg.stats()
    mg.build([tmp_path])
    s2 = mg.stats()
    assert s1 == s2
    mg.close()
