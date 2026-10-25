"""MariaDB integration tests for article ingestion persistence."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.database import Database
from src.database.repositories.articles import ArticleRepository
from src.logger import AppLogger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
]

TEST_PAGE_ID = 3_900_000_001
TEST_TITLE = "UEZA Ingestion Integration Test"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_vector(index: int = 0) -> list[float]:
    if not 0 <= index < 768:
        raise ValueError("Vector index out of bounds")

    vector = [0.0] * 768
    vector[index] = 1.0

    return vector


def make_article(
    revision_id: int = 100,
    categories: tuple[str, ...] = ("Test category",),
    links: tuple[str, ...] = ("Machine learning",),
) -> SimpleNamespace:
    return SimpleNamespace(
        page_id=TEST_PAGE_ID,
        title=TEST_TITLE,
        length=5000,
        revision_id=revision_id,
        last_modified=datetime(2026, 9, 1, tzinfo=UTC),
        categories=categories,
        links=links,
    )


def csv_row() -> dict[str, str]:
    return {
        "title": TEST_TITLE,
        "pageid": str(TEST_PAGE_ID),
        "root_category": "Machine learning",
    }


async def cleanup(database: Database) -> None:
    """Remove only the dedicated integration-test article."""

    async with database.get_session() as session:
        result = await session.execute(
            text("""
                SELECT id
                FROM articles
                WHERE page_id = :page_id
            """),
            {"page_id": TEST_PAGE_ID},
        )

        article_id = result.scalar_one_or_none()

        if article_id is None:
            return

        for table in (
            "article_chunks",
            "article_categories",
            "article_links",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE article_id = :article_id"),
                {"article_id": article_id},
            )

        await session.execute(
            text("""
                DELETE FROM articles
                WHERE id = :article_id
            """),
            {"article_id": article_id},
        )


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    db = Database(
        settings,
        AppLogger(settings),
    )

    await db.connect()

    try:
        async with db.get_session() as session:
            result = await session.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                """)
            )

            existing_tables = {str(row[0]) for row in result.all()}

            result = await session.execute(
                text("""
                    SELECT title
                    FROM articles
                    WHERE page_id = :page_id
                """),
                {"page_id": TEST_PAGE_ID},
            )

            existing_title = result.scalar_one_or_none()

        required_tables = {
            "articles",
            "article_chunks",
            "article_categories",
            "article_links",
        }

        missing = required_tables - existing_tables

        if missing:
            pytest.fail(f"Missing database tables: {sorted(missing)}")

        if existing_title not in (None, TEST_TITLE):
            pytest.fail("Integration test page ID conflicts with existing article")

        await cleanup(db)

        try:
            yield db
        finally:
            await cleanup(db)

    finally:
        await db.disconnect()


async def read_state(
    database: Database,
) -> dict[str, Any] | None:
    """Read an article and its child record counts."""

    async with database.get_session() as session:
        result = await session.execute(
            text("""
                SELECT
                    a.id,
                    a.revision_id,
                    a.title,
                    a.root_category,

                    (
                        SELECT COUNT(*)
                        FROM article_chunks c
                        WHERE c.article_id = a.id
                    ) AS chunks,

                    (
                        SELECT COUNT(*)
                        FROM article_categories ac
                        WHERE ac.article_id = a.id
                    ) AS categories,

                    (
                        SELECT COUNT(*)
                        FROM article_links al
                        WHERE al.article_id = a.id
                    ) AS links

                FROM articles a
                WHERE a.page_id = :page_id
            """),
            {"page_id": TEST_PAGE_ID},
        )

        row = result.mappings().one_or_none()

        if row is None:
            return None

        return dict(row)


async def test_first_ingest(database: Database) -> None:
    repository = ArticleRepository(database)

    await repository.replace_article(
        wiki=make_article(),
        csv_row=csv_row(),
        chunks=[
            "Title: Test\n\nFirst chunk.",
            "Title: Test\n\nSecond chunk.",
        ],
        vectors=[
            make_vector(0),
            make_vector(1),
        ],
    )

    state = await read_state(database)

    assert state is not None
    assert state["title"] == TEST_TITLE
    assert state["revision_id"] == 100
    assert state["root_category"] == "Machine learning"
    assert state["chunks"] == 2
    assert state["categories"] == 1
    assert state["links"] == 1


