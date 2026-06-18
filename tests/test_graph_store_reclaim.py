from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_reclaim_deletes_orphan_entity_and_dangling_relation(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    # e1 有 MENTIONS（来自 chunk c1）→ 保留；e2 无 MENTIONS → 孤儿
    store.upsert_node(Node(id="c1", type=NodeType.CHUNK, doc_id="d1"))
    store.upsert_node(Node(id="e1", type=NodeType.ENTITY))
    store.upsert_node(Node(id="e2", type=NodeType.ENTITY))
    store.upsert_edge(Edge(src="c1", dst="e1", type=EdgeType.MENTIONS))
    store.upsert_edge(Edge(src="e1", dst="e2", type=EdgeType.RELATES_TO))
    n = store.reclaim_orphans()
    assert n == 1
    assert store.get_node("e1") is not None
    assert store.get_node("e2") is None
    # e2 的悬挂 RELATES_TO 也被清掉
    g = store.to_networkx()
    assert not any(k == EdgeType.RELATES_TO.value for _, _, k in g.edges(keys=True))
    store.close()


def test_reclaim_deletes_orphan_tag(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="d1", type=NodeType.DOCUMENT, doc_id="d1"))
    store.upsert_node(Node(id="t_used", type=NodeType.TAG, meta={"name": "used"}))
    store.upsert_node(Node(id="t_orphan", type=NodeType.TAG, meta={"name": "orphan"}))
    store.upsert_edge(Edge(src="d1", dst="t_used", type=EdgeType.TAGGED))
    n = store.reclaim_orphans()
    assert n == 1
    assert store.get_node("t_used") is not None
    assert store.get_node("t_orphan") is None
    store.close()


def test_reclaim_is_idempotent(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="e_orphan", type=NodeType.ENTITY))
    assert store.reclaim_orphans() == 1
    assert store.reclaim_orphans() == 0
    store.close()


def test_export_graph_shape_and_counts(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="b", type=NodeType.CHUNK, doc_id="d1", meta={"k": 1}))
    store.upsert_node(Node(id="a", type=NodeType.DOCUMENT, doc_id="d1"))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    data = store.export_graph()
    assert [n["id"] for n in data["nodes"]] == ["a", "b"]  # 确定性排序
    assert data["nodes"][0]["type"] == NodeType.DOCUMENT.value
    assert data["edges"] == [{"src": "a", "dst": "b", "type": EdgeType.CONTAINS.value}]
    assert len(data["nodes"]) == store.stats()["nodes"]
    store.close()
