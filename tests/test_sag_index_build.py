from mdgraph.engine import MarkdownGraph
from mdgraph.ids import entity_id, sag_event_id
from mdgraph.providers.mock import DeterministicEmbeddingProvider
from mdgraph.providers.sag_extractor import SAGEntity, SAGEvent


def write(tmp_path, name, content):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


class FakeExtractor:
    """按 chunk 文本返回固定事件；含 None（提取失败）与受控实体。"""

    def __init__(self, by_text=None, default=None):
        self.by_text = by_text or {}
        self.default = default
        self.calls = []

    def extract_event(self, content, heading=None, doc_title=None):
        self.calls.append((content, heading, doc_title))
        for key, ev in self.by_text.items():
            if key in content:
                return ev
        return self.default


def _ev(title, entities):
    return SAGEvent(
        title=title,
        summary=f"{title} summary",
        content=f"{title} content",
        category="cat",
        keywords=[title.lower()],
        entities=entities,
    )


def _build_graph(tmp_path, embedder=None):
    write(tmp_path, "a.md", "# A\n\nAlpha relates to Beta\n")
    mg = MarkdownGraph(tmp_path / ".mdgraph", embedder=embedder)
    mg.build([tmp_path])
    return mg


def test_build_sag_index_persists_three_tables(tmp_path):
    mg = _build_graph(tmp_path)
    extractor = FakeExtractor(
        default=_ev(
            "Event",
            [SAGEntity(type="person", name="Alice"), SAGEntity(type="org", name="Acme")],
        )
    )
    report = mg.build_sag_index(extractor=extractor)
    counts = mg.sag_store.counts()
    assert counts["events"] >= 1
    assert counts["entities"] == 2
    assert counts["links"] == 2 * counts["events"]
    assert report["failed"] == 0
    assert report["events"] == counts["events"]
    mg.close()


def test_build_sag_index_event_id_from_chunk(tmp_path):
    mg = _build_graph(tmp_path)
    chunks = mg.graph_store.list_chunks_by_doc(mg.graph_store.list_documents()[0][0])
    extractor = FakeExtractor(default=_ev("E", [SAGEntity(type="person", name="Alice")]))
    mg.build_sag_index(extractor=extractor)
    expected = sag_event_id(chunks[0].id)
    assert expected in mg.sag_store.all_event_ids()
    mg.close()


def test_build_sag_index_dedup_entities_by_normalized_name(tmp_path):
    mg = _build_graph(tmp_path)
    # 同一事件出现 "Alice" 与 "  alice " → 规范化后同 id，去重为一条
    extractor = FakeExtractor(
        default=_ev(
            "E",
            [
                SAGEntity(type="person", name="Alice", description="first"),
                SAGEntity(type="", name="  alice ", description="second"),
            ],
        )
    )
    mg.build_sag_index(extractor=extractor)
    assert mg.sag_store.counts()["entities"] == 1
    row = mg.sag_store.entities_by_ids([entity_id("Alice")])[entity_id("Alice")]
    # 合并保留首个非空 type/description
    assert row["type"] == "person"
    assert row["description"] == "first"
    mg.close()


def test_build_sag_index_counts_failed(tmp_path):
    mg = _build_graph(tmp_path)
    extractor = FakeExtractor(default=None)  # 永远提取失败
    report = mg.build_sag_index(extractor=extractor)
    assert report["events"] == 0
    assert report["failed"] >= 1
    mg.close()


def test_build_sag_index_incremental_overwrites_by_chunk(tmp_path):
    mg = _build_graph(tmp_path)
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("Old", [SAGEntity(type="person", name="Alice")]))
    )
    chunk_id = mg.graph_store.list_chunks_by_doc(
        mg.graph_store.list_documents()[0][0]
    )[0].id
    ev_id = sag_event_id(chunk_id)
    assert mg.sag_store.events_by_ids([ev_id])[ev_id]["title"] == "Old"
    # 重建非 full：同 chunk 覆盖为新事件
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("New", [SAGEntity(type="person", name="Bob")]))
    )
    assert mg.sag_store.events_by_ids([ev_id])[ev_id]["title"] == "New"
    assert mg.sag_store.counts()["events"] == 1
    mg.close()


def test_build_sag_index_full_clears_first(tmp_path):
    mg = _build_graph(tmp_path)
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("E", [SAGEntity(type="person", name="Alice")]))
    )
    # full=True 先清空；这次 extractor 全失败 → 无事件残留
    report = mg.build_sag_index(extractor=FakeExtractor(default=None), full=True)
    assert report["events"] == 0
    assert mg.sag_store.counts()["events"] == 0
    mg.close()


def test_build_sag_index_stores_embedding_when_embedder(tmp_path):
    embedder = DeterministicEmbeddingProvider(dim=16)
    mg = _build_graph(tmp_path, embedder=embedder)
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("E", [SAGEntity(type="person", name="Alice")])),
        embedder=embedder,
    )
    assert mg.sag_store.iter_event_embeddings()
    mg.close()


def test_build_sag_index_no_embedder_stores_null(tmp_path):
    mg = _build_graph(tmp_path)  # no embedder
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("E", [SAGEntity(type="person", name="Alice")]))
    )
    assert mg.sag_store.iter_event_embeddings() == []
    mg.close()


def test_build_sag_index_progress_reports_sag_phase(tmp_path):
    mg = _build_graph(tmp_path)
    events = []
    mg.build_sag_index(
        extractor=FakeExtractor(default=_ev("E", [SAGEntity(type="person", name="Alice")])),
        progress=lambda phase, done, total: events.append((phase, done, total)),
    )
    assert events
    assert all(p == "sag" for p, _, _ in events)
    assert events[-1][1] == events[-1][2]  # 最终 done == total
    mg.close()
