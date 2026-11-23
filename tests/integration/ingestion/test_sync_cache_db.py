"""Live sync and snapshot ingest against a real MariaDB, a mocked MediaWiki and a real cache.

Only the dedicated test article is touched. Chunking and embedding are replaced by small fakes:
they are not what is under test here.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from src.config import settings
from src.database import Database
from src.database.repositories.articles import ArticleRepository
from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki import MediaWikiClient, WikiArticle
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.sync import sync_articles
from src.logger import AppLogger

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PAGE_ID = 3_900_000_002
TITLE = "UEZA Sync Cache Integration Test"
SNAPSHOT_TIME = "2026-09-01T10:00:00Z"


def vector(index: int = 0) -> list[float]:
    values = [0.0] * settings.embedding_dimension
    values[index] = 1.0
    return values


class FakeEmbedder:
    model = SimpleNamespace(tokenizer=None)

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]]:
        return [vector(i % 10) for i, _ in enumerate(texts)]


@pytest.fixture(autouse=True)
def simple_chunks(monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.pipeline.chunk_article",
        lambda title, text, tokenizer, config="A": [f"Title: {title}\n\n{text.strip()}"],
    )


async def remove_test_article(database: Database) -> None:
    async with database.get_session() as session:
        article_id = (
            await session.execute(
                text("SELECT id FROM articles WHERE page_id = :page_id"), {"page_id": PAGE_ID}
            )
        ).scalar_one_or_none()
        if article_id is None:
            return
        for table in ("article_chunks", "article_categories", "article_links"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE article_id = :id"), {"id": article_id}
            )
        await session.execute(text("DELETE FROM articles WHERE id = :id"), {"id": article_id})


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    db = Database(settings, AppLogger(settings))
    await db.connect()
    try:
        async with db.get_session() as session:
            tables = {
                str(row[0])
                for row in (
                    await session.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = DATABASE()"
                        )
                    )
                ).all()
            }
        if not {"articles", "article_chunks"} <= tables:
            pytest.skip("schema not loaded")
    except Exception as exc:  # noqa: BLE001 - any connection problem means "skip"
        await db.disconnect()
        pytest.skip(f"MariaDB not reachable: {exc}")

    await remove_test_article(db)
    try:
        yield db
    finally:
        await remove_test_article(db)
        await db.disconnect()


class Upstream:
    """MediaWiki serving revision ``latest`` (or ``historical`` for a snapshot request)."""

    def __init__(self, article_response, *, latest: int, historical: int = 150) -> None:
        self.article_response = article_response
        self.latest = latest
        self.historical = historical
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        revision = self.historical if "rvstart" in request.url.params else self.latest
        return httpx.Response(
            200,
            json=self.article_response(
                title=TITLE,
                page_id=PAGE_ID,
                revision_id=revision,
                timestamp="2026-11-05T03:24:26Z",
                content=f"Text of revision {revision}.",
                categories=["Test category"],
                links=["Machine learning"],
            ),
        )


def stale_article() -> WikiArticle:
    return WikiArticle(
        page_id=PAGE_ID,
        title=TITLE,
        text="Text of revision 100.",
        length=21,
        revision_id=100,
        last_modified=datetime(2026, 9, 1, tzinfo=UTC),
        categories=("Test category",),
        links=("Machine learning",),
    )


def csv_row() -> dict[str, str]:
    return {
        "title": TITLE,
        "pageid": str(PAGE_ID),
        "last_edit": SNAPSHOT_TIME,
        "root_category": "Machine learning",
    }


async def store_revision_100(repository: ArticleRepository) -> None:
    await repository.replace_article(
        wiki=stale_article(),
        csv_row=csv_row(),
        chunks=["Title: T\n\nText of revision 100."],
        vectors=[vector(0)],
    )


async def stored(database: Database) -> tuple[int, str]:
    async with database.get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.revision_id, c.chunk_text FROM articles a "
                    "JOIN article_chunks c ON c.article_id = a.id WHERE a.page_id = :page_id"
                ),
                {"page_id": PAGE_ID},
            )
        ).one()
    return int(row[0]), str(row[1])


def setup(tmp_path, database, article_response, *, latest: int, cached: WikiArticle | None):
    cache = ArticleCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    if cached is not None:
        cache.set(cached)
    upstream = Upstream(article_response, latest=latest)
    client = MediaWikiClient(
        user_agent="UEZA-test",
        requests_per_second=100_000,
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
        cache=cache,
    )
    repository = ArticleRepository(database, settings.embedding_dimension)
    pipeline = IngestionPipeline(client, FakeEmbedder(), repository)
    csv_file = tmp_path / "articles.csv"
    csv_file.write_text(
        "title,pageid,length,last_edit,root_category,category\n"
        f"{TITLE},{PAGE_ID},1000,{SNAPSHOT_TIME},Machine learning,Test\n",
        encoding="utf-8",
    )
    return cache, upstream, client, repository, pipeline, str(csv_file)


async def test_sync_does_not_store_a_stale_cached_revision_again(
    database, tmp_path, article_response
):
    cache, upstream, client, repository, pipeline, csv_file = setup(
        tmp_path, database, article_response, latest=200, cached=stale_article()
    )
    await store_revision_100(repository)

    result = await sync_articles(
        client=client,
        repository=repository,
        pipeline_factory=lambda: pipeline,
        csv_path=csv_file,
        rebuild_share=1.0,
    )

    assert [c.latest_revision for c in result.changed] == [200]
    assert result.replaced_articles == 1
    assert result.failures == []
    revision, chunk = await stored(database)
    assert revision == 200  # the cached revision 100 was not stored again
    assert "revision 200" in chunk
    assert upstream.calls >= 3  # the revision check, then the article and its metadata
    assert cache.get(TITLE).revision_id == 200

    again = await sync_articles(
        client=client,
        repository=repository,
        pipeline_factory=lambda: pipeline,
        csv_path=csv_file,
    )
    assert again.changed == []  # and the next sync finds nothing left to do


async def test_a_plain_latest_ingest_still_uses_the_cache_within_its_lifetime(
    database, tmp_path, article_response
):
    """Pins the documented difference: only the sync demands a revision."""
    _, upstream, _, repository, pipeline, _ = setup(
        tmp_path, database, article_response, latest=200, cached=stale_article()
    )

    await pipeline.ingest_one(csv_row(), snapshot=False)

    assert (await stored(database))[0] == 100
    assert upstream.calls == 0


async def test_a_snapshot_ingest_ignores_and_leaves_the_cache_alone(
    database, tmp_path, article_response
):
    cache, upstream, _, repository, pipeline, _ = setup(
        tmp_path, database, article_response, latest=200, cached=stale_article()
    )
    cached_before = {p.name: p.read_bytes() for p in cache.cache_path.iterdir()}

    await pipeline.ingest_one(csv_row(), snapshot=True)

    revision, chunk = await stored(database)
    assert revision == 150  # the revision at the snapshot date, not the cached 100
    assert "revision 150" in chunk
    assert upstream.calls >= 1
    assert {p.name: p.read_bytes() for p in cache.cache_path.iterdir()} == cached_before
