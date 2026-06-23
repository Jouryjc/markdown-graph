from mdgraph.engine import MarkdownGraph
from mdgraph.retrieve import Context


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


class _StubRetriever:
    """注入式 retriever：记录调用并返回固定 Context（绝不联网/调真实模型）。"""

    def __init__(self, contexts):
        self._contexts = contexts
        self.calls = []

    def retrieve(self, query, source_dir, k=8):
        self.calls.append((query, source_dir, k))
        return self._contexts


def test_build_persists_source_with_relative_layout(tmp_path):
    src = tmp_path / "docs"
    write(src, "alpha.md", "# Alpha\n\nalpha body\n")
    write(src, "nested/beta.md", "# Beta\n\nbeta body\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # embedder=None：File 路径独立于向量
    mg.build([src])
    source_dir = mg.store_dir / "source"
    assert (source_dir / "alpha.md").read_text(encoding="utf-8") == "# Alpha\n\nalpha body\n"
    assert (source_dir / "nested/beta.md").read_text(encoding="utf-8") == "# Beta\n\nbeta body\n"
    mg.close()


def test_full_rebuild_clears_stale_source(tmp_path):
    src = tmp_path / "docs"
    write(src, "alpha.md", "# Alpha\n\na\n")
    write(src, "beta.md", "# Beta\n\nb\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([src], incremental=False)
    source_dir = mg.store_dir / "source"
    assert (source_dir / "beta.md").exists()
    # 删除 beta 后 full 重建：source/ 先清空再全量复制，stale beta.md 应消失
    (src / "beta.md").unlink()
    mg.build([src], incremental=False)
    assert (source_dir / "alpha.md").exists()
    assert not (source_dir / "beta.md").exists()
    mg.close()


def test_retrieve_file_without_source_returns_empty(tmp_path):
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # 从未 build → 无 source/
    res = mg.retrieve_file("anything", k=5)
    assert res.contexts == []
    assert res.subgraph == {"nodes": [], "edges": []}
    mg.close()


def test_retrieve_file_with_source_and_injected_retriever(tmp_path):
    src = tmp_path / "docs"
    write(src, "alpha.md", "# Alpha\n\nalpha body\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([src])
    stub = _StubRetriever(
        [Context(chunk_id="file::alpha.md::0", text="alpha body", score=1.0, source_path="alpha.md")]
    )
    res = mg.retrieve_file("alpha", k=3, retriever=stub)
    assert [c.source_path for c in res.contexts] == ["alpha.md"]
    assert res.subgraph == {"nodes": [], "edges": []}
    # retriever 收到 store_dir/source 与传入的 k
    assert len(stub.calls) == 1
    query, source_dir, k = stub.calls[0]
    assert query == "alpha"
    assert source_dir == mg.store_dir / "source"
    assert k == 3
    mg.close()
