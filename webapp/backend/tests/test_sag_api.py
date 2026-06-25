"""SAG API tests — fully offline (Mock providers, no network, tmp store).

Covers the /api/sag/* contract:
  * /api/sag/search 409 when no SAG events have been built yet.
  * /api/sag/search 200 with the correct response shape once the SAG tables are
    seeded (events / entities / graph / trace).
  * /api/sag/search 200 (NOT 503) when the engine has NO embedder — SAG must work
    without vectors (entity match + overlap ranking).
  * /api/sag/status shape: built / events / entities / links / has_embedder.
  * /api/sag/build triggers a job (start_sag_build_job monkeypatched to avoid any
    real LLM / background thread), returning {job_id}; 409 when a build is active.

IRON RULE: no real models / network. We seed the SAGStore directly with fixed
events/entities/links (no LLM extraction) and inject the engine via set_engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdgraph import MarkdownGraph
from mdgraph.ids import entity_id, normalize_name, sag_event_id
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)

from webapp.backend import engine_provider, jobs
from webapp.backend.app import app

_DOC = """---
title: Alpha
---

# Alpha

Alpha mentions Bravo and Charlie working together.
"""


def _seed_sag(engine: MarkdownGraph) -> None:
    """Populate the engine's sag.db with one seeded event + two entities + links.

    The event's chunk_id is taken from the real graph store so retrieve_sag can
    backfill source_path / heading_path off the existing chunk.
    """
    docs = engine.graph_store.list_documents()
    doc_id = docs[0][0]
    chunk = engine.graph_store.list_chunks_by_doc(doc_id)[0]

    store = engine.sag_store
    ev_id = sag_event_id(chunk.id)
    embedding = engine.embedder.embed(["Alpha mentions Bravo"])[0] if engine.embedder else None
    store.upsert_event(
        id=ev_id,
        doc_id=doc_id,
        chunk_id=chunk.id,
        title="Alpha works with Bravo",
        summary="Alpha and Bravo collaborate.",
        content="Alpha mentions Bravo and Charlie working together.",
        category="action",
        keywords=["alpha", "bravo"],
        embedding=embedding,
    )
    for name, etype in (("Alpha", "person"), ("Bravo", "person")):
        eid = entity_id(name)
        store.upsert_entity(
            id=eid,
            type=etype,
            name=name,
            normalized_name=normalize_name(name),
            description="",
        )
        store.link(ev_id, eid)


@pytest.fixture()
def sag_store_dir(tmp_path: Path) -> Path:
    """Build a tiny store from one markdown doc, return the store dir."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.md").write_text(_DOC, encoding="utf-8")

    store = tmp_path / "store"
    graph = MarkdownGraph(
        store,
        embedder=DeterministicEmbeddingProvider(),
        llm=MockLLMProvider(),
    )
    graph.build([corpus], root=corpus)
    graph.close()
    return store


@pytest.fixture()
def sag_engine(sag_store_dir: Path) -> MarkdownGraph:
    """Engine (with embedder) over the tmp store, SAG tables empty."""
    eng = MarkdownGraph(
        sag_store_dir,
        embedder=DeterministicEmbeddingProvider(),
        llm=MockLLMProvider(),
    )
    engine_provider.set_engine(eng)
    yield eng
    engine_provider.reset_engine()


@pytest.fixture()
def sag_client(sag_engine: MarkdownGraph) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sag_no_embedder_engine(sag_store_dir: Path) -> MarkdownGraph:
    """Engine WITHOUT an embedder over the tmp store, SAG tables empty."""
    eng = MarkdownGraph(sag_store_dir, embedder=None, llm=None)
    engine_provider.set_engine(eng)
    yield eng
    engine_provider.reset_engine()


@pytest.fixture()
def sag_no_embedder_client(sag_no_embedder_engine: MarkdownGraph) -> TestClient:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# /api/sag/status
# --------------------------------------------------------------------------- #
def test_sag_status_empty(sag_client: TestClient) -> None:
    resp = sag_client.get("/api/sag/status")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("built", "events", "entities", "links", "has_embedder"):
        assert key in body
    assert body["built"] is False
    assert body["events"] == 0
    assert body["entities"] == 0
    assert body["links"] == 0
    assert body["has_embedder"] is True


