from mdgraph.parse import parse_document


def _links(pd):
    out = []
    for s in pd.sections:
        out.extend(s.links)
    return out


def test_wiki_links_with_alias_and_anchor():
    text = "# H\n\nsee [[Other Note]] and [[Doc#Sec|alias]] here\n"
    pd = parse_document("a.md", text)
    links = _links(pd)
    wiki = [l for l in links if l.kind == "wiki"]
    assert (wiki[0].target, wiki[0].anchor) == ("Other Note", None)
    assert (wiki[1].target, wiki[1].anchor) == ("Doc", "Sec")


def test_md_links_local_only_and_anchor_split():
    text = "# H\n\n[a](b/c.md) [x](https://e.com) [s](d.md#part)\n"
    pd = parse_document("a.md", text)
    md = [l for l in _links(pd) if l.kind == "md"]
    assert [(l.target, l.anchor) for l in md] == [("b/c.md", None), ("d.md", "part")]


def test_links_inside_code_are_ignored():
    text = "# H\n\nreal [[Real]] but `[[code]]` and\n```\n[[fenced]](x.md)\n```\n"
    pd = parse_document("a.md", text)
    targets = [l.target for l in _links(pd)]
    assert targets == ["Real"]


def test_tags_extracted_excluding_code():
    text = "# H\n\n#alpha and #beta/sub not `#code`\n"
    pd = parse_document("a.md", text)
    tags = []
    for s in pd.sections:
        tags.extend(s.tags)
    assert tags == ["alpha", "beta/sub"]


def test_link_pos_is_absolute_offset():
    text = "# H\n\nXX [[T]]\n"
    pd = parse_document("a.md", text)
    link = _links(pd)[0]
    assert text[link.pos : link.pos + 5] == "[[T]]"