async def test_repeat_ingest_is_idempotent(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    chunks = [
        "Title: Test\n\nFirst chunk.",
        "Title: Test\n\nSecond chunk.",
    ]

    vectors = [
        make_vector(0),
        make_vector(1),
    ]

    for _ in range(2):
        await repository.replace_article(
            wiki=make_article(),
            csv_row=csv_row(),
            chunks=chunks,
            vectors=vectors,
        )

    state = await read_state(database)

    assert state is not None
    assert state["chunks"] == 2
    assert state["categories"] == 1
    assert state["links"] == 1


async def test_revision_replaces_old_chunks(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    await repository.replace_article(
        wiki=make_article(revision_id=100),
        csv_row=csv_row(),
        chunks=["Title: Test\n\nOld content."],
        vectors=[make_vector(0)],
    )

    await repository.replace_article(
        wiki=make_article(revision_id=200),
        csv_row=csv_row(),
        chunks=[
            "Title: Test\n\nNew content A.",
            "Title: Test\n\nNew content B.",
            "Title: Test\n\nNew content C.",
        ],
        vectors=[
            make_vector(0),
            make_vector(1),
            make_vector(2),
        ],
    )

    state = await read_state(database)

    assert state is not None
    assert state["revision_id"] == 200
    assert state["chunks"] == 3

    async with database.get_session() as session:
        result = await session.execute(
            text("""
                SELECT c.chunk_text
                FROM article_chunks c
                JOIN articles a ON a.id = c.article_id
                WHERE a.page_id = :page_id
                ORDER BY c.chunk_index
            """),
            {"page_id": TEST_PAGE_ID},
        )

        chunks = list(result.scalars().all())

    assert len(chunks) == 3
    assert all("New content" in chunk for chunk in chunks)
    assert all("Old content" not in chunk for chunk in chunks)


async def test_invalid_vector_rejected(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    with pytest.raises(ValueError):
        await repository.replace_article(
            wiki=make_article(),
            csv_row=csv_row(),
            chunks=["Chunk"],
            vectors=[[1.0, 2.0]],
        )

    state = await read_state(database)

    assert state is None


async def test_mismatched_counts_rejected(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    with pytest.raises(ValueError):
        await repository.replace_article(
            wiki=make_article(),
            csv_row=csv_row(),
            chunks=["First", "Second"],
            vectors=[make_vector()],
        )

    state = await read_state(database)

    assert state is None


async def test_page_id_mismatch_rejected(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    invalid_row = csv_row()
    invalid_row["pageid"] = "123"

    with pytest.raises(ValueError):
        await repository.replace_article(
            wiki=make_article(),
            csv_row=invalid_row,
            chunks=["Chunk"],
            vectors=[make_vector()],
        )

    state = await read_state(database)

    assert state is None


async def test_transaction_rolls_back_on_db_error(
    database: Database,
) -> None:
    """Failed replacement must preserve the original article."""

    repository = ArticleRepository(database)

    await repository.replace_article(
        wiki=make_article(revision_id=100),
        csv_row=csv_row(),
        chunks=[
            "Title: Test\n\nOriginal content.",
        ],
        vectors=[make_vector(0)],
    )

    original = await read_state(database)

    assert original is not None

    # Deliberately violate article_categories.category NOT NULL.
    # This happens after the replacement transaction starts.
    broken_article = make_article(
        revision_id=200,
        categories=(None,),  # type: ignore[arg-type]
    )

    with pytest.raises(IntegrityError):
        await repository.replace_article(
            wiki=broken_article,
            csv_row=csv_row(),
            chunks=[
                "Title: Test\n\nReplacement content.",
            ],
            vectors=[make_vector(1)],
        )

    restored = await read_state(database)

    assert restored is not None
    assert restored["id"] == original["id"]
    assert restored["revision_id"] == 100
    assert restored["chunks"] == 1
    assert restored["categories"] == 1


async def test_chunk_positions_are_sequential(
    database: Database,
) -> None:
    repository = ArticleRepository(database)

    chunks = [f"Title: Test\n\nChunk {index}" for index in range(5)]

    vectors = [make_vector(index) for index in range(5)]

    await repository.replace_article(
        wiki=make_article(),
        csv_row=csv_row(),
        chunks=chunks,
        vectors=vectors,
    )

    async with database.get_session() as session:
        result = await session.execute(
            text("""
                SELECT c.chunk_index
                FROM article_chunks c
                JOIN articles a ON a.id = c.article_id
                WHERE a.page_id = :page_id
                ORDER BY c.chunk_index
            """),
            {"page_id": TEST_PAGE_ID},
        )

        indexes = list(result.scalars().all())

    assert indexes == [0, 1, 2, 3, 4]
