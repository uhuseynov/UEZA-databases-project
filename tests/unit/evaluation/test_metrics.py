import math

import pytest

from src.evaluation.metrics import (
    best_threshold,
    distance_stats,
    evaluate_threshold,
    first_hit_rank,
    latency_stats,
    mean_reciprocal_rank,
    overlap_at_k,
    percentile,
    recall_at_k,
)


def test_first_hit_rank_is_one_based_and_uses_any_correct_article():
    titles = ["A", "B", "C", "B"]

    assert first_hit_rank(titles, ["B"]) == 2
    assert first_hit_rank(titles, ["Z", "C"]) == 3
    assert first_hit_rank(titles, ["Z"]) is None


def test_recall_at_k():
    ranks = [1, 3, None, 10, 2]

    assert recall_at_k(ranks, 1) == pytest.approx(1 / 5)
    assert recall_at_k(ranks, 3) == pytest.approx(3 / 5)
    assert recall_at_k(ranks, 10) == pytest.approx(4 / 5)
    assert math.isnan(recall_at_k([], 5))


def test_mean_reciprocal_rank():
    assert mean_reciprocal_rank([1, 2, None, 4]) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)


def test_overlap_at_k():
    assert overlap_at_k([1, 2, 3], [3, 2, 9], k=3) == pytest.approx(2 / 3)
    assert overlap_at_k([1, 2], [1, 2], k=10) == 1.0
    assert math.isnan(overlap_at_k([1], [], k=3))


def test_percentile_interpolates():
    samples = [1.0, 2.0, 3.0, 4.0]

    assert percentile(samples, 50) == pytest.approx(2.5)
    assert percentile(samples, 0) == 1.0
    assert percentile(samples, 100) == 4.0


def test_latency_stats():
    stats = latency_stats([10.0, 12.0, 14.0])

    assert stats.samples == 3
    assert stats.mean_ms == pytest.approx(12.0)
    assert stats.std_ms == pytest.approx(2.0)
    assert stats.p50_ms == pytest.approx(12.0)
    assert stats.max_ms == 14.0
    assert latency_stats([5.0]).std_ms == 0.0
    assert latency_stats([]).samples == 0


def test_distance_stats():
    assert distance_stats([0.2, 0.4]) == {"samples": 2, "mean": 0.3, "min": 0.2, "p50": 0.3, "max": 0.4}
    assert distance_stats([])["samples"] == 0


def test_threshold_evaluation_and_search():
    answerable = [0.20, 0.25, 0.30, 0.45]
    unanswerable = [0.40, 0.55, 0.60]

    result = evaluate_threshold(answerable, unanswerable, threshold=0.5)
    assert result.answerable_kept == 1.0
    assert result.unanswerable_rejected == pytest.approx(2 / 3)

    best = best_threshold(answerable, unanswerable)
    assert best is not None
    assert best.balanced_accuracy >= result.balanced_accuracy
    assert best_threshold(answerable, []) is None
