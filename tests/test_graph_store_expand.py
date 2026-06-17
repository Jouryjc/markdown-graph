from mdgraph.models import Edge, EdgeType, Node, NodeType
from mdgraph.store.graph_store import GraphStore


def build_chain(store):
    # a -CONTAINS-> b -LINKS_TO-> c -MENTIONS-> e ; d 孤立
    for nid in ["a", "b", "c", "e", "d"]:
        store.upsert_node(Node(id=nid, type=NodeType.CHUNK))
    store.upsert_edge(Edge(src="a", dst="b", type=EdgeType.CONTAINS))
    store.upsert_edge(Edge(src="b", dst="c", type=EdgeType.LINKS_TO))
    store.upsert_edge(Edge(src="c", dst="e", type=EdgeType.MENTIONS))


def test_expand_multi_source_distances(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["a"], hops=2) == {"b": 1, "c": 2}
    store.close()


def test_expand_excludes_seeds(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    dist = store.expand(["a", "b"], hops=1)
    assert "a" not in dist and "b" not in dist
    assert dist.get("c") == 1
    store.close()


def test_expand_filters_edge_types(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["a"], edge_types=[EdgeType.CONTAINS], hops=2) == {"b": 1}
    store.close()


def test_expand_missing_seed_ignored(tmp_path):
    store = GraphStore(tmp_path / "g.db")
    build_chain(store)
    assert store.expand(["nope"], hops=2) == {}
    store.close()
