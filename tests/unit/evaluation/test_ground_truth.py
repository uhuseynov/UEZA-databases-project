from datetime import datetime

import pytest

from src.evaluation.ground_truth import load_ground_truth, parse_filter_description
from src.rag.models import SearchFilters


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("", SearchFilters()),
        ("root_category = Reinforcement learning", SearchFilters(root_category="Reinforcement learning")),
        ("length > 250000", SearchFilters(min_length=250001)),
        ("length < 10000", SearchFilters(max_length=9999)),
        ("length >= 5", SearchFilters(min_length=5)),
        ("length <= 5", SearchFilters(max_length=5)),
        ("last_edit < 2026-01-01", SearchFilters(edited_before=datetime(2026, 1, 1))),
        ("last_edit >= 2026-10-04", SearchFilters(edited_since=datetime(2026, 10, 4))),
        ("last_edit > 2026-10-04", SearchFilters(edited_since=datetime(2026, 10, 5))),
        ("last_edit <= 2026-10-04", SearchFilters(edited_before=datetime(2026, 10, 5))),
        ("category = Text-to-video generation", SearchFilters(category="Text-to-video generation")),
        (
            "linked_from = Large language model (verify with links table)",
            SearchFilters(linked_from="Large language model"),
        ),
        (
            "root_category = Natural language processing AND length < 30000",
            SearchFilters(root_category="Natural language processing", max_length=29999),
        ),
        (
            "root_category = Machine learning and length > 100000",
            SearchFilters(root_category="Machine learning", min_length=100001),
        ),
    ],
)
def test_parse_filter_description(description, expected):
    assert parse_filter_description(description) == expected


@pytest.mark.parametrize(
    "description",
    ["popularity > 3", "category > Deepfakes", "length is long", "last_edit < yesterday"],
)
def test_parse_rejects_unknown_or_malformed_clauses(description):
    with pytest.raises(ValueError):
        parse_filter_description(description)


CSV = """id,question,correct_article,needs_filter,filter_description,answerable
1,"Which method averages many decision trees?",Random forest,N,,Y
37,"Which long article gives an overview?",Artificial intelligence,Y,length > 250000,Y
54,"How does the offside rule work in football?",,N,,N
"""


def test_load_ground_truth(tmp_path):
    path = tmp_path / "ground_truth.csv"
    path.write_text(CSV, encoding="utf-8")

    questions = load_ground_truth(path)

    assert [q.id for q in questions] == ["1", "37", "54"]
    assert questions[0].correct_articles == ("Random forest",)
    assert not questions[0].filtered
    assert questions[1].filters == SearchFilters(min_length=250001)
    assert questions[1].filtered
    assert not questions[2].answerable
    assert questions[2].correct_articles == ()


def test_load_rejects_answerable_question_without_article(tmp_path):
    path = tmp_path / "ground_truth.csv"
    path.write_text(
        "id,question,correct_article,needs_filter,filter_description,answerable\n"
        '1,"Q?",,N,,Y\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="question 1"):
        load_ground_truth(path)


def test_load_reports_which_question_has_a_bad_filter(tmp_path):
    path = tmp_path / "ground_truth.csv"
    path.write_text(
        "id,question,correct_article,needs_filter,filter_description,answerable\n"
        '9,"Q?",A,Y,stars > 3,Y\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="question 9"):
        load_ground_truth(path)


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="ground-truth"):
        load_ground_truth(tmp_path / "nope.csv")
