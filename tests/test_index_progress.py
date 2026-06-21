"""进度回调测试：离线、确定性，无真实模型。"""

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.mock import DeterministicEmbeddingProvider


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_progress_callback_reports_indexing_and_done(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n")
    write(tmp_path, "b.md", "# B\n\nbody of b\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")

    events: list[tuple[str, int, int]] = []
    report = mg.build([tmp_path], progress=lambda phase, cur, tot: events.append((phase, cur, tot)))

    assert report.indexed == 2
    assert ("indexing", 1, 2) in events
    assert ("indexing", 2, 2) in events
    assert events[-1] == ("done", 1, 1)
    # 无 embedder 时不应出现 embedding 阶段
    assert not any(e[0] == "embedding" for e in events)
    mg.close()


def test_progress_callback_reports_embedding_phase(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody of a\n")
    write(tmp_path, "b.md", "# B\n\nbody of b\n")
    embedder = DeterministicEmbeddingProvider()
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=embedder)

    events: list[tuple[str, int, int]] = []
    mg.build([tmp_path], progress=lambda phase, cur, tot: events.append((phase, cur, tot)))

    assert ("indexing", 1, 2) in events
    assert ("indexing", 2, 2) in events
    assert ("embedding", 0, 1) in events
    assert ("embedding", 1, 1) in events
    assert events.index(("embedding", 0, 1)) < events.index(("embedding", 1, 1))
    assert events[-1] == ("done", 1, 1)
    mg.close()


def test_none_callback_is_noop(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    report = mg.build([tmp_path])  # progress defaults to None
    assert report.indexed == 1
    mg.close()


def test_raising_callback_does_not_crash_build(tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph")

    def boom(phase, cur, tot):
        raise RuntimeError("callback should never crash the build")

    report = mg.build([tmp_path], progress=boom)
    assert report.indexed == 1
    mg.close()
