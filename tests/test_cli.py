import json

from typer.testing import CliRunner

from mdgraph.cli import app

runner = CliRunner()
EMB = "mdgraph.providers.mock:DeterministicEmbeddingProvider"
LLM = "mdgraph.providers.mock:MockLLMProvider"


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def test_index_then_query(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha topic body\n")
    write(src, "b.md", "# B\n\nbeta topic body\n")
    store = tmp_path / "store"
    r = runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    assert r.exit_code == 0, r.output
    assert "indexed=2" in r.output

    r = runner.invoke(
        app, ["query", "alpha", "--store", str(store), "--embedder", EMB, "-k", "3"]
    )
    assert r.exit_code == 0, r.output
    assert "a.md" in r.output


def test_query_json_output(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nalpha\n")
    store = tmp_path / "store"
    runner.invoke(app, ["index", str(src), "--store", str(store), "--embedder", EMB])
    r = runner.invoke(
        app, ["query", "alpha", "--store", str(store), "--embedder", EMB, "--json"]
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert "contexts" in payload and "subgraph" in payload


def test_query_without_embedder_errors(tmp_path):
    r = runner.invoke(app, ["query", "alpha", "--store", str(tmp_path / "store")])
    assert r.exit_code != 0
    assert "embedder" in r.output.lower()


def test_bad_dotted_path_errors(tmp_path):
    src = tmp_path / "src"
    write(src, "a.md", "# A\n\nx\n")
    r = runner.invoke(
        app,
        ["index", str(src), "--store", str(tmp_path / "s"), "--embedder", "no.such:Thing"],
    )
    assert r.exit_code != 0
