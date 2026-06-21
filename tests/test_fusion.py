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


def test_rrf_weights_scale_contribution():
    equal = reciprocal_rank_fusion([["a"], ["a"]])
    weighted = reciprocal_rank_fusion([["a"], ["a"]], weights=[1.0, 3.0])
    assert weighted["a"] > equal["a"]


def test_rrf_weight_can_reorder():
    # b 在高权重路第一、a 在低权重路第一 → b 反超
    r = reciprocal_rank_fusion([["a"], ["b"]], weights=[0.1, 1.0])
    assert r["b"] > r["a"]


def test_rrf_weights_none_equals_equal_weight():
    assert reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == reciprocal_rank_fusion(
        [["a", "b"], ["b", "c"]], weights=[1.0, 1.0]
    )
