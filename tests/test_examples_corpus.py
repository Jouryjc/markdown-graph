from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.models import EdgeType

CORPUS = Path(__file__).resolve().parent.parent / "examples" / "ai_kb"


def test_corpus_exists_and_sized():
    files = list(CORPUS.glob("*.md"))
    assert len(files) >= 18, f"语料至少 18 篇，实际 {len(files)}"


def test_corpus_builds_clean_and_interlinked(tmp_path):
    mg = MarkdownGraph(tmp_path / ".mdgraph")  # 无 provider，纯结构
    report = mg.build([CORPUS])
    assert report.errors == [], f"解析/索引不应有错误：{report.errors}"
    assert report.indexed >= 18
    g = mg.graph_store.to_networkx()
    links = [1 for _, _, k in g.edges(keys=True) if k == EdgeType.LINKS_TO.value]
    tagged = [1 for _, _, k in g.edges(keys=True) if k == EdgeType.TAGGED.value]
    assert len(links) >= 20, f"维基链接 LINKS_TO 边过少：{len(links)}"
    assert len(tagged) >= 10, f"TAGGED 边过少：{len(tagged)}"
    # 互联：未解析链接占比应较低（绝大多数 [[..]] 指向真实存在的文档）
    assert report.unresolved_links <= len(links) * 0.2
    mg.close()
