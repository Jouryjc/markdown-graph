from mdgraph.parse import SECTION_PATH_SEP, parse_document


def test_headings_build_sections_with_path_and_parent():
    text = "# A\n\nhello\n\n## B\n\nworld\n"
    pd = parse_document("a.md", text)
    assert [s.heading_path for s in pd.sections] == ["A", f"A{SECTION_PATH_SEP}B"]
    b = pd.sections[1]
    assert b.level == 2
    assert b.parent_idx == 0
    assert "world" in b.text


def test_preamble_before_first_heading_becomes_level0_section():
    text = "intro text\n\n# A\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.sections[0].level == 0
    assert pd.sections[0].heading_path == ""
    assert "intro text" in pd.sections[0].text


def test_heading_inside_fenced_code_is_not_a_section():
    text = "# Real\n\n```\n# not a heading\n```\n\nafter\n"
    pd = parse_document("a.md", text)
    assert [s.heading_path for s in pd.sections] == ["Real"]


def test_frontmatter_parsed_and_excluded_from_body():
    text = "---\ntitle: T\ntags:\n  - x\n  - y\n---\n# H\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.frontmatter["title"] == "T"
    assert pd.frontmatter["tags"] == ["x", "y"]
    assert [s.heading_path for s in pd.sections] == ["H"]


def test_broken_frontmatter_is_ignored_with_warning():
    text = "---\n: : bad: [\n---\n# H\n\nbody\n"
    pd = parse_document("a.md", text)
    assert pd.frontmatter == {}
    assert pd.warnings
