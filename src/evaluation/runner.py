"""Run the ground-truth questions against the retriever: recall, latency, not-found.

Method:

- Every question is embedded once (query prefix), outside the timed part, so the
  latency numbers are the MariaDB search only.
- One warm-up pass is run and discarded (cold caches, first connection).
- Then every question is searched ``runs`` times. Recall comes from the first
  timed run; later runs only add latency samples and are checked to return the
  same chunks.
- A question counts as a hit at k when a chunk of its correct article is among
  the top k chunks.
- Errors are recorded per question and the question is left out of the metrics,
  so one unsupported filter does not hide the rest of the results.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from src.evaluation.ground_truth import Question
from src.evaluation.metrics import (
    best_threshold,
    distance_stats,
    evaluate_threshold,
    first_hit_rank,
    latency_stats,
    mean_reciprocal_rank,
    overlap_at_k,
    recall_at_k,
)
from src.rag.models import RetrievedChunk, SearchFilters
from src.rag.retriever import (
    DEFAULT_SHAPE,
    DEFAULT_VECTOR_FORMAT,
    SHAPES,
    SearchShape,
    VectorFormat,
)

K_VALUES = (1, 3, 5, 10)


class EmbedderLike(Protocol):
    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]]: ...


class RetrieverLike(Protocol):
    async def retrieve(
        self,
        query_vector: Sequence[float],
        k: int = 5,
        filters: SearchFilters | None = None,
        *,
        exact: bool = False,
        ef_search: int | None = None,
        shape: SearchShape = DEFAULT_SHAPE,
        vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
    ) -> list[RetrievedChunk]: ...


@dataclass(slots=True, frozen=True)
class EvalConfig:
    label: str = "default"
    k_values: tuple[int, ...] = K_VALUES
    runs: int = 5
    warmup_runs: int = 1
    ef_search: int | None = None
    exact: bool = False
    not_found_threshold: float = 0.5
    shape: SearchShape = DEFAULT_SHAPE
    vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT

    def __post_init__(self) -> None:
        if self.runs < 1:
            raise ValueError("runs must be at least 1")
        if self.warmup_runs < 0:
            raise ValueError("warmup_runs must not be negative")
        if not self.k_values or min(self.k_values) < 1:
            raise ValueError("k_values must be positive")

    @property
    def max_k(self) -> int:
        return max(self.k_values)


@dataclass(slots=True)
class QuestionResult:
    id: str
    question: str
    answerable: bool
    filtered: bool
    filters: dict[str, str | int]
    correct_articles: list[str]
    rank: int | None = None
    returned: int = 0
    top_titles: list[str] = field(default_factory=list)
    top_distance: float | None = None
    chunk_ids: list[int] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    stable: bool = True
    error: str | None = None


async def embed_questions(
    embedder: EmbedderLike, questions: Sequence[Question]
) -> tuple[list[list[float]], float]:
    start = time.perf_counter()
    vectors = await asyncio.to_thread(embedder.embed, [q.question for q in questions], "query")
    return vectors, (time.perf_counter() - start) * 1000


async def run_questions(
    questions: Sequence[Question],
    vectors: Sequence[Sequence[float]],
    retriever: RetrieverLike,
    config: EvalConfig,
) -> list[QuestionResult]:
    results = [
        QuestionResult(
            id=q.id,
            question=q.question,
            answerable=q.answerable,
            filtered=q.filtered,
            filters=q.filters.as_dict(),
            correct_articles=list(q.correct_articles),
        )
        for q in questions
    ]

    async def search(question: Question, vector: Sequence[float]) -> list[RetrievedChunk]:
        return await retriever.retrieve(
            vector,
            config.max_k,
            question.filters,
            exact=config.exact,
            ef_search=config.ef_search,
            shape=config.shape,
            vector_format=config.vector_format,
        )

    for _ in range(config.warmup_runs):
        for question, vector, result in zip(questions, vectors, results, strict=True):
            try:
                await search(question, vector)
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                result.error = _describe(exc)

    for run in range(config.runs):
        for question, vector, result in zip(questions, vectors, results, strict=True):
            if result.error:
                continue
            start = time.perf_counter()
            try:
                chunks = await search(question, vector)
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                result.error = _describe(exc)
                continue
            result.latencies_ms.append(round((time.perf_counter() - start) * 1000, 3))

            ids = [chunk.chunk_id for chunk in chunks]
            if run == 0:
                titles = [chunk.title for chunk in chunks]
                result.chunk_ids = ids
                result.returned = len(chunks)
                result.top_titles = titles[:5]
                result.top_distance = round(chunks[0].distance, 6) if chunks else None
                result.rank = first_hit_rank(titles, question.correct_articles)
            elif ids != result.chunk_ids:
                result.stable = False

    return results


def summarize(results: Sequence[QuestionResult], config: EvalConfig) -> dict[str, Any]:
    ok = [r for r in results if r.error is None]
    answerable = [r for r in ok if r.answerable]
    subsets = {
        "all": answerable,
        "plain": [r for r in answerable if not r.filtered],
        "filtered": [r for r in answerable if r.filtered],
    }

    retrieval = {}
    for name, subset in subsets.items():
        ranks = [r.rank for r in subset]
        retrieval[name] = {
            "questions": len(subset),
            **{f"recall@{k}": _round(recall_at_k(ranks, k)) for k in config.k_values},
            "mrr": _round(mean_reciprocal_rank(ranks)),
        }

    latency = {
        name: latency_stats([ms for r in subset for ms in r.latencies_ms]).as_dict()
        for name, subset in {
            "all": ok,
            "plain": [r for r in ok if not r.filtered],
            "filtered": [r for r in ok if r.filtered],
        }.items()
    }
    run_means = [
        sum(r.latencies_ms[run] for r in ok) / len(ok)
        for run in range(config.runs)
        if ok and all(len(r.latencies_ms) > run for r in ok)
    ]
    latency["per_run_mean_ms"] = [round(m, 3) for m in run_means]
    latency["run_to_run"] = latency_stats(run_means).as_dict()

    answerable_distances = [
        r.top_distance for r in answerable if r.top_distance is not None
    ]
    unanswerable_distances = [
        r.top_distance for r in ok if not r.answerable and r.top_distance is not None
    ]
    configured = evaluate_threshold(
        answerable_distances, unanswerable_distances, config.not_found_threshold
    )
    best = best_threshold(answerable_distances, unanswerable_distances)

    starved = [r.id for r in ok if r.filtered and r.returned < config.max_k]

    return {
        "retrieval": retrieval,
        "latency": latency,
        "not_found": {
            "answerable_top_distance": distance_stats(answerable_distances),
            "unanswerable_top_distance": distance_stats(unanswerable_distances),
            "configured_threshold": _rounded_dict(asdict(configured)),
            "best_threshold": _rounded_dict(asdict(best)) if best else None,
        },
        "filtered_with_fewer_than_k_results": starved,
        "unstable_questions": [r.id for r in ok if not r.stable],
        "errors": {r.id: r.error for r in results if r.error},
    }


async def evaluate(
    questions: Sequence[Question],
    embedder: EmbedderLike,
    retriever: RetrieverLike,
    config: EvalConfig,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vectors, embed_ms = await embed_questions(embedder, questions)
    results = await run_questions(questions, vectors, retriever, config)
    return {
        "kind": "evaluation",
        "label": config.label,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {**asdict(config), "k_values": list(config.k_values)},
        "environment": environment or {},
        "embedding": {
            "questions": len(questions),
            "total_ms": round(embed_ms, 1),
            "per_question_ms": round(embed_ms / len(questions), 2) if questions else None,
        },
        "metrics": summarize(results, config),
        "questions": [asdict(r) for r in results],
    }


async def _exact_baseline(
    questions: Sequence[Question],
    vectors: Sequence[Sequence[float]],
    retriever: RetrieverLike,
    *,
    runs: int,
    warmup_runs: int,
    k: int,
    vector_format: VectorFormat,
) -> tuple[dict[str, Any], dict[str, list[int]], tuple[int, ...]]:
    """The exact search (full scan, no index): the true nearest neighbours."""
    k_values = tuple(sorted({kv for kv in K_VALUES if kv <= k} | {k}))
    config = EvalConfig(label="exact", k_values=k_values, runs=runs, warmup_runs=warmup_runs,
                        exact=True, vector_format=vector_format)
    exact = await run_questions(questions, vectors, retriever, config)
    exact_ids = {r.id: r.chunk_ids for r in exact if r.error is None}
    return _sweep_row("exact", exact, config, exact_ids, k), exact_ids, k_values


async def ef_search_sweep(
    questions: Sequence[Question],
    embedder: EmbedderLike,
    retriever: RetrieverLike,
    ef_values: Sequence[int],
    *,
    runs: int = 3,
    warmup_runs: int = 1,
    k: int = 10,
    environment: dict[str, Any] | None = None,
    shape: SearchShape = DEFAULT_SHAPE,
    vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
) -> dict[str, Any]:
    """Recall and latency for several mhnsw_ef_search values, next to exact search.

    The exact search (full scan, no index) gives the true nearest neighbours, so
    "index recall" is the share of those the HNSW index also returned.
    """
    vectors, _ = await embed_questions(embedder, questions)
    exact_row, exact_ids, k_values = await _exact_baseline(
        questions, vectors, retriever, runs=runs, warmup_runs=warmup_runs, k=k,
        vector_format=vector_format,
    )

    rows = [exact_row]
    for ef in ef_values:
        config = EvalConfig(label=f"ef={ef}", k_values=k_values, runs=runs,
                            warmup_runs=warmup_runs, ef_search=ef, shape=shape,
                            vector_format=vector_format)
        results = await run_questions(questions, vectors, retriever, config)
        rows.append(_sweep_row(ef, results, config, exact_ids, k))

    return {
        "kind": "ef_search_sweep",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {"ef_values": list(ef_values), "runs": runs, "warmup_runs": warmup_runs, "k": k,
                   "shape": shape, "vector_format": vector_format},
        "environment": environment or {},
        "rows": rows,
    }


async def m_sweep(
    questions: Sequence[Question],
    embedder: EmbedderLike,
    retriever: RetrieverLike,
    m_values: Sequence[int],
    ef_values: Sequence[int],
    *,
    rebuild: Callable[[int], Awaitable[float]],
    restart: Callable[[], Awaitable[None]] | None = None,
    shapes: Sequence[SearchShape] = SHAPES,
    runs: int = 3,
    warmup_runs: int = 1,
    k: int = 10,
    vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Index recall and latency for several M values of the vector index.

    For every M the index is rebuilt (``rebuild(m)`` returns the seconds it took) and
    measured right after the build ("built") and, if ``restart`` is given, again after a
    server restart ("restarted"). Only the questions without a filter are used: a
    filtered search does not use the vector index, so M cannot change it. The exact
    answers are computed once, since they do not depend on the index.
    """
    plain = [q for q in questions if not q.filtered]
    vectors, _ = await embed_questions(embedder, plain)
    exact_row, exact_ids, k_values = await _exact_baseline(
        plain, vectors, retriever, runs=runs, warmup_runs=warmup_runs, k=k,
        vector_format=vector_format,
    )

    rows: list[dict[str, Any]] = [{"m": None, "state": None, "shape": "exact", **exact_row}]
    builds: list[dict[str, Any]] = []
    for m in m_values:
        seconds = await rebuild(m)
        builds.append({"m": m, "build_seconds": round(seconds, 2)})
        states: list[tuple[str, Callable[[], Awaitable[None]] | None]] = [("built", None)]
        if restart is not None:
            states.append(("restarted", restart))
        for state, before in states:
            if before is not None:
                await before()
            for shape in shapes:
                for ef in ef_values:
                    config = EvalConfig(label=f"M={m} {state} {shape} ef={ef}", k_values=k_values,
                                        runs=runs, warmup_runs=warmup_runs, ef_search=ef,
                                        shape=shape, vector_format=vector_format)
                    results = await run_questions(plain, vectors, retriever, config)
                    rows.append({"m": m, "state": state, "shape": shape,
                                 **_sweep_row(ef, results, config, exact_ids, k)})

    return {
        "kind": "m_sweep",
        "label": "m-sweep",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {"m_values": list(m_values), "ef_values": list(ef_values),
                   "shapes": list(shapes), "runs": runs, "warmup_runs": warmup_runs, "k": k,
                   "vector_format": vector_format, "questions": len(plain),
                   "restarted": restart is not None},
        "environment": environment or {},
        "builds": builds,
        "rows": rows,
    }


