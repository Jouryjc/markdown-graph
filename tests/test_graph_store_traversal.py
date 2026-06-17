import networkx as nx

from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def build_chain(store):
    # a -CONTAINS-> b -LINKS_TO-> c ; 另有 a -TAGGED-> t
    for nid in ["a", "b", "c", "t"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="b", dst="c", type=EdgeType.LINKS_TO))
    store.upsert_edge(Edge(src="a", dst="t", type=EdgeType.TAGGED))


def test_to_networkx_shape(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    g = store.to_networkx()
    assert isinstance(g, nx.MultiDiGraph)
    assert g.number_of_nodes() == 4
    assert g.number_of_edges() == 3
    store.close()


def test_neighbors_one_hop_undirected(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # b 的一跳邻居：a（入边 CONTAINS）与 c（出边 LINKS_TO）
    assert store.neighbors("b", hops=1) == {"a", "c"}
    store.close()


def test_neighbors_two_hops(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # a 两跳：b、t（一跳），再到 c（经 b）
    assert store.neighbors("a", hops=2) == {"b", "t", "c"}
    store.close()


def test_neighbors_filtered_by_edge_type(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    # 仅沿 CONTAINS：a 的一跳只有 b（TAGGED 被过滤）
    assert store.neighbors("a", edge_types=[EdgeType.CONTAINS], hops=1) == {"b"}
    store.close()


def test_neighbors_missing_node_returns_empty(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.neighbors("nope") == set()
    store.close()
