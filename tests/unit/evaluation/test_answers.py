import pytest

from src.evaluation.answers import evaluate_answers
from src.evaluation.ground_truth import Question
from src.evaluation.report import render_answers
from src.rag.models import Answer, RetrievedChunk, SearchFilters
from src.rag.service import NOT_FOUND_MESSAGE

pytestmark = pytest.mark.anyio


def chunk(title: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(1, 1, title, None, 0, "text", distance)


QUESTIONS = [
    Question("1", "q-cites-right", ("Random forest",), True),
    Question("2", "q-cites-wrong", ("Overfitting",), True),
    Question("3", "q-refused", ("Bagging",), True, SearchFilters(root_category="Core"), "root_category = Core"),
    Question("4", "football?", (), False),
    Question("5", "near-topic?", (), False),
    Question("6", "hallucinated?", (), False),
    Question("7", "broken", ("X",), True),
]

CONTEXT = (chunk("Random forest", 0.2), chunk("Bagging", 0.3))
LLM = {"embed_ms": 1.0, "retrieve_ms": 2.0, "llm_ms": 1500.0, "total_ms": 1510.0}
NO_LLM = {"embed_ms": 1.0, "retrieve_ms": 2.0, "llm_ms": 0.0, "total_ms": 3.0}

ANSWERS = {
    "q-cites-right": Answer("q", "Random forests average many trees [1].", True, chunks=CONTEXT, timings_ms=LLM),
    "q-cites-wrong": Answer("q", "It is bagging [2]. NOT_FOUND otherwise.", True, chunks=CONTEXT, timings_ms=LLM),
    "q-refused": Answer("q", NOT_FOUND_MESSAGE, False, chunks=CONTEXT, timings_ms=LLM),
    "football?": Answer("q", NOT_FOUND_MESSAGE, False, chunks=(chunk("Robot soccer", 0.6),), timings_ms=NO_LLM),
    "near-topic?": Answer("q", NOT_FOUND_MESSAGE, False, chunks=CONTEXT, timings_ms=LLM),
    "hallucinated?": Answer("q", "It was made in 1999.", True, chunks=CONTEXT, timings_ms=LLM),
}


class FakeService:
    def __init__(self) -> None:
        self.filters = []

    async def answer(self, question, k=None, filters=None):
        self.filters.append(filters)
        if question == "broken":
            raise TimeoutError("model did not answer")
        return ANSWERS[question]


async def test_outcomes_are_counted_for_answerable_and_unanswerable_questions():
    service = FakeService()

    report = await evaluate_answers(QUESTIONS, service, environment={"llm_model": "qwen2.5:3b"})

    summary = report["summary"]
    assert summary["answerable"] == {
        "questions": 4, "answered": 2, "answered_citing_a_correct_article": 1,
        "answered_without_citation": 0, "not_found": 1, "rejected": 0, "errors": 1,
    }
    assert summary["unanswerable"] == {
        "questions": 3, "rejected": 1, "not_found": 1, "answered": 1, "errors": 0,
    }
    assert summary["replies_mentioning_not_found"] == 1
    assert summary["llm_latency"]["samples"] == 5
    assert service.filters[2] == SearchFilters(root_category="Core")
    by_id = {r["id"]: r for r in report["questions"]}
    assert by_id["1"]["cited"] == ["Random forest"]
    assert by_id["1"]["cites_correct"]
    assert by_id["6"]["outcome"] == "answered"
    assert by_id["6"]["no_citation"]
    assert by_id["7"]["error"] == "TimeoutError: model did not answer"


async def test_report_lists_the_unanswerable_replies():
    report = await evaluate_answers(QUESTIONS, FakeService(), environment={"llm_model": "m"})

    markdown = render_answers(report)

    assert "Model `m`" in markdown
    assert "| unanswerable | 3 | 1 | – | 1 | 1 | 0 |" in markdown
    assert "It was made in 1999." in markdown
    assert "**2** q-cites-wrong" in markdown
