from mdgraph.fusion import reciprocal_rank_fusion


def test_rrf_both_rankings_beats_single():
    r = reciprocal_rank_fusion([["a", "b"], ["a", "c"]])
    assert r["a"] > r["b"]
    assert r["a"] > r["c"]


def test_rrf_preserves_rank_order_single():
    r = reciprocal_rank_fusion([["a", "b", "c"]])
    assert r["a"] > r["b"] > r["c"]


def test_rrf_empty():
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[]]) == {}


def test_rrf_k_affects_score():
    assert reciprocal_rank_fusion([["a"]], k=1)["a"] > reciprocal_rank_fusion([["a"]], k=100)["a"]
