from mdgraph.models import Chunk, Document, Edge, EdgeType, Node, NodeType
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.retrieve import Retriever
from mdgraph.store.graph_store import GraphStore
from mdgraph.store.vector_store import VectorStore


def test_retriever_without_graph_store_is_pure_vector(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    vs.add(["c1", "c2"], emb.embed(["alpha", "beta"]), ["alpha", "beta"],
           [{"source_path": "a.md"}, {"source_path": "b.md"}])
    res = Retriever(vs, emb).retrieve("alpha", k=2)  # graph_store=None
    assert res.contexts[0].chunk_id == "c1"
    assert 0.0 < res.contexts[0].score <= 1.0  # 相似度，不是 RRF
    assert res.subgraph == {"nodes": [], "edges": []}


def test_dual_pulls_graph_only_chunk_with_graph_metadata(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    # 图里有 c1、c2（c1 LINKS_TO c2）；向量库只有 c1
    gs.upsert_document(Document(id="d2", path="notes/b.md", hash="h", mtime=1.0))
    gs.upsert_chunk(Chunk(id="c2", doc_id="d2", section_path="B>Sub", text="graph only text", char_start=0, char_end=15))
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    gs.upsert_node(Node(id="c2", type=NodeType.CHUNK, doc_id="d2"))
    gs.upsert_edge(Edge(src="c1", dst="c2", type=EdgeType.LINKS_TO))
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{"source_path": "a.md", "heading_path": "A"}])
    res = Retriever(vs, emb, graph_store=gs).retrieve("alpha", k=8, hops=1)
    ids = [c.chunk_id for c in res.contexts]
    assert ids[0] == "c1"
    assert "c2" in ids
    c2ctx = next(c for c in res.contexts if c.chunk_id == "c2")
    assert c2ctx.text == "graph only text"
    assert c2ctx.source_path == "notes/b.md"
    assert c2ctx.heading_path == "B>Sub"
    assert any(e["type"] == EdgeType.LINKS_TO.value for e in res.subgraph["edges"])
    gs.close()


def test_dual_empty_query(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    res = Retriever(vs, emb, graph_store=gs).retrieve("   ")
    assert res.contexts == []
    gs.close()


def test_graph_weight_demotes_graph_only_chunk(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    # 向量命中 c1(先), c2(后)；图里 c1 LINKS_TO c3（c3 图独有 1 跳）
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    gs.upsert_node(Node(id="c3", type=NodeType.CHUNK, doc_id="d3"))
    gs.upsert_document(Document(id="d3", path="c.md", hash="h", mtime=1.0))
    gs.upsert_chunk(Chunk(id="c3", doc_id="d3", section_path="C", text="graph only", char_start=0, char_end=10))
    gs.upsert_edge(Edge(src="c1", dst="c3", type=EdgeType.LINKS_TO))
    vs.add(["c1", "c2"], emb.embed(["alpha topic", "beta topic"]),
           ["alpha topic", "beta topic"],
           [{"source_path": "a.md"}, {"source_path": "b.md"}])

    def ids(gw):
        r = Retriever(vs, emb, graph_store=gs, graph_weight=gw, per_doc_cap=None).retrieve(
            "alpha topic", k=8, hops=1)
        return [c.chunk_id for c in r.contexts]

    hi = ids(1.0)   # 高图权重：图独有 c3 排在向量命中 c2 之前
    lo = ids(0.1)   # 低图权重：c3 被压到 c2 之后
    assert hi.index("c3") < hi.index("c2")
    assert lo.index("c3") > lo.index("c2")
    gs.close()


def test_per_doc_cap_limits_same_source(tmp_path):
    emb = DeterministicEmbeddingProvider(dim=16)
    gs = GraphStore(tmp_path / "g.db")
    vs = VectorStore(tmp_path / "v", model_name=emb.name, dim=emb.dim)
    gs.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    for cid, did, path in [("c2", "d2", "b.md"), ("c3", "d2", "b.md"), ("c4", "d4", "c.md")]:
        gs.upsert_document(Document(id=did, path=path, hash="h", mtime=1.0))
        gs.upsert_node(Node(id=cid, type=NodeType.CHUNK, doc_id=did))
        gs.upsert_chunk(Chunk(id=cid, doc_id=did, section_path="S", text=cid, char_start=0, char_end=2))
        gs.upsert_edge(Edge(src="c1", dst=cid, type=EdgeType.LINKS_TO))
    vs.add(["c1"], emb.embed(["alpha"]), ["alpha"], [{"source_path": "a.md"}])

    capped = Retriever(vs, emb, graph_store=gs, per_doc_cap=1).retrieve("alpha", k=8, hops=1)
    cap_src = [c.source_path for c in capped.contexts]
    assert cap_src.count("b.md") <= 1     # b.md 被限到 1 块
    assert "c.md" in cap_src              # 其它文档得以进入

    uncapped = Retriever(vs, emb, graph_store=gs, per_doc_cap=None).retrieve("alpha", k=8, hops=1)
    un_src = [c.source_path for c in uncapped.contexts]
    assert un_src.count("b.md") == 2      # 不限流时 b.md 两块都在
    gs.close()
