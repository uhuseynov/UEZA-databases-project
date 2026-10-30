import json

import pytest

from src.evaluation.ground_truth import Question
from src.evaluation.report import render_evaluation, render_m_sweep, render_sweep, write_report
from src.evaluation.runner import EvalConfig, ef_search_sweep, evaluate, m_sweep
from src.rag.models import RetrievedChunk, SearchFilters

pytestmark = pytest.mark.anyio


def chunk(chunk_id: int, title: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(chunk_id, chunk_id, title, None, 0, "text", distance)


QUESTIONS = [
    Question("1", "q1", ("Random forest",), True),
    Question("2", "q2", ("Overfitting",), True),
    Question(
        "3", "q3", ("Gradient boosting",), True, SearchFilters(root_category="Core"), "root_category = Core"
    ),
    Question("4", "football?", (), False),
]

# What the fake database returns for each question, by question text.
RESULTS = {
    "q1": [chunk(10, "Random forest", 0.20), chunk(11, "Bagging", 0.30)],
    "q2": [chunk(20, "Dropout", 0.25), chunk(21, "Overfitting", 0.35)],
    "q3": [chunk(30, "Gradient boosting", 0.22)],
    "football?": [chunk(40, "Robot soccer", 0.70)],
}


INDEX = {q.question: float(i) for i, q in enumerate(QUESTIONS)}


class FakeEmbedder:
    """Encodes each question as a one-number vector: its position in QUESTIONS."""

    def embed(self, texts, kind="passage"):
        assert kind == "query"
        return [[INDEX[t]] for t in texts]


class FakeRetriever:
    """Returns RESULTS[question]; with ``exact=False`` and a small ef it misses a chunk."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.vector_to_question = {index: text for text, index in INDEX.items()}

    async def retrieve(self, query_vector, k=5, filters=None, *, exact=False, ef_search=None,
                       shape="join", vector_format="text"):
        self.calls.append({"k": k, "filters": filters, "exact": exact, "ef_search": ef_search,
                           "shape": shape, "vector_format": vector_format})
        question = self.vector_to_question[query_vector[0]]
        chunks = RESULTS[question][:k]
        if not exact and ef_search is not None and ef_search < 20 and question == "q2":
            chunks = chunks[:1]  # a low ef misses the second neighbour
        return chunks


class FailingRetriever(FakeRetriever):
    async def retrieve(self, query_vector, k=5, filters=None, *, exact=False, ef_search=None,
                       shape="join", vector_format="text"):
        if filters is not None and filters.root_category:
            raise RuntimeError("Unknown column 'a.root_category'")
        return await super().retrieve(query_vector, k, filters, exact=exact, ef_search=ef_search,
                                      shape=shape, vector_format=vector_format)


async def test_evaluate_computes_recall_mrr_and_latency():
    retriever = FakeRetriever()
    config = EvalConfig(label="test", runs=3, warmup_runs=1, not_found_threshold=0.5)

    report = await evaluate(QUESTIONS, FakeEmbedder(), retriever, config, {"python": "3.14"})

    overall = report["metrics"]["retrieval"]["all"]
    assert overall["questions"] == 3
    assert overall["recall@1"] == pytest.approx(2 / 3, abs=1e-4)
    assert overall["recall@3"] == 1.0
    assert overall["mrr"] == pytest.approx((1 + 0.5 + 1) / 3, abs=1e-4)
    assert report["metrics"]["retrieval"]["filtered"]["questions"] == 1
    # 4 questions x (1 warm-up + 3 timed runs)
    assert len(retriever.calls) == 16
    assert all(call["k"] == 10 for call in retriever.calls)
    assert report["metrics"]["latency"]["all"]["samples"] == 12
    assert len(report["metrics"]["latency"]["per_run_mean_ms"]) == 3
    assert report["metrics"]["filtered_with_fewer_than_k_results"] == ["3"]
    assert report["metrics"]["errors"] == {}
    assert report["environment"] == {"python": "3.14"}


async def test_not_found_analysis_uses_the_top_distance():
    report = await evaluate(QUESTIONS, FakeEmbedder(), FakeRetriever(), EvalConfig(runs=1))

    not_found = report["metrics"]["not_found"]
    assert not_found["unanswerable_top_distance"]["max"] == 0.7
    assert not_found["configured_threshold"]["unanswerable_rejected"] == 1.0
    assert not_found["configured_threshold"]["answerable_kept"] == 1.0


async def test_a_failing_question_is_reported_and_left_out():
    report = await evaluate(QUESTIONS, FakeEmbedder(), FailingRetriever(), EvalConfig(runs=2))

    assert "root_category" in report["metrics"]["errors"]["3"]
    assert report["metrics"]["retrieval"]["all"]["questions"] == 2
    assert report["metrics"]["retrieval"]["filtered"]["questions"] == 0


async def test_sweep_compares_index_with_exact_search():
    report = await ef_search_sweep(
        QUESTIONS, FakeEmbedder(), FakeRetriever(), [10, 40], runs=2, k=3
    )

    rows = {row["ef_search"]: row for row in report["rows"]}
    assert set(rows) == {"exact", 10, 40}
    assert rows["exact"]["index_recall@3"] == 1.0
    assert rows[40]["index_recall@3"] == 1.0
    # ef=10 returns 1 of the 2 exact neighbours for q2: (1 + 0.5 + 1 + 1) / 4
    assert rows[10]["index_recall@3"] == pytest.approx(0.875)


async def test_reports_are_written_as_json_and_markdown(tmp_path):
    report = await evaluate(QUESTIONS, FakeEmbedder(), FakeRetriever(), EvalConfig(label="My run", runs=1))

    json_path, md_path = write_report(report, tmp_path)

    assert json_path.name.endswith("_My-run.json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metrics"]["retrieval"]["all"]["questions"] == 3
    markdown = md_path.read_text(encoding="utf-8")
    assert "Recall@10" in markdown
    assert "| all | 3 |" in markdown


async def test_sweep_renders_a_table():
    report = await ef_search_sweep(QUESTIONS, FakeEmbedder(), FakeRetriever(), [10], runs=1, k=3)

    markdown = render_sweep(report)

    assert "| exact |" in markdown
    assert "index recall@3" in markdown


EMPTY_DISTANCES = {"samples": 0, "mean": None, "min": None, "p50": None, "max": None}


def test_render_evaluation_lists_errors():
    report = {
        "label": "x",
        "created_at": "now",
        "config": {"k_values": [1], "exact": True, "ef_search": None, "runs": 1, "warmup_runs": 0},
        "metrics": {
            "retrieval": {"all": {"questions": 0, "recall@1": float("nan"), "mrr": float("nan")}},
            "latency": {"run_to_run": {"mean_ms": float("nan"), "std_ms": float("nan"), "samples": 0}},
            "not_found": {
                "answerable_top_distance": EMPTY_DISTANCES,
                "unanswerable_top_distance": EMPTY_DISTANCES,
                "configured_threshold": {
                    "threshold": 0.5,
                    "answerable_kept": None,
                    "unanswerable_rejected": None,
                },
                "best_threshold": None,
            },
            "filtered_with_fewer_than_k_results": [],
            "unstable_questions": [],
            "errors": {"3": "RuntimeError: boom"},
        },
    }

    markdown = render_evaluation(report)

    assert "exact search (no index)" in markdown
    assert "- 3: `RuntimeError: boom`" in markdown


async def test_evaluate_passes_shape_and_vector_format_to_every_search():
    retriever = FakeRetriever()
    config = EvalConfig(runs=1, shape="nearest_first", vector_format="binary")

    report = await evaluate(QUESTIONS, FakeEmbedder(), retriever, config)

    assert {(c["shape"], c["vector_format"]) for c in retriever.calls} == {("nearest_first", "binary")}
    assert report["config"]["shape"] == "nearest_first"


async def test_m_sweep_rebuilds_measures_and_restarts_for_every_m():
    retriever = FakeRetriever()
    events = []

    async def rebuild(m):
        events.append(("rebuild", m))
        return 1.5

    async def restart():
        events.append(("restart",))

    report = await m_sweep(
        QUESTIONS, FakeEmbedder(), retriever, [6, 16], [10, 40],
        rebuild=rebuild, restart=restart, shapes=["join", "nearest_first"], runs=1, k=3,
    )

    assert events == [("rebuild", 6), ("restart",), ("rebuild", 16), ("restart",)]
    assert report["builds"] == [{"m": 6, "build_seconds": 1.5}, {"m": 16, "build_seconds": 1.5}]
    assert report["config"]["questions"] == 3  # the filtered question is left out
    assert all(call["filters"].is_empty() for call in retriever.calls)
    rows = report["rows"]
    assert rows[0]["shape"] == "exact"
    # exact + 2 M x 2 states x 2 shapes x 2 ef values
    assert len(rows) == 1 + 16
    row = next(r for r in rows if (r["m"], r["state"], r["shape"], r["ef_search"])
               == (16, "restarted", "nearest_first", 10))
    # ef=10 returns 1 of the 2 exact neighbours for q2: (1 + 0.5 + 1) / 3
    assert row["index_recall@3"] == pytest.approx(0.8333, abs=1e-4)
    assert "latency_plain" in row

    markdown = render_m_sweep(report)
    assert "| 16 | restarted | nearest_first | 10 |" in markdown
    assert "## Index build" in markdown


async def test_m_sweep_without_restart_measures_only_after_the_build():
    async def rebuild(m):
        return 0.1

    report = await m_sweep(QUESTIONS, FakeEmbedder(), FakeRetriever(), [8], [20],
                           rebuild=rebuild, shapes=["join"], runs=1, k=3)

    assert [row["state"] for row in report["rows"]] == [None, "built"]
    assert report["config"]["restarted"] is False


def test_config_validation():
    with pytest.raises(ValueError):
        EvalConfig(runs=0)
    with pytest.raises(ValueError):
        EvalConfig(k_values=())
