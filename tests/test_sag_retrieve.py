from mdgraph.sag_retrieve import SAGResult, SAGRetriever, _cosine
from mdgraph.store.sag_store import SAGStore


class FakeEmbedder:
    """按 token 集合返回稀疏向量；query 与共享 token 的事件 cosine 高。"""

    name = "fake"
    dim = 8
    _VOCAB = ["alice", "bob", "acme", "gpt", "openai", "cat", "dog", "x"]

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            low = t.lower()
            for i, w in enumerate(self._VOCAB):
                if w in low:
                    vec[i] = 1.0
            out.append(vec)
        return out


def _entity(store, eid, name, etype="person"):
    store.upsert_entity(
        id=eid, type=etype, name=name, normalized_name=name.lower(), description=""
    )


def _event(store, eid, chunk_id, *, title, keywords, embedding=None, entities=()):
    store.upsert_event(
        id=eid,
        doc_id="d1",
        chunk_id=chunk_id,
        title=title,
        summary=f"{title} summary",
        content=f"{title} content",
        category="cat",
        keywords=keywords,
        embedding=embedding,
    )
    for ent_id in entities:
        store.link(eid, ent_id)


def test_cosine_zero_vector_returns_zero():
    assert _cosine([0, 0], [1, 1]) == 0.0
    assert _cosine([], [1]) == 0.0
    assert abs(_cosine([1, 0], [1, 0]) - 1.0) < 1e-9


