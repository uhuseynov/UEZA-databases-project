"""Hybrid search against a real MariaDB.

Needs the database from docker-compose.yml with the four-table schema (articles,
article_categories, article_links, article_chunks). The test is skipped when the
database is unreachable or the schema is not there yet. It inserts a few articles
whose titles start with a test prefix and removes them again afterwards.

The filter tests use exact search, so they check the SQL predicates themselves and do
not depend on how many candidates the HNSW index visits when a filter is very selective.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from src.config import settings
from src.database import Database
from src.logger import AppLogger
from src.rag.models import SearchFilters
from src.rag.retriever import VectorRetriever

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# No "_" or "%" in the prefix: both are wildcards in LIKE.
PREFIX = "UEZA integration test: "
TEST_CATEGORY = f"{PREFIX}category"
REQUIRED_TABLES = {"articles", "article_categories", "article_links", "article_chunks"}

# (title, article_length, last_edit_date, categories, links, basis index of its vector)
ARTICLES = [
    (f"{PREFIX}Alpha", 1_000, datetime(2025, 6, 1), [TEST_CATEGORY], [f"{PREFIX}Gamma"], 0),
    (f"{PREFIX}Beta", 5_000, datetime(2026, 2, 1), [TEST_CATEGORY], [], 1),
    (f"{PREFIX}Gamma", 20_000, datetime(2026, 9, 1), [], [], 2),
]


def basis_vector(index: int, *, noise: float = 0.0) -> list[float]:
    vector = [noise] * settings.embedding_dimension
    vector[index] = 1.0
    return vector


CLEANUP_STATEMENTS = (
    "DELETE FROM article_chunks WHERE article_id IN "
    "(SELECT id FROM articles WHERE title LIKE :prefix)",
    "DELETE FROM article_categories WHERE article_id IN "
    "(SELECT id FROM articles WHERE title LIKE :prefix)",
    "DELETE FROM article_links WHERE article_id IN "
    "(SELECT id FROM articles WHERE title LIKE :prefix)",
    "DELETE FROM articles WHERE title LIKE :prefix",
)


async def _cleanup(session) -> None:
    for statement in CLEANUP_STATEMENTS:
        await session.execute(text(statement), {"prefix": f"{PREFIX}%"})


@pytest.fixture
async def database():
    db = Database(settings, AppLogger(settings))
    await db.connect()
    try:
        async with db.get_session() as session:
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
            tables = {row[0] for row in result.all()}
    except Exception as exc:  # noqa: BLE001 - any connection problem means "skip"
        await db.disconnect()
        pytest.skip(f"MariaDB not reachable: {exc}")

    missing = REQUIRED_TABLES - tables
    if missing:
        await db.disconnect()
        pytest.skip(f"schema not loaded yet, missing tables: {sorted(missing)}")

    async with db.get_session() as session:
        await _cleanup(session)
        for offset, (title, length, edited, categories, links, basis) in enumerate(ARTICLES):
            result = await session.execute(
                text(
                    "INSERT INTO articles (page_id, title, url, article_length, revision_id, last_edit_date) "
                    "VALUES (:page_id, :title, :url, :length, 1, :edited)"
                ),
                {
                    "page_id": 4_000_000_000 + offset,
                    "title": title,
                    "url": "https://example.org",
                    "length": length,
                    "edited": edited,
                },
            )
            article_id = result.lastrowid
            for category in categories:
                await session.execute(
                    text("INSERT INTO article_categories (article_id, category) VALUES (:a, :c)"),
                    {"a": article_id, "c": category},
                )
            for linked_title in links:
                await session.execute(
                    text("INSERT INTO article_links (article_id, linked_title) VALUES (:a, :t)"),
                    {"a": article_id, "t": linked_title},
                )
            await session.execute(
                text(
                    "INSERT INTO article_chunks (article_id, chunk_index, chunk_text, embedding) "
                    "VALUES (:a, 0, :t, VEC_FromText(:v))"
                ),
                {"a": article_id, "t": f"chunk of {title}", "v": json.dumps(basis_vector(basis))},
            )

    yield db

    async with db.get_session() as session:
        await _cleanup(session)
    await db.disconnect()


async def test_nearest_chunk_comes_first(database):
    retriever = VectorRetriever(database)

    chunks = await retriever.retrieve(basis_vector(1, noise=0.001), k=3)

    assert chunks[0].title == f"{PREFIX}Beta"
    assert chunks[0].distance < 0.01
    assert [c.distance for c in chunks] == sorted(c.distance for c in chunks)


async def test_exact_search_agrees_with_the_index_on_the_top_hit(database):
    retriever = VectorRetriever(database)
    query = basis_vector(2, noise=0.001)

    indexed = await retriever.retrieve(query, k=1)
    exact = await retriever.retrieve(query, k=1, exact=True)

    assert indexed[0].chunk_id == exact[0].chunk_id


async def test_category_filter(database):
    retriever = VectorRetriever(database)

    chunks = await retriever.retrieve(
        basis_vector(2), k=5, filters=SearchFilters(category=TEST_CATEGORY), exact=True
    )

    assert {c.title for c in chunks} == {f"{PREFIX}Alpha", f"{PREFIX}Beta"}


async def test_linked_from_filter(database):
    retriever = VectorRetriever(database)

    chunks = await retriever.retrieve(
        basis_vector(0), k=5, filters=SearchFilters(linked_from=f"{PREFIX}Alpha"), exact=True
    )

    assert [c.title for c in chunks] == [f"{PREFIX}Gamma"]


async def test_length_and_date_filters_combine(database):
    retriever = VectorRetriever(database)

    chunks = await retriever.retrieve(
        basis_vector(0, noise=0.001),
        k=5,
        filters=SearchFilters(
            category=TEST_CATEGORY,
            min_length=2_000,
            edited_since=datetime(2026, 1, 1),
            edited_before=datetime(2026, 3, 1),
        ),
        exact=True,
    )

    assert [c.title for c in chunks] == [f"{PREFIX}Beta"]
