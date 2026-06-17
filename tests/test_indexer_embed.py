from mdgraph.indexer import StructuralIndexer
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def make_indexer(tmp_path):
    gs = GraphStore(tmp_path / "g.db")
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    return gs, vs, StructuralIndexer(gs, vector_store=vs, embedder=emb)


def test_index_embeds_all_chunks(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha body\n\n## Sub\n\nmore text\n")
    write(src, "b.md", "# B\n\nbeta body\n")
    gs, vs, idx = make_indexer(tmp_path)
    idx.index([src], root=src)
    assert vs.count() == gs.stats()["chunks"]
    assert vs.count() >= 3
    gs.close()


def test_rebuild_does_not_duplicate_vectors(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha body\n")
    gs, vs, idx = make_indexer(tmp_path)
    idx.index([src], root=src)
    n1 = vs.count()
    idx.index([src], root=src)
    assert vs.count() == n1  # no duplicate rows across rebuilds
    gs.close()


def test_indexer_without_vector_store_is_structure_only(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nbody\n")
    gs = GraphStore(tmp_path / "g.db")
    idx = StructuralIndexer(gs)  # no vector_store / embedder
    report = idx.index([src], root=src)
    assert report.indexed == 1
    assert gs.stats()["chunks"] >= 1
    gs.close()


def test_errored_doc_embedding_skip_is_warned(tmp_path, monkeypatch):
    src = tmp_path / "src"
    write(src, "good.md", "# G\n\nok\n")
    write(src, "bad.md", "# B\n\nboom\n")
    gs, vs, idx = make_indexer(tmp_path)
    orig = idx._build_doc

    def maybe_fail(ctx, report):
        if ctx.relpath == "bad.md":
            raise RuntimeError("boom")
        return orig(ctx, report)

    monkeypatch.setattr(idx, "_build_doc", maybe_fail)
    report = idx.index([src], root=src)
    # bad.md recorded as error, and embedding-skip surfaced as a warning
    assert any("bad.md" in e[0] for e in report.errors)
    assert any("bad.md" in w for w in report.warnings)
    gs.close()
