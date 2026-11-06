"""Answer every ground-truth question with the language model: is "not found" right?

Each question goes through ``RAGService.answer``, the same code as ``POST /ask``, with the
question's filters. There are three outcomes:

- **rejected**: no chunk is closer than ``RAG_MAX_DISTANCE``, so the model is not asked;
- **not found**: the model replied ``NOT_FOUND``;
- **answered**: the model wrote an answer.

For an unanswerable question, rejected and not found are right and an answer is wrong. For
an answerable one, an answer is right if it cites a passage of a correct article. Replies
are kept in the report, so the wrong ones can be read.
"""

import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from src.evaluation.ground_truth import Question
from src.evaluation.metrics import latency_stats
from src.rag.models import Answer, SearchFilters
from src.rag.prompt import NOT_FOUND, cited_passages

REJECTED, NOT_FOUND_OUTCOME, ANSWERED, ERROR = "rejected", "not_found", "answered", "error"


class AnswerServiceLike(Protocol):
    async def answer(
        self, question: str, k: int | None = None, filters: SearchFilters | None = None
    ) -> Answer: ...


def classify(answer: Answer) -> str:
    if answer.found:
        return ANSWERED
    # The service does not call the model when every chunk is too far away.
    return REJECTED if not answer.timings_ms.get("llm_ms") else NOT_FOUND_OUTCOME


def cited_titles(answer: Answer) -> list[str]:
    """Titles of the passages the reply cites, in order, without duplicates."""
    titles: list[str] = []
    for number in cited_passages(answer.text, len(answer.chunks)):
        title = answer.chunks[number - 1].title
        if title not in titles:
            titles.append(title)
    return titles


async def evaluate_answers(
    questions: Sequence[Question],
    service: AnswerServiceLike,
    *,
    environment: dict[str, Any] | None = None,
    reply_chars: int = 1200,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for question in questions:
        start = time.perf_counter()
        record: dict[str, Any] = {
            "id": question.id,
            "question": question.question,
            "answerable": question.answerable,
            "filters": question.filters.as_dict(),
            "correct_articles": list(question.correct_articles),
        }
        try:
            answer = await service.answer(question.question, filters=question.filters)
        except Exception as exc:  # noqa: BLE001 - recorded, the other questions continue
            record |= {"outcome": ERROR, "error": f"{type(exc).__name__}: {exc}"[:300],
                       "seconds": round(time.perf_counter() - start, 2)}
            records.append(record)
            continue

        outcome = classify(answer)
        cited = cited_titles(answer) if outcome == ANSWERED else []
        record |= {
            "outcome": outcome,
            "reply": answer.text[:reply_chars],
            "cited": cited,
            "cites_correct": bool(set(cited) & set(question.correct_articles)),
            "no_citation": outcome == ANSWERED and not cited,
            "mentions_not_found": outcome == ANSWERED and NOT_FOUND in answer.text.upper(),
            "context_titles": list(dict.fromkeys(chunk.title for chunk in answer.chunks)),
            "top_distance": round(min((c.distance for c in answer.chunks), default=float("nan")), 6)
            if answer.chunks else None,
            "llm_ms": answer.timings_ms.get("llm_ms"),
            "seconds": round(time.perf_counter() - start, 2),
        }
        records.append(record)

    return {
        "kind": "answers",
        "label": "answers",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": environment or {},
        "summary": summarize_answers(records),
        "questions": records,
    }


def summarize_answers(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def count(subset, outcome):
        return sum(1 for r in subset if r["outcome"] == outcome)

    answerable = [r for r in records if r["answerable"]]
    unanswerable = [r for r in records if not r["answerable"]]
    answered = [r for r in answerable if r["outcome"] == ANSWERED]
    llm_ms = [r["llm_ms"] for r in records if r.get("llm_ms")]
    return {
        "answerable": {
            "questions": len(answerable),
            "answered": len(answered),
            "answered_citing_a_correct_article": sum(1 for r in answered if r["cites_correct"]),
            "answered_without_citation": sum(1 for r in answered if r["no_citation"]),
            "not_found": count(answerable, NOT_FOUND_OUTCOME),
            "rejected": count(answerable, REJECTED),
            "errors": count(answerable, ERROR),
        },
        "unanswerable": {
            "questions": len(unanswerable),
            "rejected": count(unanswerable, REJECTED),
            "not_found": count(unanswerable, NOT_FOUND_OUTCOME),
            "answered": count(unanswerable, ANSWERED),
            "errors": count(unanswerable, ERROR),
        },
        "replies_mentioning_not_found": sum(1 for r in records if r.get("mentions_not_found")),
        "llm_latency": latency_stats(llm_ms).as_dict(),
    }


def render_answers(report: dict[str, Any]) -> str:
    summary = report["summary"]
    a, u = summary["answerable"], summary["unanswerable"]
    llm = summary["llm_latency"]
    environment = report.get("environment", {})
    parts = [
        "# Answers with the language model",
        "",
        f"Created {report['created_at']}. Model `{environment.get('llm_model', '?')}`, "
        f"`RAG_MAX_DISTANCE={environment.get('rag_max_distance', '?')}`, "
        f"top {environment.get('top_k', '?')} chunks per question.",
        "",
        "| Questions | n | answered | of those citing a correct article | NOT_FOUND | rejected by distance | errors |",
        "|---|---|---|---|---|---|---|",
        f"| answerable | {a['questions']} | {a['answered']} | {a['answered_citing_a_correct_article']} "
        f"| {a['not_found']} | {a['rejected']} | {a['errors']} |",
        f"| unanswerable | {u['questions']} | {u['answered']} | – | {u['not_found']} "
        f"| {u['rejected']} | {u['errors']} |",
        "",
        f"Answers without any citation: {a['answered_without_citation']}. Replies that contain "
        f"`NOT_FOUND` next to other text (counted as answered): "
        f"{summary['replies_mentioning_not_found']}.",
        f"Model time per call: mean {llm['mean_ms'] / 1000:.1f} s, p95 {llm['p95_ms'] / 1000:.1f} s "
        f"over {llm['samples']} calls." if llm["samples"] else "The model was not called.",
    ]

    def lines(records):
        return [
            f"- **{r['id']}** {r['question']}  \n  {r['outcome']}"
            + (f", cites {', '.join(r['cited']) or 'nothing'}" if r["outcome"] == ANSWERED else "")
            + (f": {r.get('reply', r.get('error', ''))[:400]}" if r["outcome"] in (ANSWERED, ERROR) else "")
            for r in records
        ]

    unanswerable = [r for r in report["questions"] if not r["answerable"]]
    wrong = [
        r for r in report["questions"]
        if r["answerable"] and (r["outcome"] != ANSWERED or not r.get("cites_correct"))
    ]
    parts += ["", "## Unanswerable questions", "", *lines(unanswerable)]
    parts += ["", "## Answerable questions without a cited correct article", "", *lines(wrong)]
    return "\n".join(parts) + "\n"
