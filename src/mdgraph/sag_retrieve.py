"""SAG Fast 检索：query 实体匹配 ∪ 事件向量召回 → 种子事件 → 沿共享实体多跳扩展
（动态超边）→ 粗排 → top-k。查询期不调 LLM；embedder 可选。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mdgraph.ids import normalize_name


def _cosine(a: list[float], b: list[float]) -> float:
    """纯函数余弦相似度；任一为零向量（或长度不匹配）返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SAGEntityRef(BaseModel):
    id: str
    name: str
    type: str = ""


class SAGEventHit(BaseModel):
    event_id: str
    title: str
    summary: str
    content: str
    category: str = ""
    keywords: list[str] = Field(default_factory=list)
    score: float
    hop: int = 0
    chunk_id: str = ""
    source_path: str = ""
    heading_path: str = ""
    entities: list[SAGEntityRef] = Field(default_factory=list)
    connected_via: list[str] = Field(default_factory=list)


class SAGTrace(BaseModel):
    query_entities: list[str] = Field(default_factory=list)
    seed_event_ids: list[str] = Field(default_factory=list)
    expanded_event_ids: list[str] = Field(default_factory=list)
    ranked_event_ids: list[str] = Field(default_factory=list)


class SAGResult(BaseModel):
    events: list[SAGEventHit] = Field(default_factory=list)
    entities: list[SAGEntityRef] = Field(default_factory=list)
    graph: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})
    trace: SAGTrace = Field(default_factory=SAGTrace)


