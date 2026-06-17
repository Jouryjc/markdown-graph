from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def test_subgraph_includes_nodes_and_connectors(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    for nid, t in [("c1", NodeType.CHUNK), ("c2", NodeType.CHUNK), ("e1", NodeType.ENTITY)]:
        store.upsert_node(Node(id=nid, type=t, meta={"name": nid}))
    store.upsert_edge(Edge(src="c1", dst="e1", type=EdgeType.MENTIONS))
    store.upsert_edge(Edge(src="c2", dst="e1", type=EdgeType.MENTIONS))
    sg = store.subgraph(["c1", "c2"])
    assert {n["id"] for n in sg["nodes"]} == {"c1", "c2", "e1"}  # e1 是 1 跳连接器
    types = {n["id"]: n["type"] for n in sg["nodes"]}
    assert types["e1"] == NodeType.ENTITY.value
    pairs = {(e["src"], e["dst"], e["type"]) for e in sg["edges"]}
    assert ("c1", "e1", EdgeType.MENTIONS.value) in pairs
    assert ("c2", "e1", EdgeType.MENTIONS.value) in pairs
    store.close()


def test_subgraph_isolated_node(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    store.upsert_node(Node(id="x", type=NodeType.CHUNK))
    sg = store.subgraph(["x"])
    assert [n["id"] for n in sg["nodes"]] == ["x"]
    assert sg["edges"] == []
    store.close()


def test_subgraph_deterministic_order(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    for nid in ["b", "a", "c"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    sg = store.subgraph(["a", "b", "c"])
    assert [n["id"] for n in sg["nodes"]] == ["a", "b", "c"]
    store.close()
