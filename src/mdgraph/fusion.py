"""倒数排名融合（Reciprocal Rank Fusion）。"""

from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """对多个排名列表做 RRF：score(item) = Σ 1/(k + rank)，rank 从 1 开始。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores
