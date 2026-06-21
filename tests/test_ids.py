import re

from mdgraph.ids import chunk_id, doc_id, doc_id_from_chunk, section_id, tag_id

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


def test_doc_id_from_chunk_round_trips_chunk_and_section_ids():
    d = doc_id("notes/a.md")
    assert doc_id_from_chunk(chunk_id(d, 2, 3)) == d
    assert doc_id_from_chunk(section_id(d, 2)) == d
    assert doc_id_from_chunk(d) == d


def test_doc_id_from_chunk_returns_empty_on_unrecognized_id():
    assert doc_id_from_chunk("e_deadbeef") == ""
    assert doc_id_from_chunk("") == ""


def test_tag_id_is_case_insensitive_and_quote_free():
    assert tag_id("Foo") == tag_id("foo")
    assert tag_id("foo").startswith("t_")
    assert _SAFE.match(tag_id("foo/bar"))


def test_normalize_name_lowercases_and_collapses():
    from mdgraph.ids import normalize_name

    assert normalize_name("Foo, Bar") == "foo bar"
    assert normalize_name("foo   bar") == "foo bar"
    assert normalize_name("  Baz!  ") == "baz"


def test_entity_id_normalizes_and_is_quote_free():
    from mdgraph.ids import entity_id

    assert entity_id("Foo Bar") == entity_id("foo,  bar")
    assert entity_id("X").startswith("e_")
    assert _SAFE.match(entity_id("foo bar"))
    assert entity_id("a") != entity_id("b")