def test_empty_store_returns_empty(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    res = SAGRetriever(store).retrieve("alice")
    assert isinstance(res, SAGResult)
    assert res.events == []
    store.close()


def test_empty_query_returns_empty(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_alice", "Alice")
    _event(store, "ev_1", "c1", title="Alice event", keywords=["alice"], entities=["e_alice"])
    assert SAGRetriever(store).retrieve("   ").events == []
    store.close()


def test_no_seed_no_vector_returns_empty(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_alice", "Alice")
    _event(store, "ev_1", "c1", title="Alice event", keywords=["alice"], entities=["e_alice"])
    # 无 embedder + query token 不匹配任何实体 → 空
    assert SAGRetriever(store).retrieve("zzz nomatch").events == []
    store.close()


def test_entity_match_seeds_event_without_embedder(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_alice", "Alice")
    _event(store, "ev_1", "c1", title="Alice event", keywords=["alice"], entities=["e_alice"])
    res = SAGRetriever(store).retrieve("alice")
    assert [e.event_id for e in res.events] == ["ev_1"]
    assert res.events[0].hop == 0
    assert res.events[0].connected_via == ["e_alice"]
    assert res.trace.query_entities == ["Alice"]
    assert res.trace.seed_event_ids == ["ev_1"]
    store.close()


def test_hyperedge_multi_hop_expansion_records_hop(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    # ev_1(Alice) — 共享 Acme — ev_2(Acme) ；query 只命中 Alice
    _entity(store, "e_alice", "Alice")
    _entity(store, "e_acme", "Acme", etype="organization")
    _event(store, "ev_1", "c1", title="Alice at Acme", keywords=["alice"],
           entities=["e_alice", "e_acme"])
    _event(store, "ev_2", "c2", title="Acme news", keywords=["acme"], entities=["e_acme"])
    res = SAGRetriever(store).retrieve("alice", k=8, max_hops=2)
    hop_by_id = {e.event_id: e.hop for e in res.events}
    assert hop_by_id["ev_1"] == 0
    assert hop_by_id["ev_2"] == 1
    assert "ev_2" in res.trace.expanded_event_ids
    store.close()


def test_max_hops_limits_expansion(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_a", "Alice")
    _entity(store, "e_b", "Bob")
    _entity(store, "e_c", "Cathy")
    # 链：ev_1(a,b) - ev_2(b,c) - ev_3(c)
    _event(store, "ev_1", "c1", title="t1", keywords=["alice"], entities=["e_a", "e_b"])
    _event(store, "ev_2", "c2", title="t2", keywords=[], entities=["e_b", "e_c"])
    _event(store, "ev_3", "c3", title="t3", keywords=[], entities=["e_c"])
    res = SAGRetriever(store).retrieve("alice", k=8, max_hops=1)
    ids = {e.event_id for e in res.events}
    assert "ev_1" in ids and "ev_2" in ids
    assert "ev_3" not in ids  # 超过 1 跳
    store.close()


def test_k_truncation(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_alice", "Alice")
    for i in range(5):
        _event(store, f"ev_{i}", f"c{i}", title=f"Alice {i}", keywords=["alice"],
               entities=["e_alice"])
    res = SAGRetriever(store).retrieve("alice", k=3)
    assert len(res.events) == 3
    assert len(res.trace.ranked_event_ids) == 3
    store.close()


def test_embedder_vector_recall_and_rank(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    emb = FakeEmbedder()
    # ev_vec 无实体但向量与 query 重合 → 靠向量召回进种子
    _event(store, "ev_vec", "c1", title="gpt openai", keywords=[],
           embedding=emb.embed(["gpt openai"])[0])
    _entity(store, "e_alice", "Alice")
    _event(store, "ev_ent", "c2", title="alice", keywords=["alice"],
           embedding=emb.embed(["alice"])[0], entities=["e_alice"])
    res = SAGRetriever(store, embedder=emb).retrieve("gpt", k=8)
    ids = {e.event_id for e in res.events}
    assert "ev_vec" in ids  # 纯向量召回命中
    store.close()


def test_graph_and_trace_shape(tmp_path):
    store = SAGStore(tmp_path / "sag.db")
    _entity(store, "e_alice", "Alice")
    _event(store, "ev_1", "c1", title="Alice event", keywords=["alice"], entities=["e_alice"])
    res = SAGRetriever(store).retrieve("alice")
    node_types = {n["type"] for n in res.graph["nodes"]}
    assert node_types == {"event", "sag_entity"}
    assert all(e["type"] == "has_entity" for e in res.graph["edges"])
    assert res.graph["edges"] == [{"src": "ev_1", "dst": "e_alice", "type": "has_entity"}]
    assert [e.id for e in res.entities] == ["e_alice"]
    assert set(res.trace.model_dump().keys()) == {
        "query_entities",
        "seed_event_ids",
        "expanded_event_ids",
        "ranked_event_ids",
    }
    store.close()


# --- engine.retrieve_sag enrichment ---
def test_engine_retrieve_sag_enriches_source_and_heading(tmp_path):
    from mdgraph.engine import MarkdownGraph
    from mdgraph.ids import sag_event_id

    f = tmp_path / "doc.md"
    f.write_text("# A\n\nAlice content here\n", encoding="utf-8")
    mg = MarkdownGraph(tmp_path / ".mdgraph")
    mg.build([tmp_path])
    chunk = mg.graph_store.list_chunks_by_doc(mg.graph_store.list_documents()[0][0])[0]
    mg.sag_store.upsert_entity(
        id="e_alice", type="person", name="Alice", normalized_name="alice", description=""
    )
    mg.sag_store.upsert_event(
        id=sag_event_id(chunk.id),
        doc_id=chunk.doc_id,
        chunk_id=chunk.id,
        title="Alice event",
        summary="s",
        content="",  # 空 content → 兜底 chunk.text
        category="",
        keywords=["alice"],
        embedding=None,
    )
    mg.sag_store.link(sag_event_id(chunk.id), "e_alice")
    res = mg.retrieve_sag("alice")
    assert res.events
    hit = res.events[0]
    assert hit.source_path.endswith("doc.md")
    assert hit.heading_path == chunk.section_path
    assert hit.content == chunk.text  # 空 content 兜底
    mg.close()


def test_engine_retrieve_sag_empty_store(tmp_path):
    from mdgraph.engine import MarkdownGraph

    mg = MarkdownGraph(tmp_path / ".mdgraph")
    res = mg.retrieve_sag("anything")
    assert res.events == []
    mg.close()
