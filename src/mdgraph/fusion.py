"""倒数排名融合（Reciprocal Rank Fusion）。"""

from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60, weights: list[float] | None = None
) -> dict[str, float]:
    """对多个排名列表做（可加权）RRF：score(item) = Σ w_i × 1/(k + rank)，rank 从 1 开始。

    weights 为每路 ranking 的权重；None → 全 1.0（等权，向后兼容）。
    """
    scores: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else weights[i]
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + w * (1.0 / (k + rank))
    return scores
