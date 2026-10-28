"""Unit tests for the ingestion loop: failures and the statistics refresh."""

import pytest

from src.ingestion.pipeline import IngestionPipeline

pytestmark = pytest.mark.anyio

CSV = """title,pageid,length,last_edit,root_category,category
Good article,1,1000,2026-09-01T10:00:00Z,Core,Core
Broken article,2,1000,2026-09-01T10:00:00Z,Core,Core
"""


class FakeRepository:
    def __init__(self) -> None:
        self.analyzed = 0

    async def analyze(self) -> None:
        self.analyzed += 1


def make_pipeline(repository: FakeRepository, failing: set[str]) -> IngestionPipeline:
    # Skip __init__, which loads the tokenizer of the embedding model.
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.repository = repository

    async def ingest_one(row, config="A", snapshot=True):
        if row["title"] in failing:
            raise ValueError("Unclosed MediaWiki table")
        return 3

    pipeline.ingest_one = ingest_one
    return pipeline


async def test_statistics_are_refreshed_even_when_an_article_fails(tmp_path) -> None:
    csv_path = tmp_path / "articles.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    repository = FakeRepository()
    pipeline = make_pipeline(repository, failing={"Broken article"})

    with pytest.raises(RuntimeError, match="1 failures") as error:
        await pipeline.ingest_all(csv_path=str(csv_path))

    assert "Broken article" in str(error.value)
    assert repository.analyzed == 1


async def test_successful_run_reports_counts(tmp_path) -> None:
    csv_path = tmp_path / "articles.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    repository = FakeRepository()
    pipeline = make_pipeline(repository, failing=set())

    articles, chunks = await pipeline.ingest_all(csv_path=str(csv_path))

    assert (articles, chunks) == (2, 6)
    assert repository.analyzed == 1


async def test_nothing_to_analyze_when_every_article_fails(tmp_path) -> None:
    csv_path = tmp_path / "articles.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    repository = FakeRepository()
    pipeline = make_pipeline(repository, failing={"Good article", "Broken article"})

    with pytest.raises(RuntimeError, match="2 failures"):
        await pipeline.ingest_all(csv_path=str(csv_path))

    assert repository.analyzed == 0