class SAGRetriever:
    def __init__(self, sag_store, embedder=None) -> None:
        self.sag_store = sag_store
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 8, max_hops: int = 2) -> SAGResult:
        if not query.strip():
            return SAGResult()

        # 1. 种子实体：规范化 query 分词，过滤长度≤1。
        tokens = [t for t in normalize_name(query).split() if len(t) > 1]
        seed_entities = self.sag_store.match_entities_by_name(tokens) if tokens else []
        seed_entity_ids = [e["id"] for e in seed_entities]
        query_entities = [e["name"] for e in seed_entities]

        # 2. 实体 → 种子事件。
        seed_event_ids = self.sag_store.event_ids_for_entities(seed_entity_ids)

        # 3. 事件向量召回（有 embedder 时附加）。
        qvec: list[float] | None = None
        vector_event_ids: list[str] = []
        if self.embedder is not None:
            qvec = self.embedder.embed([query])[0]
            scored = [
                (eid, _cosine(qvec, vec))
                for eid, vec in self.sag_store.iter_event_embeddings()
            ]
            scored.sort(key=lambda x: (-x[1], x[0]))
            vector_event_ids = [eid for eid, _ in scored[: max(k, 10)]]

        seeds: list[str] = []
        seen_seed: set[str] = set()
        for eid in seed_event_ids + vector_event_ids:
            if eid not in seen_seed:
                seen_seed.add(eid)
                seeds.append(eid)

        # 无种子且无向量召回 → 空结果。
        if not seeds:
            return SAGResult()

        # 每事件的「连接实体」= 命中的种子实体（用于 connected_via 与共享数排序）。
        seed_entity_set = set(seed_entity_ids)
        ev_entities = self.sag_store.entity_ids_for_events(seeds)
        connected_via: dict[str, list[str]] = {}
        for eid in seeds:
            connected_via[eid] = sorted(
                set(ev_entities.get(eid, [])) & seed_entity_set
            )

        # 4. 超边多跳扩展：从当前事件集合的实体出发拉入新事件，记 hop 距。
        hop_of: dict[str, int] = {eid: 0 for eid in seeds}
        visited: set[str] = set(seeds)
        frontier: list[str] = list(seeds)
        for hop in range(1, max_hops + 1):
            frontier_entities: set[str] = set()
            for eid in frontier:
                frontier_entities.update(ev_entities.get(eid, []))
            if not frontier_entities:
                break
            new_event_ids = self.sag_store.event_ids_for_entities(
                sorted(frontier_entities), exclude=visited
            )
            if not new_event_ids:
                break
            new_ev_entities = self.sag_store.entity_ids_for_events(new_event_ids)
            for eid in new_event_ids:
                hop_of[eid] = hop
                visited.add(eid)
                ev_entities[eid] = new_ev_entities.get(eid, [])
                connected_via[eid] = sorted(
                    set(ev_entities[eid]) & seed_entity_set
                )
            frontier = new_event_ids

        candidate_ids = sorted(visited)

        # 5. 粗排。
        event_rows = self.sag_store.events_by_ids(candidate_ids)
        if self.embedder is not None and qvec is not None:
            def _score(eid: str) -> float:
                emb = event_rows.get(eid, {}).get("embedding")
                return _cosine(qvec, emb) if emb else 0.0

            ranked = sorted(
                candidate_ids,
                key=lambda eid: (-_score(eid), hop_of.get(eid, 0), eid),
            )
            scores = {eid: _score(eid) for eid in candidate_ids}
        else:
            qtokens = set(tokens)

            def _overlap(eid: str) -> int:
                row = event_rows.get(eid, {})
                terms: set[str] = set()
                for kw in row.get("keywords", []):
                    terms.update(normalize_name(kw).split())
                terms.update(normalize_name(row.get("title", "")).split())
                return len(terms & qtokens)

            def _shared(eid: str) -> int:
                return len(connected_via.get(eid, []))

            ranked = sorted(
                candidate_ids,
                key=lambda eid: (
                    -_shared(eid),
                    -_overlap(eid),
                    hop_of.get(eid, 0),
                    eid,
                ),
            )
            scores = {
                eid: float(_shared(eid)) + float(_overlap(eid)) for eid in candidate_ids
            }

        ranked = ranked[:k]

        # 6. 装配。
        ranked_entity_ids: list[str] = []
        ranked_entity_set: set[str] = set()
        for eid in ranked:
            for ent_id in ev_entities.get(eid, []):
                if ent_id not in ranked_entity_set:
                    ranked_entity_set.add(ent_id)
                    ranked_entity_ids.append(ent_id)
        entity_rows = self.sag_store.entities_by_ids(ranked_entity_ids)

        events: list[SAGEventHit] = []
        for eid in ranked:
            row = event_rows.get(eid, {})
            ent_refs = [
                SAGEntityRef(
                    id=ent_id,
                    name=entity_rows.get(ent_id, {}).get("name", ""),
                    type=entity_rows.get(ent_id, {}).get("type", ""),
                )
                for ent_id in ev_entities.get(eid, [])
                if ent_id in entity_rows
            ]
            events.append(
                SAGEventHit(
                    event_id=eid,
                    title=row.get("title", ""),
                    summary=row.get("summary", ""),
                    content=row.get("content", ""),
                    category=row.get("category", ""),
                    keywords=row.get("keywords", []),
                    score=scores.get(eid, 0.0),
                    hop=hop_of.get(eid, 0),
                    chunk_id=row.get("chunk_id", ""),
                    entities=ent_refs,
                    connected_via=connected_via.get(eid, []),
                )
            )

        entities = [
            SAGEntityRef(
                id=ent_id,
                name=entity_rows[ent_id]["name"],
                type=entity_rows[ent_id]["type"],
            )
            for ent_id in ranked_entity_ids
            if ent_id in entity_rows
        ]

        nodes = [
            {"id": e.event_id, "type": "event", "meta": {"title": e.title}}
            for e in events
        ]
        nodes += [
            {"id": ent.id, "type": "sag_entity", "meta": {"name": ent.name, "etype": ent.type}}
            for ent in entities
        ]
        edges = []
        for e in events:
            for ent in e.entities:
                edges.append(
                    {"src": e.event_id, "dst": ent.id, "type": "has_entity"}
                )
        graph = {"nodes": nodes, "edges": edges}

        trace = SAGTrace(
            query_entities=query_entities,
            seed_event_ids=seeds,
            expanded_event_ids=[eid for eid in candidate_ids if hop_of.get(eid, 0) > 0],
            ranked_event_ids=ranked,
        )

        return SAGResult(events=events, entities=entities, graph=graph, trace=trace)
