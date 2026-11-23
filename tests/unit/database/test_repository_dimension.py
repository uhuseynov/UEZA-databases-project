"""The repository checks vectors and the table against the configured dimension."""

import pytest

from src.database.repositories.articles import ArticleRepository, vector_column_dimension

pytestmark = pytest.mark.anyio


class FakeWiki:
    page_id = 1
    categories: list[str] = []
    links: list[str] = []


CSV_ROW = {"pageid": "1", "title": "A"}


class _Result:
    def __init__(self, create: str) -> None:
        self.create = create

    def one(self):
        return ("article_chunks", self.create)


class _Session:
    def __init__(self, create: str) -> None:
        self.create = create

    async def execute(self, statement):
        return _Result(self.create)


class FakeDatabase:
    def __init__(self, create: str = "") -> None:
        self.create = create

    def get_session(self):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def session():
            yield _Session(self.create)

        return session()


def test_reads_the_column_dimension():
    assert vector_column_dimension("  `embedding` vector(768) NOT NULL,") == 768
    assert vector_column_dimension("`embedding` VECTOR(384) NOT NULL") == 384


def test_missing_column_is_an_error():
    with pytest.raises(ValueError, match="no VECTOR"):
        vector_column_dimension("CREATE TABLE t (`id` int)")


async def test_wrong_vector_length_names_the_configured_dimension():
    repository = ArticleRepository(FakeDatabase(), dimension=4)

    with pytest.raises(ValueError, match="3 dimensions, but EMBEDDING_DIMENSION is 4"):
        await repository.replace_article(
            wiki=FakeWiki(), csv_row=CSV_ROW, chunks=["x"], vectors=[[0.1, 0.2, 0.3]]
        )


async def test_check_dimension_passes_when_the_table_matches():
    database = FakeDatabase("`embedding` vector(4) NOT NULL")

    await ArticleRepository(database, dimension=4).check_dimension()


async def test_check_dimension_reports_a_mismatch_without_changing_anything():
    database = FakeDatabase("`embedding` vector(768) NOT NULL")

    with pytest.raises(ValueError, match=r"EMBEDDING_DIMENSION is 384.*VECTOR\(768\)"):
        await ArticleRepository(database, dimension=384).check_dimension()
