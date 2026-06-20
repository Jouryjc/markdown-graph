import importlib.util
from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.mock import DeterministicEmbeddingProvider, MockLLMProvider

DEMO = Path(__file__).resolve().parent.parent / "examples" / "run_demo.py"
spec = importlib.util.spec_from_file_location("run_demo", DEMO)
run_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_demo)


def test_load_env_parses_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nFOO=bar\n\nBAZ = qux \n", encoding="utf-8")
    monkeypatch.delenv("FOO", raising=False)
    got = run_demo.load_env(env)
    assert got["FOO"] == "bar"
    assert got["BAZ"] == "qux"
    import os
    assert os.environ["FOO"] == "bar"


def _write(tmp_path, name, body):
    f = tmp_path / "src" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def test_compare_retrieval_flags_graph_added(tmp_path):
    # a 链接 b；查询命中 a，双引擎应经 LINKS_TO 把 b 也带出
    _write(tmp_path, "a.md", "# A\n\nalpha topic see [[b]]\n")
    _write(tmp_path, "b.md", "# B\n\nbeta detail about alpha\n")
    store = tmp_path / ".mdgraph"
    emb = DeterministicEmbeddingProvider(dim=16)
    mg = MarkdownGraph(store, embedder=emb, llm=MockLLMProvider())
    mg.build([tmp_path / "src"])
    rows = run_demo.compare_retrieval(
        mg.vector_store, emb, mg.graph_store, ["alpha"], k=5
    )
    assert rows[0]["query"] == "alpha"
    assert set(rows[0]["dual"]) >= set(rows[0]["vector_only"])  # 双引擎是超集或并集
    mg.close()


def test_top_mentioned_entities(tmp_path):
    _write(tmp_path, "a.md", "# A\n\nAlpha here\n")
    _write(tmp_path, "b.md", "# B\n\nAlpha again\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph", llm=MockLLMProvider())
    mg.build([tmp_path / "src"])
    top = run_demo.top_mentioned_entities(mg.graph_store, top=10)
    assert any(name == "Alpha" and cnt >= 2 for name, cnt in top)
    mg.close()
