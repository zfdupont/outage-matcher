import pytest

from outage_matcher.evals import metrics


def test_first_relevant_rank_is_one_based_and_none_when_absent():
    assert metrics.first_relevant_rank([7, 3, 9], {3}) == 2
    assert metrics.first_relevant_rank([7, 3, 9], {9, 3}) == 2
    assert metrics.first_relevant_rank([7, 3, 9], {4}) is None
    assert metrics.first_relevant_rank([], {4}) is None


def test_recall_at_k_on_a_hand_checked_set():
    ranks = [1, 2, 4, 11, None]
    assert metrics.recall_at_k(ranks, 1) == pytest.approx(1 / 5)
    assert metrics.recall_at_k(ranks, 3) == pytest.approx(2 / 5)
    assert metrics.recall_at_k(ranks, 5) == pytest.approx(3 / 5)
    assert metrics.recall_at_k(ranks, 10) == pytest.approx(3 / 5)
    assert metrics.recall_at_k(ranks, 11) == pytest.approx(4 / 5)


def test_mrr_on_a_hand_checked_set():
    # (1 + 1/2 + 1/4 + 1/10 + 0) / 5
    assert metrics.mean_reciprocal_rank([1, 2, 4, 10, None]) == pytest.approx(1.85 / 5)


def test_perfect_and_empty_cases():
    assert metrics.mean_reciprocal_rank([1, 1]) == 1.0
    assert metrics.recall_at_k([1, 1], 1) == 1.0
    assert metrics.mean_reciprocal_rank([None, None]) == 0.0
    assert metrics.recall_at_k([None], 10) == 0.0


def test_compute_metrics_has_every_k_and_mrr():
    result = metrics.compute_metrics([1, 3, None, 6])
    assert result == {
        "recall@1": 0.25,
        "recall@3": 0.5,
        "recall@5": 0.5,
        "recall@10": 0.75,
        "mrr": pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4),
    }


def test_invalid_inputs_raise():
    with pytest.raises(ValueError, match="no queries"):
        metrics.mean_reciprocal_rank([])
    with pytest.raises(ValueError, match="1-based"):
        metrics.recall_at_k([0], 1)
    with pytest.raises(ValueError, match="at least 1"):
        metrics.recall_at_k([1], 0)