def test_sag_status_built(sag_client: TestClient, sag_engine: MarkdownGraph) -> None:
    _seed_sag(sag_engine)
    resp = sag_client.get("/api/sag/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["built"] is True
    assert body["events"] == 1
    assert body["entities"] == 2
    assert body["links"] == 2
    assert body["has_embedder"] is True


def test_sag_status_no_embedder(sag_no_embedder_client: TestClient) -> None:
    resp = sag_no_embedder_client.get("/api/sag/status")
    assert resp.status_code == 200
    assert resp.json()["has_embedder"] is False


# --------------------------------------------------------------------------- #
# /api/sag/search
# --------------------------------------------------------------------------- #
def test_sag_search_409_when_not_built(sag_client: TestClient) -> None:
    resp = sag_client.post("/api/sag/search", json={"query": "Alpha", "k": 8})
    assert resp.status_code == 409
    assert "SAG" in resp.json()["detail"]


def test_sag_search_200_shape_when_seeded(
    sag_client: TestClient, sag_engine: MarkdownGraph
) -> None:
    _seed_sag(sag_engine)
    resp = sag_client.post(
        "/api/sag/search", json={"query": "Alpha Bravo", "k": 8, "max_hops": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Top-level shape mirrors SAGSearchResponse.
    for key in ("events", "entities", "graph", "trace"):
        assert key in body
    assert body["events"], "seeded query should return at least one event"

    ev = body["events"][0]
    for key in (
        "event_id",
        "title",
        "summary",
        "content",
        "category",
        "keywords",
        "score",
        "hop",
        "chunk_id",
        "source_path",
        "heading_path",
        "entities",
        "connected_via",
    ):
        assert key in ev
    # source_path / heading_path backfilled from the real chunk.
    assert ev["source_path"]
    # Event carries its typed entities.
    assert ev["entities"]
    assert {"id", "name", "type"} <= set(ev["entities"][0].keys())

    # entities panel (deduped) present.
    assert body["entities"]
    assert {"id", "name", "type"} <= set(body["entities"][0].keys())

    # graph is a Subgraph (event + sag_entity nodes, has_entity edges).
    assert {"nodes", "edges"} <= set(body["graph"].keys())
    node_types = {n["type"] for n in body["graph"]["nodes"]}
    assert "event" in node_types
    assert "sag_entity" in node_types
    if body["graph"]["edges"]:
        assert body["graph"]["edges"][0]["type"] == "has_entity"

    # trace four segments.
    for key in (
        "query_entities",
        "seed_event_ids",
        "expanded_event_ids",
        "ranked_event_ids",
    ):
        assert key in body["trace"]


def test_sag_search_200_when_no_embedder(
    sag_no_embedder_client: TestClient, sag_no_embedder_engine: MarkdownGraph
) -> None:
    _seed_sag(sag_no_embedder_engine)
    resp = sag_no_embedder_client.post(
        "/api/sag/search", json={"query": "Alpha Bravo", "k": 8}
    )
    # Must be 200 (NOT 503) — SAG degrades to entity match + overlap ranking.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["events"], "no-embedder search should still find seeded events"


# --------------------------------------------------------------------------- #
# /api/sag/build
# --------------------------------------------------------------------------- #
def test_sag_build_triggers_job(sag_client: TestClient, monkeypatch) -> None:
    calls: list[bool] = []

    def _fake_start(full: bool) -> str:
        calls.append(full)
        return "fake-job-id"

    monkeypatch.setattr(jobs, "start_sag_build_job", _fake_start)
    resp = sag_client.post("/api/sag/build", json={"full": True})
    assert resp.status_code == 202
    assert resp.json() == {"job_id": "fake-job-id"}
    assert calls == [True]


def test_sag_build_409_when_build_active(sag_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "is_build_active", lambda: True)
    resp = sag_client.post("/api/sag/build", json={"full": False})
    assert resp.status_code == 409
