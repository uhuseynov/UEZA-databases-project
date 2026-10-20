"""Retrieval metrics. Pure functions, no database."""

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass


def first_hit_rank(retrieved_titles: Sequence[str], correct_titles: Iterable[str]) -> int | None:
    """1-based position of the first retrieved chunk from a correct article, or None."""
    correct = set(correct_titles)
    for position, title in enumerate(retrieved_titles, start=1):
        if title in correct:
            return position
    return None


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Share of questions whose correct article appears in the top k chunks."""
    if not ranks:
        return math.nan
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    if not ranks:
        return math.nan
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)


def overlap_at_k(found_ids: Sequence[int], exact_ids: Sequence[int], k: int) -> float:
    """Index recall: share of the exact top-k neighbours that the index also returned."""
    exact = list(exact_ids)[:k]
    if not exact:
        return math.nan
    return len(set(found_ids[:k]) & set(exact)) / len(exact)


def percentile(samples: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, ``q`` in [0, 100]."""
    if not samples:
        return math.nan
    ordered = sorted(samples)
    position = (len(ordered) - 1) * q / 100
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@dataclass(slots=True, frozen=True)
class LatencyStats:
    samples: int
    mean_ms: float
    std_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float

    def as_dict(self) -> dict[str, float]:
        return {key: round(value, 3) for key, value in asdict(self).items()}


def latency_stats(samples: Sequence[float]) -> LatencyStats:
    if not samples:
        nan = math.nan
        return LatencyStats(0, nan, nan, nan, nan, nan, nan)
    return LatencyStats(
        samples=len(samples),
        mean_ms=statistics.fmean(samples),
        std_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
        p50_ms=percentile(samples, 50),
        p95_ms=percentile(samples, 95),
        min_ms=min(samples),
        max_ms=max(samples),
    )


def distance_stats(samples: Sequence[float]) -> dict[str, float]:
    """Summary of cosine distances (no unit, 0 = identical)."""
    if not samples:
        return {"samples": 0, "mean": math.nan, "min": math.nan, "p50": math.nan, "max": math.nan}
    return {
        "samples": len(samples),
        "mean": round(statistics.fmean(samples), 4),
        "min": round(min(samples), 4),
        "p50": round(percentile(samples, 50), 4),
        "max": round(max(samples), 4),
    }


@dataclass(slots=True, frozen=True)
class ThresholdResult:
    threshold: float
    answerable_kept: float
    unanswerable_rejected: float
    balanced_accuracy: float


def evaluate_threshold(
    answerable_distances: Sequence[float],
    unanswerable_distances: Sequence[float],
    threshold: float,
) -> ThresholdResult:
    """How well "closest chunk further than threshold → not found" separates the two groups."""
    kept = (
        sum(d <= threshold for d in answerable_distances) / len(answerable_distances)
        if answerable_distances
        else math.nan
    )
    rejected = (
        sum(d > threshold for d in unanswerable_distances) / len(unanswerable_distances)
        if unanswerable_distances
        else math.nan
    )
    return ThresholdResult(threshold, kept, rejected, (kept + rejected) / 2)


def best_threshold(
    answerable_distances: Sequence[float],
    unanswerable_distances: Sequence[float],
) -> ThresholdResult | None:
    """The cut-off between two observed distances with the highest balanced accuracy."""
    if not answerable_distances or not unanswerable_distances:
        return None
    observed = sorted(set(answerable_distances) | set(unanswerable_distances))
    candidates = [(a + b) / 2 for a, b in zip(observed, observed[1:])] or observed
    results = [
        evaluate_threshold(answerable_distances, unanswerable_distances, t) for t in candidates
    ]
    return max(results, key=lambda r: (r.balanced_accuracy, r.answerable_kept))
