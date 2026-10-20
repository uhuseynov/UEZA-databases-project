"""Load the ground-truth questions from ``data/ground_truth.csv``.

The CSV has the columns ``id, question, correct_article, needs_filter,
filter_description, answerable``. Filters are written as clauses joined by AND,
for example ``root_category = Machine learning AND length > 100000``. They are
turned into the same ``SearchFilters`` the API uses, so the evaluation runs the
exact SQL a reader would run.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from src.rag.models import SearchFilters

_CLAUSE = re.compile(r"^\s*(?P<field>[a-z_]+)\s*(?P<op>>=|<=|=|>|<)\s*(?P<value>.+?)\s*$")
_NOTE = re.compile(r"\s*\([^)]*\)\s*$")  # e.g. "(verify with links table)"
_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class Question:
    id: str
    question: str
    correct_articles: tuple[str, ...]
    answerable: bool
    filters: SearchFilters = field(default_factory=SearchFilters)
    filter_description: str = ""

    @property
    def filtered(self) -> bool:
        return not self.filters.is_empty()


def parse_filter_description(description: str) -> SearchFilters:
    """Turn ``"length > 250000 AND category = Deepfakes"`` into ``SearchFilters``."""
    values: dict[str, object] = {}
    if not description.strip():
        return SearchFilters()

    for clause in _AND.split(description.strip()):
        match = _CLAUSE.match(clause)
        if not match:
            raise ValueError(f"cannot parse filter clause {clause!r}")
        name, op = match["field"], match["op"]
        value = _NOTE.sub("", match["value"]).strip()

        if name in ("category", "root_category", "linked_from"):
            if op != "=":
                raise ValueError(f"{name} only supports '=', got {op!r}")
            values[name] = value
        elif name == "length":
            values.update(_length_bounds(op, int(value)))
        elif name == "last_edit":
            values.update(_date_bounds(op, date.fromisoformat(value)))
        else:
            raise ValueError(f"unknown filter field {name!r}")

    return SearchFilters(**values)


def _length_bounds(op: str, number: int) -> dict[str, int]:
    # SearchFilters length bounds are inclusive; lengths are whole numbers.
    return {
        ">": {"min_length": number + 1},
        ">=": {"min_length": number},
        "<": {"max_length": number - 1},
        "<=": {"max_length": number},
        "=": {"min_length": number, "max_length": number},
    }[op]


def _date_bounds(op: str, day: date) -> dict[str, datetime]:
    # edited_since is inclusive, edited_before exclusive; "<= day" includes the whole day.
    start = datetime.combine(day, time.min)
    next_day = start + timedelta(days=1)
    return {
        ">": {"edited_since": next_day},
        ">=": {"edited_since": start},
        "<": {"edited_before": start},
        "<=": {"edited_before": next_day},
        "=": {"edited_since": start, "edited_before": next_day},
    }[op]


def _yes(value: str) -> bool:
    return value.strip().upper() in ("Y", "YES", "TRUE", "1")


def load_ground_truth(path: str | Path) -> list[Question]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ground-truth file not found: {path}")

    questions: list[Question] = []
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            question_id = row["id"].strip()
            answerable = _yes(row["answerable"])
            articles = tuple(
                title.strip()
                for title in re.split(r"[|;]", row.get("correct_article") or "")
                if title.strip()
            )
            if answerable and not articles:
                raise ValueError(f"question {question_id} is answerable but has no correct article")

            description = (row.get("filter_description") or "").strip()
            if _yes(row.get("needs_filter") or "N") and not description:
                raise ValueError(f"question {question_id} needs a filter but has no description")
            try:
                filters = parse_filter_description(description)
            except ValueError as exc:
                raise ValueError(f"question {question_id}: {exc}") from exc

            questions.append(
                Question(
                    id=question_id,
                    question=row["question"].strip(),
                    correct_articles=articles,
                    answerable=answerable,
                    filters=filters,
                    filter_description=description,
                )
            )
    return questions
