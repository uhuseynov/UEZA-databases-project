"""The article cache against revisions: a sync cannot reuse stale content, a snapshot ignores it."""

from datetime import UTC, datetime

import httpx
import pytest

from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki import MediaWikiClient, WikiArticle
from src.ingestion.pipeline import IngestionPipeline

TITLE = "Machine learning"


def cached(revision_id: int, text: str) -> WikiArticle:
    return WikiArticle(
        page_id=233488,
        title=TITLE,
        text=text,
        length=len(text),
        revision_id=revision_id,
        last_modified=datetime(2026, 9, 1, tzinfo=UTC),
        categories=("Old category",),
        links=("Old link",),
    )


@pytest.fixture
def cache(tmp_path) -> ArticleCache:
    return ArticleCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)


class Upstream:
    """A MediaWiki that serves ``revision_id`` for the latest revision and records requests."""

    def __init__(self, article_response, *, latest: int = 200, historical: int = 50) -> None:
        self.article_response = article_response
        self.latest = latest
        self.historical = historical
        self.requests: list[httpx.QueryParams] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.params)
        revision = self.historical if "rvstart" in request.url.params else self.latest
        return httpx.Response(
            200,
            json=self.article_response(
                title=TITLE,
                page_id=233488,
                revision_id=revision,
                content=f"text of revision {revision}",
                categories=["New category"],
                links=["New link"],
            ),
        )


def make_client(cache: ArticleCache, upstream: Upstream) -> MediaWikiClient:
    return MediaWikiClient(
        user_agent="UEZA-test",
        requests_per_second=100_000,
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
        cache=cache,
    )


def test_a_cached_older_revision_is_not_used_when_a_newer_one_is_required(cache, article_response):
    cache.set(cached(100, "stale text"))
    upstream = Upstream(article_response, latest=200)

    article = make_client(cache, upstream).get_article(TITLE, min_revision=200)

    assert article.revision_id == 200
    assert article.text == "text of revision 200"
    assert len(upstream.requests) == 2  # it went to MediaWiki
    assert cache.get(TITLE).revision_id == 200  # and the cache now holds the fresh copy


def test_a_cached_copy_that_is_new_enough_is_used(cache, article_response):
    cache.set(cached(200, "current text"))
    upstream = Upstream(article_response)
    client = make_client(cache, upstream)

    assert client.get_article(TITLE, min_revision=200).text == "current text"
    assert client.get_article(TITLE, min_revision=150).text == "current text"
    assert upstream.requests == []


def test_without_a_required_revision_the_cache_is_used_until_it_expires(cache, article_response):
    """The documented behaviour of the latest-revision mode (make ingest-latest, the API)."""
    cache.set(cached(100, "stale text"))
    upstream = Upstream(article_response, latest=200)

    article = make_client(cache, upstream).get_article(TITLE)

    assert article.revision_id == 100
    assert upstream.requests == []


def test_the_required_revision_also_applies_to_a_cached_alias(cache, article_response):
    cache.set(cached(100, "stale text"), requested_title="ML")
    upstream = Upstream(article_response, latest=200)

    article = make_client(cache, upstream).get_article("ML", min_revision=200)

    assert article.revision_id == 200
    assert upstream.requests


def test_a_snapshot_request_neither_reads_nor_writes_the_cache(cache, article_response):
    cache.set(cached(100, "cached text"))
    files = {path.name: path.read_bytes() for path in cache.cache_path.iterdir()}
    upstream = Upstream(article_response, historical=50)

    snapshot = make_client(cache, upstream).get_article(
        TITLE, as_of=datetime(2026, 8, 1, tzinfo=UTC), min_revision=999
    )

    assert snapshot.revision_id == 50  # the historical revision, not the cached 100
    assert all("rvstart" in params for params in upstream.requests[:1])
    assert {path.name: path.read_bytes() for path in cache.cache_path.iterdir()} == files


@pytest.mark.anyio
async def test_the_pipeline_passes_the_required_revision_to_the_client():
    seen: dict = {}

    class Stop(Exception):
        pass

    class Client:
        def get_article(self, title, **options):
            seen.update(options)
            raise Stop

    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.client = Client()
    row = {"title": TITLE, "pageid": "1", "last_edit": "2026-09-01T10:00:00Z"}

    with pytest.raises(Stop):
        await pipeline.ingest_one(row, snapshot=False, min_revision=201)
    assert seen == {"as_of": None, "min_revision": 201}

    seen.clear()
    with pytest.raises(Stop):
        await pipeline.ingest_one(row, snapshot=False)
    assert seen == {"as_of": None}  # a plain ingest sends nothing new
