import re

from mdgraph.ids import chunk_id, doc_id, section_id, tag_id

_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


def test_doc_id_is_deterministic_and_quote_free():
    a = doc_id("notes/a.md")
    assert a == doc_id("notes/a.md")
    assert a != doc_id("notes/b.md")
    assert a.startswith("d_")
    assert _SAFE.match(a)


def test_section_and_chunk_id_format():
    d = doc_id("a.md")
    assert section_id(d, 2) == f"{d}_s2"
    assert chunk_id(d, 2, 0) == f"{d}_s2_c0"
    assert _SAFE.match(chunk_id(d, 2, 0))


def test_tag_id_is_case_insensitive_and_quote_free():
    assert tag_id("Foo") == tag_id("foo")
    assert tag_id("foo").startswith("t_")
    assert _SAFE.match(tag_id("foo/bar"))
