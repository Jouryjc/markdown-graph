"""Backend API tests — fully offline via Mock providers (see conftest).

IRON RULE: no real models, no network. Every fixture builds a tiny tmp store
with DeterministicEmbeddingProvider + MockLLMProvider.
"""

from __future__ import annotations


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
def test_health(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def test_stats(client) -> None:
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    # All contract keys present.
    for key in (
        "documents",
        "sections",
        "chunks",
        "entities",
        "tags",
        "nodes",
        "edges",
        "vectors",
    ):
        assert key in body
    assert body["documents"] == 2
    assert body["chunks"] == 3
    assert body["sections"] == 3
    assert body["entities"] >= 1
    assert body["tags"] == 1
    assert body["vectors"] == 3  # embedder configured -> vectors built
    assert body["nodes"] > 0 and body["edges"] > 0


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #
def test_query_dual(client) -> None:
    resp = client.post(
        "/api/query",
        json={"query": "Alpha Bravo Charlie", "k": 8, "mode": "dual"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contexts"], "dual query should return contexts"
    c0 = body["contexts"][0]
    for key in (
        "chunk_id",
        "text",
        "score",
        "doc_id",
        "source_path",
        "heading_path",
        "from_graph",
    ):
        assert key in c0
    # doc_id is the document NODE id (search -> document navigation keys on it).
    assert c0["doc_id"].startswith("d_")
    assert c0["chunk_id"].startswith(c0["doc_id"])
    # dual mode populates a subgraph.
    assert body["subgraph"]["nodes"]


def test_query_vector_mode_empty_subgraph(client) -> None:
    resp = client.post(
        "/api/query",
        json={"query": "Alpha Bravo Charlie", "k": 8, "mode": "vector"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contexts"]
    # Pure vector mode => empty subgraph and nothing flagged from_graph.
    assert body["subgraph"]["nodes"] == []
    assert body["subgraph"]["edges"] == []
    assert all(c["from_graph"] is False for c in body["contexts"])


def test_query_from_graph_flag(client) -> None:
    # query "Beta" at k=1 with a strong graph_weight pulls the linked Beta chunk
    # (absent from the pure-vector top-1) in via graph expansion => from_graph.
    resp = client.post(
        "/api/query",
        json={
            "query": "Beta",
            "k": 1,
            "mode": "dual",
            "graph_weight": 2.0,
            "per_doc_cap": None,
            "hops": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(c["from_graph"] for c in body["contexts"]), (
        "expected at least one graph-brought context flagged from_graph"
    )


def test_query_rejects_nonpositive_k(client) -> None:
    # k<=0 must be a clean 422 (validation), not a 500 from the ANN engine.
    for bad_k in (0, -1):
        resp = client.post(
            "/api/query",
            json={"query": "Alpha", "k": bad_k, "mode": "vector"},
        )
        assert resp.status_code == 422, f"k={bad_k} should be rejected"


def test_query_503_without_embedder(no_embedder_client) -> None:
    resp = no_embedder_client.post(
        "/api/query", json={"query": "anything", "mode": "vector"}
    )
    assert resp.status_code == 503
    assert "detail" in resp.json()


# --------------------------------------------------------------------------- #
# graph
# --------------------------------------------------------------------------- #
def test_graph_full(client) -> None:
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is False
    assert body["total_nodes"] == len(body["nodes"])
    assert body["total_nodes"] > 0
    # nodes are id-sorted.
    ids = [n["id"] for n in body["nodes"]]
    assert ids == sorted(ids)


def test_graph_limit_truncated(client) -> None:
    full = client.get("/api/graph").json()
    total = full["total_nodes"]
    limit = 2
    assert total > limit  # store has more than 2 nodes
    resp = client.get(f"/api/graph?limit={limit}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert body["total_nodes"] == total
    assert len(body["nodes"]) == limit
    # Keeps the first `limit` id-sorted nodes.
    assert [n["id"] for n in body["nodes"]] == [n["id"] for n in full["nodes"][:limit]]
    kept = {n["id"] for n in body["nodes"]}
    # Every retained edge has both endpoints among kept nodes.
    for e in body["edges"]:
        assert e["src"] in kept and e["dst"] in kept


def test_graph_limit_not_truncated_when_ge_total(client) -> None:
    total = client.get("/api/graph").json()["total_nodes"]
    resp = client.get(f"/api/graph?limit={total}")
    body = resp.json()
    assert body["truncated"] is False
    assert len(body["nodes"]) == total


def test_graph_rejects_negative_limit(client) -> None:
    # A negative limit must 422, not silently negative-slice (dropping nodes
    # while reporting truncated=true).
    resp = client.get("/api/graph?limit=-1")
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# graph/expand
# --------------------------------------------------------------------------- #
def test_graph_expand(client) -> None:
    docs = client.get("/api/documents").json()
    seed = docs[0]["id"]
    resp = client.get(f"/api/graph/expand?seeds={seed}&hops=2")
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert seed in node_ids
    # expansion should reach beyond the seed itself.
    assert len(node_ids) > 1


# --------------------------------------------------------------------------- #
# node
# --------------------------------------------------------------------------- #
def test_node_detail(client) -> None:
    docs = client.get("/api/documents").json()
    doc_id = docs[0]["id"]
    resp = client.get(f"/api/node/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["node"]["id"] == doc_id
    assert body["node"]["type"] == "document"
    assert body["neighbors"], "document node should have neighbors (contains sections)"
    n0 = body["neighbors"][0]
    for key in ("id", "type", "meta", "edge_type", "direction"):
        assert key in n0
    assert all(n["direction"] in ("out", "in") for n in body["neighbors"])


def test_node_404(client) -> None:
    resp = client.get("/api/node/does_not_exist")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
def test_documents_list(client) -> None:
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 2
    ids = [d["id"] for d in docs]
    assert ids == sorted(ids)
    for d in docs:
        assert d["path"].endswith(".md")
        assert d["chunk_count"] >= 1


def test_document_detail_and_links(client) -> None:
    docs = client.get("/api/documents").json()
    # find alpha.md (it links to beta.md).
    alpha = next(d for d in docs if d["path"].endswith("alpha.md"))
    beta = next(d for d in docs if d["path"].endswith("beta.md"))
    resp = client.get(f"/api/document/{alpha['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document"]["id"] == alpha["id"]
    assert body["document"]["path"].endswith("alpha.md")
    assert body["document"]["frontmatter"].get("title") == "Alpha"
    assert body["chunks"], "alpha should have chunks"
    # alpha links to beta via a markdown link.
    assert beta["id"] in body["links"]
    # never links to itself.
    assert alpha["id"] not in body["links"]


def test_document_404(client) -> None:
    resp = client.get("/api/document/nope")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# --------------------------------------------------------------------------- #
# entities
# --------------------------------------------------------------------------- #
def test_entities(client) -> None:
    resp = client.get("/api/entities?limit=20")
    assert resp.status_code == 200
    ents = resp.json()
    assert ents, "expected entities from the mock extractor"
    for e in ents:
        for key in ("id", "name", "type", "mentions"):
            assert key in e
    # sorted by mentions desc then id.
    keyed = [(-e["mentions"], e["id"]) for e in ents]
    assert keyed == sorted(keyed)
    assert ents[0]["mentions"] >= 1


def test_entities_limit(client) -> None:
    resp = client.get("/api/entities?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) <= 2


def test_entities_rejects_negative_limit(client) -> None:
    # Negative limit must 422, not negative-slice (returning N-1 entities).
    resp = client.get("/api/entities?limit=-1")
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# index (synchronous build) + 503 path
# --------------------------------------------------------------------------- #
def test_index_503_without_embedder(no_embedder_client) -> None:
    resp = no_embedder_client.post("/api/index", json={"paths": [], "full": False})
    assert resp.status_code == 503
    assert "detail" in resp.json()
