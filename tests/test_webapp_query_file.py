"""POST /api/query mode=="file" — LLM 文件检索分支的 webapp 契约测试。

约定（沿用切片铁律，绝不联网/调真实模型）：
- 用 ``engine_provider.set_engine`` 注入桩引擎；桩的 ``retrieve_file`` 返回固定
  ``RetrievalResult``，``store_dir`` 指向 tmp 目录。
- 桩刻意把 ``embedder=None`` / ``vector_store=None``，以证明 file 分支不触发
  require_embedder 的 503。
- 每个测试结束 ``reset_engine`` 清掉桩，避免跨用例泄漏到真实单例。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdgraph.retrieve import Context as EngineContext
from mdgraph.retrieve import RetrievalResult
from webapp.backend import engine_provider
from webapp.backend.app import create_app


class StubEngine:
    """最小桩引擎：仅实现 query 路由 file/vector 分支会触碰的属性/方法。

    - ``embedder`` / ``vector_store`` 恒为 None：证明 file 不依赖它们。
    - ``store_dir`` 指向 tmp；其下是否存在 ``source/`` 决定 200 vs 409。
    """

    def __init__(self, store_dir: Path, file_result: RetrievalResult | None = None):
        self.store_dir = store_dir
        self.embedder = None
        self.vector_store = None
        self.graph_store = None
        self._file_result = file_result or RetrievalResult()
        self.retrieve_file_calls: list[tuple[str, int]] = []

    def retrieve_file(self, query: str, k: int = 8) -> RetrievalResult:
        self.retrieve_file_calls.append((query, k))
        return self._file_result


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _reset_engine():
    yield
    engine_provider.reset_engine()


def _make_source_dir(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "doc.md").write_text("# hi\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# mode=="file" 正常路径：有 source/ + 桩返回 contexts → 200、映射正确、子图空
# ---------------------------------------------------------------------------
def test_file_mode_returns_contexts_and_empty_subgraph(client, tmp_path):
    store_dir = _make_source_dir(tmp_path)
    file_result = RetrievalResult(
        contexts=[
            EngineContext(
                chunk_id="file::a.md::0",
                text="段落甲",
                score=1.0,
                doc_id="",
                source_path="a.md",
                heading_path="",
            ),
            EngineContext(
                chunk_id="file::sub/b.md::1",
                text="段落乙",
                score=0.5,
                doc_id="",
                source_path="sub/b.md",
                heading_path="",
            ),
        ],
        subgraph={"nodes": [], "edges": []},
    )
    stub = StubEngine(store_dir, file_result)
    engine_provider.set_engine(stub)

    resp = client.post("/api/query", json={"query": "找点东西", "mode": "file", "k": 5})
    assert resp.status_code == 200
    body = resp.json()

    # contexts 逐字段映射，from_graph 恒 False。
    assert [c["chunk_id"] for c in body["contexts"]] == [
        "file::a.md::0",
        "file::sub/b.md::1",
    ]
    assert [c["text"] for c in body["contexts"]] == ["段落甲", "段落乙"]
    assert [c["source_path"] for c in body["contexts"]] == ["a.md", "sub/b.md"]
    assert all(c["from_graph"] is False for c in body["contexts"])

    # 子图恒空。
    assert body["subgraph"] == {"nodes": [], "edges": []}

    # retrieve_file 被以 (query, k) 调用一次，不依赖 graph_weight/hops。
    assert stub.retrieve_file_calls == [("找点东西", 5)]


# ---------------------------------------------------------------------------
# 证明 file 不触发 503：桩 embedder/vector_store 均为 None 仍 200
# ---------------------------------------------------------------------------
def test_file_mode_does_not_require_embedder(client, tmp_path):
    store_dir = _make_source_dir(tmp_path)
    stub = StubEngine(store_dir, RetrievalResult())  # 空结果也算成功
    assert stub.embedder is None and stub.vector_store is None
    engine_provider.set_engine(stub)

    resp = client.post("/api/query", json={"query": "q", "mode": "file"})
    # 关键断言：缺 embedder 不 503，file 分支跳过 require_embedder。
    assert resp.status_code == 200
    assert resp.json()["contexts"] == []
    assert resp.json()["subgraph"] == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# source/ 缺失 → 409 + 清晰文案
# ---------------------------------------------------------------------------
def test_file_mode_missing_source_returns_409(client, tmp_path):
    # store_dir 下没有 source/ 子目录。
    stub = StubEngine(tmp_path, RetrievalResult())
    engine_provider.set_engine(stub)

    resp = client.post("/api/query", json={"query": "q", "mode": "file"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "该 store 未持久化源文件，请重建索引后再用 File 检索"
    # 409 路径不应触达 retrieve_file。
    assert stub.retrieve_file_calls == []


# ---------------------------------------------------------------------------
# 回归：mode=="vector" 在缺 embedder 的桩下仍走 require_embedder → 503
# （证明 file 分支没有影响 dual/vector 的既有行为/契约）
# ---------------------------------------------------------------------------
def test_vector_mode_still_requires_embedder_503(client, tmp_path):
    stub = StubEngine(tmp_path, RetrievalResult())  # embedder/vector_store None
    engine_provider.set_engine(stub)

    resp = client.post("/api/query", json={"query": "q", "mode": "vector"})
    assert resp.status_code == 503
    # file 没被误调。
    assert stub.retrieve_file_calls == []
