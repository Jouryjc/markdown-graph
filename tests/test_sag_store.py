from mdgraph.store.sag_store import SAGStore


def make_store(tmp_path):
    return SAGStore(tmp_path / "sag.db")


def _add_event(store, *, id, chunk_id, doc_id="d1", title="T", embedding=None, **kw):
    store.upsert_event(
        id=id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        title=title,
        summary=kw.get("summary", "S"),
        content=kw.get("content", "C"),
        category=kw.get("category", ""),
        keywords=kw.get("keywords", []),
        embedding=embedding,
    )


def test_schema_and_empty_counts(tmp_path):
    store = make_store(tmp_path)
    assert store.counts() == {"events": 0, "entities": 0, "links": 0}
    assert store.all_event_ids() == []
    assert store.iter_event_embeddings() == []
    store.close()


def test_upsert_event_and_fetch(tmp_path):
    store = make_store(tmp_path)
    _add_event(
        store,
        id="ev_1",
        chunk_id="c1",
        keywords=["a", "b"],
        embedding=[0.1, 0.2],
    )
    rows = store.events_by_ids(["ev_1"])
    assert rows["ev_1"]["keywords"] == ["a", "b"]
    assert rows["ev_1"]["embedding"] == [0.1, 0.2]
    assert store.iter_event_embeddings() == [("ev_1", [0.1, 0.2])]
    assert store.all_event_ids() == ["ev_1"]
    store.close()


def test_event_without_embedding_is_null(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1", embedding=None)
    assert store.events_by_ids(["ev_1"])["ev_1"]["embedding"] is None
    assert store.iter_event_embeddings() == []
    store.close()


def test_upsert_entity_merge_only_fills_empty(tmp_path):
    store = make_store(tmp_path)
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    # 补空 type/description
    store.upsert_entity(
        id="e1", type="person", name="X", normalized_name="x", description="desc"
    )
    row = store.entities_by_ids(["e1"])["e1"]
    assert row["type"] == "person"
    assert row["description"] == "desc"
    # 已有值不被覆盖
    store.upsert_entity(
        id="e1", type="organization", name="X", normalized_name="x", description="other"
    )
    row = store.entities_by_ids(["e1"])["e1"]
    assert row["type"] == "person"
    assert row["description"] == "desc"
    store.close()


def test_link_insert_or_ignore(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1")
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    store.link("ev_1", "e1")
    store.link("ev_1", "e1")  # 幂等
    assert store.counts()["links"] == 1
    store.close()


def test_match_entities_by_name_dedup(tmp_path):
    store = make_store(tmp_path)
    store.upsert_entity(id="e1", type="person", name="Alice", normalized_name="alice", description="")
    store.upsert_entity(id="e2", type="org", name="Acme", normalized_name="acme corp", description="")
    store.upsert_entity(id="e3", type="", name="Bob", normalized_name="bob", description="")
    # token "a" 命中 e1(alice)、e2(acme corp)；"b" 命中 e3(bob)，且与 "a" 对 acme 的命中去重
    matched = store.match_entities_by_name(["a", "b"])
    ids = sorted(m["id"] for m in matched)
    assert ids == ["e1", "e2", "e3"]
    # 空 token 跳过
    assert store.match_entities_by_name([""]) == []
    assert store.match_entities_by_name([]) == []
    store.close()


def test_event_ids_for_entities_and_exclude(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1")
    _add_event(store, id="ev_2", chunk_id="c2")
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    store.link("ev_1", "e1")
    store.link("ev_2", "e1")
    assert store.event_ids_for_entities(["e1"]) == ["ev_1", "ev_2"]
    assert store.event_ids_for_entities(["e1"], exclude={"ev_1"}) == ["ev_2"]
    assert store.event_ids_for_entities([]) == []
    store.close()


def test_entity_ids_for_events(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1")
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    store.upsert_entity(id="e2", type="", name="Y", normalized_name="y", description="")
    store.link("ev_1", "e1")
    store.link("ev_1", "e2")
    out = store.entity_ids_for_events(["ev_1", "ev_2"])
    assert out["ev_1"] == ["e1", "e2"]
    assert out["ev_2"] == []
    store.close()


def test_delete_event_by_chunk_removes_links(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1")
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    store.link("ev_1", "e1")
    store.delete_event_by_chunk("c1")
    assert store.counts()["events"] == 0
    assert store.counts()["links"] == 0
    # 孤立 entity 不即时回收
    assert store.counts()["entities"] == 1
    store.close()


def test_delete_by_chunk_is_incremental_replace(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_old", chunk_id="c1", title="old")
    store.delete_event_by_chunk("c1")
    _add_event(store, id="ev_new", chunk_id="c1", title="new")
    rows = store.events_by_ids(["ev_new"])
    assert rows["ev_new"]["title"] == "new"
    assert store.counts()["events"] == 1
    store.close()


def test_clear_wipes_all_tables(tmp_path):
    store = make_store(tmp_path)
    _add_event(store, id="ev_1", chunk_id="c1")
    store.upsert_entity(id="e1", type="", name="X", normalized_name="x", description="")
    store.link("ev_1", "e1")
    store.clear()
    assert store.counts() == {"events": 0, "entities": 0, "links": 0}
    store.close()


def test_transaction_commits_and_persists(tmp_path):
    db = tmp_path / "sag.db"
    s1 = SAGStore(db)
    with s1.transaction():
        _add_event(s1, id="ev_1", chunk_id="c1")
    s1.close()
    s2 = SAGStore(db)
    assert s2.counts()["events"] == 1
    s2.close()


def test_transaction_rolls_back_on_error(tmp_path):
    store = make_store(tmp_path)
    try:
        with store.transaction():
            store.upsert_event(
                id="ev_1",
                doc_id="d1",
                chunk_id="c1",
                title="T",
                summary="S",
                content="C",
                category="",
                keywords=[],
                embedding=None,
                commit=False,
            )
            raise ValueError("boom")
    except ValueError:
        pass
    assert store.counts()["events"] == 0
    store.close()
