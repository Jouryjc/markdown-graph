"""POST /api/query — vector / dual retrieval with graph-expansion flagging.

Contract:
- mode="vector": Retriever(vector_store, embedder, graph_store=None).retrieve(...)
  (pure vector, empty subgraph).
- mode="dual": Retriever(vector_store, embedder, graph_store=graph_store,
  graph_weight=body.graph_weight, per_doc_cap=body.per_doc_cap).retrieve(
  query, k, hops).
- from_graph: true when a returned chunk_id is NOT among the top-k pure-vector
  hits for the same query. Computed by also running the pure-vector ranking.
- embedder/vector store unavailable => HTTP 503 with {detail:"..."}.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from mdgraph.retrieve import Retriever

from ..engine_provider import EngineUnavailable, get_engine, require_embedder
from ..schemas import Context, GraphEdge, GraphNode, QueryRequest, QueryResponse, Subgraph

router = APIRouter(prefix="/api", tags=["query"])


def _to_subgraph(raw: dict) -> Subgraph:
    return Subgraph(
        nodes=[
            GraphNode(id=n["id"], type=n["type"], meta=n.get("meta", {}))
            for n in raw.get("nodes", [])
        ],
        edges=[
            GraphEdge(src=e["src"], dst=e["dst"], type=e["type"])
            for e in raw.get("edges", [])
        ],
    )


def _query_file(body: QueryRequest) -> QueryResponse:
    """LLM 文件检索分支。

    与 dual/vector 不同，File 检索独立于 embedder/vector：
    - 只需 ``get_engine()``（图/store 可用即可，缺 embedder 不触发 503）。
    - 需要 build 时持久化的 ``store_dir/source/``；缺失则 409，提示重建索引。
    - 子图恒为空（File 方案不产出图）。
    - LLM/网络失败由 ``retrieve_file`` 降级为空 contexts（200 空列表），不抛崩。
    """
    engine = get_engine()
    source_dir = engine.store_dir / "source"
    if not source_dir.is_dir():
        raise HTTPException(
            status_code=409,
            detail="该 store 未持久化源文件，请重建索引后再用 File 检索",
        )
    result = engine.retrieve_file(body.query, k=body.k)
    contexts = [
        Context(
            chunk_id=c.chunk_id,
            text=c.text,
            score=c.score,
            doc_id=c.doc_id,
            source_path=c.source_path,
            heading_path=c.heading_path,
            from_graph=False,
        )
        for c in result.contexts
    ]
    return QueryResponse(contexts=contexts, subgraph=Subgraph())


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest) -> QueryResponse:
    if body.mode == "file":
        return _query_file(body)

    try:
        engine = require_embedder()
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Pure-vector top-k chunk ids for the same query — the baseline used to flag
    # which returned chunks were brought in only by graph expansion (from_graph).
    vector_retriever = Retriever(
        engine.vector_store, engine.embedder, graph_store=None
    )
    vector_result = vector_retriever.retrieve(body.query, k=body.k)
    vector_chunk_ids = {c.chunk_id for c in vector_result.contexts}

    if body.mode == "vector":
        result = vector_result
    else:  # "dual"
        retriever = Retriever(
            engine.vector_store,
            engine.embedder,
            graph_store=engine.graph_store,
            graph_weight=body.graph_weight,
            per_doc_cap=body.per_doc_cap,
        )
        result = retriever.retrieve(body.query, k=body.k, hops=body.hops)

    contexts = [
        Context(
            chunk_id=c.chunk_id,
            text=c.text,
            score=c.score,
            doc_id=c.doc_id,
            source_path=c.source_path,
            heading_path=c.heading_path,
            # In pure-vector mode nothing is "from graph"; in dual mode a chunk is
            # graph-brought when it is absent from the vector baseline.
            from_graph=(body.mode == "dual" and c.chunk_id not in vector_chunk_ids),
        )
        for c in result.contexts
    ]

    return QueryResponse(contexts=contexts, subgraph=_to_subgraph(result.subgraph))