def _sweep_row(
    ef: int | str,
    results: Sequence[QuestionResult],
    config: EvalConfig,
    exact_ids: dict[str, list[int]],
    k: int,
) -> dict[str, Any]:
    summary = summarize(results, config)
    ok = [r for r in results if r.error is None and r.id in exact_ids]

    def index_recall(subset: Sequence[QuestionResult]) -> float:
        values = [overlap_at_k(r.chunk_ids, exact_ids[r.id], k) for r in subset]
        values = [v for v in values if v == v]  # drop NaN (no exact results)
        return _round(sum(values) / len(values)) if values else float("nan")

    return {
        "ef_search": ef,
        f"index_recall@{k}": index_recall(ok),
        f"index_recall@{k}_plain": index_recall([r for r in ok if not r.filtered]),
        f"index_recall@{k}_filtered": index_recall([r for r in ok if r.filtered]),
        "retrieval": summary["retrieval"]["all"],
        "latency": summary["latency"]["all"],
        "latency_plain": summary["latency"]["plain"],
        "latency_filtered": summary["latency"]["filtered"],
        "filtered_with_fewer_than_k_results": summary["filtered_with_fewer_than_k_results"],
        "errors": summary["errors"],
    }


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits) if value == value else value  # keep NaN as is


def _rounded_dict(values: dict[str, float]) -> dict[str, float]:
    return {key: _round(value) for key, value in values.items()}
