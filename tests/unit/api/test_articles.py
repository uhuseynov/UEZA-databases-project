"""``GET /articles/{title}``: responses, errors, caching, cleanup and concurrency."""

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki import (
    MediaWikiClient,
    MediaWikiPageNotFoundError,
    MediaWikiRequestError,
    WikiArticle,
)
from src.main import create_app

ARTICLE = WikiArticle(
    page_id=233488,
    title="Machine learning",
    text="Machine learning is a field of study.",
    length=1000,
    revision_id=12345,
    last_modified=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    categories=("Machine learning",),
    links=("Artificial intelligence", "Statistics"),
)


class FakeClient:
    """Stands in for MediaWikiClient: records calls and the closing, optionally blocks."""

    def __init__(self, *, error: Exception | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay
        self.titles: list[str] = []
        self.closed = 0

    def get_article(self, title: str) -> WikiArticle:
        self.titles.append(title)
        if self.delay:
            time.sleep(self.delay)  # blocking, like the real client's HTTP calls
        if self.error:
            raise self.error
        return ARTICLE

    def close(self) -> None:
        self.closed += 1


def make_app(factory):
    app = create_app()
    app.state.container.mediawiki_client.override(providers.Factory(factory))
    return app


@pytest.fixture
def clients():
    return []


@pytest.fixture
def make_client(clients):
    def make(**options) -> FakeClient:
        client = FakeClient(**options)
        clients.append(client)
        return client

    return make


def test_returns_the_article_as_json(make_client, clients):
    app = make_app(lambda: make_client())

    response = TestClient(app).get("/articles/Machine learning")

    assert response.status_code == 200
    assert response.json() == {
        "page_id": 233488,
        "title": "Machine learning",
        "text": "Machine learning is a field of study.",
        "length": 1000,
        "revision_id": 12345,
        "last_modified": "2026-10-01T12:00:00Z",
        "categories": ["Machine learning"],
        "links": ["Artificial intelligence", "Statistics"],
    }
    assert clients[0].titles == ["Machine learning"]


@pytest.mark.parametrize(
    "error",
    [MediaWikiRequestError("network down"), MediaWikiPageNotFoundError("no such page")],
)
def test_mediawiki_errors_are_a_400_with_the_message(make_client, error):
    app = make_app(lambda: make_client(error=error))

    response = TestClient(app).get("/articles/Anything")

    assert response.status_code == 400
    assert response.json() == {"detail": str(error)}


def test_a_blank_title_is_a_422(make_client):
    app = make_app(lambda: make_client(error=ValueError("title cannot be empty")))

    response = TestClient(app).get("/articles/%20")

    assert response.status_code == 422
    assert response.json() == {"detail": "title cannot be empty"}


def test_unexpected_errors_are_not_reported_as_mediawiki_errors(make_client):
    app = make_app(lambda: make_client(error=RuntimeError("bug")))

    response = TestClient(app, raise_server_exceptions=False).get("/articles/X")

    assert response.status_code == 500


def test_the_client_is_closed_after_a_success(make_client, clients):
    app = make_app(lambda: make_client())
    http = TestClient(app)

    http.get("/articles/A")
    http.get("/articles/B")

    assert [client.closed for client in clients] == [1, 1]


@pytest.mark.parametrize("error", [MediaWikiRequestError("x"), ValueError("x"), RuntimeError("x")])
def test_the_client_is_closed_after_an_error(make_client, clients, error):
    app = make_app(lambda: make_client(error=error))

    TestClient(app, raise_server_exceptions=False).get("/articles/A")

    assert [client.closed for client in clients] == [1]


def test_the_real_client_releases_its_http_connections(tmp_path, article_response):
    """The provider's client owns an httpx.Client; the request must close it."""
    created: list[MediaWikiClient] = []

    def factory() -> MediaWikiClient:
        client = MediaWikiClient(
            user_agent="UEZA-test", requests_per_second=100_000, max_retries=0
        )
        client._client.close()  # replace the real pool by a mock transport
        client._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=article_response(title="Python"))
            )
        )
        created.append(client)
        return client

    response = TestClient(make_app(factory)).get("/articles/Python")

    assert response.status_code == 200
    assert created[0]._client.is_closed


def test_a_second_request_is_served_from_the_article_cache(tmp_path, article_response):
    """Real MediaWikiClient and ArticleCache over a mocked HTTP transport."""
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=3600)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["prop"])
        return httpx.Response(
            200,
            json=article_response(title="Python", categories=["Languages"], links=["Computing"]),
        )

    def factory() -> MediaWikiClient:
        return MediaWikiClient(
            user_agent="UEZA-test",
            requests_per_second=100_000,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            cache=cache,
        )

    http = TestClient(make_app(factory))

    first = http.get("/articles/Python")
    second = http.get("/articles/Python")

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["categories"] == ["Languages"]
    assert calls == ["info|revisions", "categories|links"]  # nothing for the second request


async def longest_loop_stall(duration: float) -> float:
    """Run a 10 ms heartbeat for ``duration`` s and return the longest gap between ticks.

    Blocking code on the event loop shows up here as a gap as long as the block.
    """
    longest = 0.0
    last = time.perf_counter()
    end = last + duration
    while last < end:
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        longest = max(longest, now - last)
        last = now
    return longest


@pytest.mark.anyio
async def test_blocking_fetches_do_not_block_the_event_loop(make_client):
    app = make_app(lambda: make_client(delay=0.5))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        fetch = asyncio.create_task(http.get("/articles/Slow"))
        stall = await longest_loop_stall(0.6)  # the 0.5 s fetch runs during this time
        health = await http.get("/health")

        assert (await fetch).status_code == 200

    assert health.status_code == 200
    assert stall < 0.2  # a fetch that blocked the loop would leave a ~0.5 s gap


@pytest.mark.anyio
async def test_concurrent_requests_run_in_parallel_and_each_closes_its_client(
    make_client, clients
):
    app = make_app(lambda: make_client(delay=0.4))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        start = time.perf_counter()
        responses = await asyncio.gather(*(http.get(f"/articles/Page {i}") for i in range(6)))
        elapsed = time.perf_counter() - start

    assert [response.status_code for response in responses] == [200] * 6
    assert sorted(title for client in clients for title in client.titles) == [
        f"Page {i}" for i in range(6)
    ]
    assert [client.closed for client in clients] == [1] * 6
    assert elapsed < 6 * 0.4 * 0.6  # serial would take 2.4 s
