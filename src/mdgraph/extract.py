"""LLM 语义抽取与聚合：chunk → 实体/关系（按规范化名合并）。纯函数，可单测。"""

from __future__ import annotations

from dataclasses import dataclass, field

from mdgraph.ids import entity_id
from mdgraph.providers.base import LLMProvider


@dataclass
class EntityRecord:
    id: str
    name: str
    type: str
    description: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractionBundle:
    entities: list[EntityRecord] = field(default_factory=list)
    mentions: list[tuple[str, str]] = field(default_factory=list)
    relations: list[tuple[str, str, str]] = field(default_factory=list)
    failed_chunks: list[str] = field(default_factory=list)


def extract_graph(chunks: list[tuple[str, str]], llm: LLMProvider) -> ExtractionBundle:
    """逐 chunk 调 llm.extract，按 entity_id 聚合实体，收集去重的 mentions/relations。

    chunks: (chunk_id, text) 列表。抽取抛异常的 chunk 记入 failed_chunks 并跳过。
    relations 仅当两端实体都在同一次抽取中出现时保留（避免幽灵实体）。
    """
    agg: dict[str, dict] = {}
    order: list[str] = []
    mentions: list[tuple[str, str]] = []
    seen_mentions: set[tuple[str, str]] = set()
    relations: list[tuple[str, str, str]] = []
    seen_relations: set[tuple[str, str, str]] = set()
    failed: list[str] = []

    for chunk_id, text in chunks:
        try:
            result = llm.extract(text)
        except Exception:  # noqa: BLE001
            failed.append(chunk_id)
            continue
        local_ids: set[str] = set()
        for ent in result.entities:
            eid = entity_id(ent.name)
            local_ids.add(eid)
            if eid not in agg:
                agg[eid] = {
                    "name": ent.name,
                    "type": ent.type,
                    "description": ent.description,
                    "aliases": set(),
                }
                order.append(eid)
            else:
                cur = agg[eid]
                if ent.name != cur["name"]:
                    cur["aliases"].add(ent.name)
                if cur["type"] in ("", "concept") and ent.type:
                    cur["type"] = ent.type
                if not cur["description"] and ent.description:
                    cur["description"] = ent.description
            m = (chunk_id, eid)
            if m not in seen_mentions:
                seen_mentions.add(m)
                mentions.append(m)
        for rel in result.relations:
            sid = entity_id(rel.source)
            tid = entity_id(rel.target)
            if sid in local_ids and tid in local_ids:
                key = (sid, tid, rel.type)
                if key not in seen_relations:
                    seen_relations.add(key)
                    relations.append(key)

    entities = [
        EntityRecord(
            id=eid,
            name=agg[eid]["name"],
            type=agg[eid]["type"],
            description=agg[eid]["description"],
            aliases=sorted(agg[eid]["aliases"]),
        )
        for eid in order
    ]
    return ExtractionBundle(
        entities=entities, mentions=mentions, relations=relations, failed_chunks=failed
    )
