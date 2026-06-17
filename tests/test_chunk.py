from mdgraph.chunk import chunk_sections
from mdgraph.ids import doc_id
from mdgraph.parse import parse_document


def test_section_becomes_single_chunk_when_small():
    pd = parse_document("a.md", "# A\n\nshort body\n")
    chunks = chunk_sections(pd)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.doc_id == doc_id("a.md")
    assert c.id == f"{doc_id('a.md')}_s0_c0"
    assert "short body" in c.text
    assert pd.sections[0].text == c.text


def test_empty_section_produces_no_chunk():
    pd = parse_document("a.md", "# A\n## B\n\nbody\n")
    chunks = chunk_sections(pd)
    paths = {c.section_path for c in chunks}
    assert "A" not in paths  # A had no body


def test_oversized_section_splits_with_overlap():
    para1 = "x" * 40
    para2 = "y" * 40
    pd = parse_document("a.md", f"# A\n\n{para1}\n\n{para2}\n")
    chunks = chunk_sections(pd, max_chars=50, overlap=10)
    assert len(chunks) >= 2
    body = pd.sections[0].text
    for c in chunks:
        local_start = c.char_start - pd.sections[0].char_start
        assert body[local_start : local_start + len(c.text)] == c.text


def test_oversized_single_paragraph_hard_splits():
    big = "z" * 130
    pd = parse_document("a.md", f"# A\n\n{big}\n")
    chunks = chunk_sections(pd, max_chars=50, overlap=0)
    assert len(chunks) == 3  # 130-ish / 50


import pytest

from mdgraph.parse import parse_document as _pd


def test_invalid_max_chars_raises():
    pd = _pd("a.md", "# A\n\nbody\n")
    with pytest.raises(ValueError):
        chunk_sections(pd, max_chars=0)


def test_overlap_must_be_less_than_max_chars():
    pd = _pd("a.md", "# A\n\nbody\n")
    with pytest.raises(ValueError):
        chunk_sections(pd, max_chars=50, overlap=50)
    with pytest.raises(ValueError):
        chunk_sections(pd, max_chars=50, overlap=-1)
