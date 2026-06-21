"""Reusable test fixtures: build a tiny offline store with Mock providers and
point the engine singleton at it, then yield a FastAPI TestClient.

IRON RULE: no real models / network. Uses DeterministicEmbeddingProvider and
MockLLMProvider from mdgraph.providers.mock only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdgraph import MarkdownGraph
from mdgraph.providers.mock import (
    DeterministicEmbeddingProvider,
    MockLLMProvider,
)

from webapp.backend import engine_provider
from webapp.backend.app import app

# Two tiny interlinked markdown docs so retrieval, links, entities and the graph
# all have something to chew on.
_DOC_ALPHA = """---
title: Alpha
tags: [demo]
---

# Alpha

Alpha mentions Bravo and connects to [Beta](beta.md).

## Details

The Alpha system talks about Charlie and Bravo working together.
"""

_DOC_BETA = """---
title: Beta
---

# Beta

Beta references Charlie. See [Alpha](alpha.md) for context.
"""


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    """Create a tiny markdown corpus, build it into a store, return store dir."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.md").write_text(_DOC_ALPHA, encoding="utf-8")
    (corpus / "beta.md").write_text(_DOC_BETA, encoding="utf-8")

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
def engine(store_dir: Path) -> MarkdownGraph:
    """Engine singleton pointed at the tmp store (Mock providers)."""
    eng = MarkdownGraph(
        store_dir,
        embedder=DeterministicEmbeddingProvider(),
        llm=MockLLMProvider(),
    )
    engine_provider.set_engine(eng)
    yield eng
    engine_provider.reset_engine()


@pytest.fixture()
def client(engine: MarkdownGraph) -> TestClient:
    """TestClient backed by the tmp-store engine."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def no_embedder_engine(store_dir: Path) -> MarkdownGraph:
    """Engine singleton WITHOUT an embedder (graph reads work, query/index 503)."""
    eng = MarkdownGraph(store_dir, embedder=None, llm=None)
    engine_provider.set_engine(eng)
    yield eng
    engine_provider.reset_engine()


@pytest.fixture()
def no_embedder_client(no_embedder_engine: MarkdownGraph) -> TestClient:
    """TestClient backed by an embedder-less engine (for 503 paths)."""
    with TestClient(app) as c:
        yield c
