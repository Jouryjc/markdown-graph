from mdgraph.ingest import discover, read_file


def test_discover_finds_md_recursively_sorted(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
    found = discover([tmp_path])
    names = [p.name for p in found]
    assert names == ["a.md", "b.md"]


def test_discover_dedupes_and_accepts_files(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("a", encoding="utf-8")
    found = discover([f, f, tmp_path])
    assert len([p for p in found if p.name == "a.md"]) == 1


def test_read_file_returns_text_hash_mtime(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")
    text, h, mtime = read_file(f)
    assert text == "hello"
    assert len(h) == 64  # sha256 hex
    assert h == read_file(f)[1]  # stable
    assert isinstance(mtime, float)
