"""``GET /articles/{title}`` under load: the concurrency cap, the shared rate limit, the cache keys.

Everything runs against mocked HTTP; the clients are created by the same provider the app uses.
"""

import asyncio
import threading
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest
from dependency_injector import providers

from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki import MediaWikiClient, MediaWikiRequestError, WikiArticle
from src.ingestion.mediawiki.rate_limiter import RateLimiter
from src.main import create_app

pytestmark = pytest.mark.anyio

ARTICLE = WikiArticle(
    page_id=1,
    title="Machine learning",
    text="text",
    length=4,
    revision_id=1,
    last_modified=datetime(2026, 10, 1, tzinfo=UTC),
    categories=(),
    links=(),
)


class FakeClient:
    def __init__(self, tracker: Tracker, *, delay: float, error: Exception | None) -> None:
        self.tracker = tracker
        self.delay = delay
        self.error = error
        self.closed = False

    def get_article(self, title: str) -> WikiArticle:
        self.tracker.enter()
        try:
            time.sleep(self.delay)
            if self.error:
                raise self.error
            return ARTICLE
        finally:
            self.tracker.leave()

    def close(self) -> None:
        self.closed = True


class Tracker:
    """How many fetches ran at once, and how many clients were ever created."""

    def __init__(self, *, delay: float = 0.0, error: Exception | None = None) -> None:
        self.delay = delay
        self.error = error
        self.running = 0
        self.peak = 0
        self.clients: list[FakeClient] = []
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)

    def leave(self) -> None:
        with self._lock:
            self.running -= 1

    def make(self) -> FakeClient:
        client = FakeClient(self, delay=self.delay, error=self.error)
        self.clients.append(client)
        return client


def make_app(factory, *, slots: int = 4):
    app = create_app()
    app.state.container.mediawiki_client.override(providers.Factory(factory))
    app.state.article_fetch_slots = asyncio.Semaphore(slots)
    return app


def http_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def longest_loop_stall(duration: float) -> float:
    longest, last = 0.0, time.perf_counter()
    end = last + duration
    while last < end:
        await asyncio.sleep(0.01)
        now = time.perf_counter()
        longest, last = max(longest, now - last), now
    return longest


# --- the concurrency cap ------------------------------------------------------------------


async def test_at_most_the_configured_number_of_fetches_run_at_once():
    tracker = Tracker(delay=0.3)
    app = make_app(tracker.make, slots=2)

    async with http_client(app) as http:
        started = time.perf_counter()
        responses = await asyncio.gather(*(http.get(f"/articles/Page {i}") for i in range(6)))
        elapsed = time.perf_counter() - started

    assert [r.status_code for r in responses] == [200] * 6
    assert tracker.peak == 2  # capped, but really parallel
    assert elapsed < 6 * 0.3 * 0.75  # three waves of two, not six in a row


async def test_requests_over_the_cap_wait_without_a_client_or_a_thread():
    tracker = Tracker(delay=0.4)
    app = make_app(tracker.make, slots=2)

    async with http_client(app) as http:
        tasks = [asyncio.create_task(http.get(f"/articles/Page {i}")) for i in range(6)]
        await asyncio.sleep(0.15)  # the first wave is fetching, the other four are waiting

        assert len(tracker.clients) == 2  # waiting requests have not even created a client
        assert tracker.running == 2

        await asyncio.gather(*tasks)

    assert len(tracker.clients) == 6
    assert all(client.closed for client in tracker.clients)


async def test_waiting_requests_do_not_stall_the_event_loop():
    tracker = Tracker(delay=0.3)
    app = make_app(tracker.make, slots=1)

    async with http_client(app) as http:
        tasks = [asyncio.create_task(http.get(f"/articles/Page {i}")) for i in range(4)]
        stall = await longest_loop_stall(0.8)
        health = await http.get("/health")
        await asyncio.gather(*tasks)

    assert health.status_code == 200
    assert stall < 0.2


@pytest.mark.parametrize(
    "error", [MediaWikiRequestError("down"), ValueError("blank"), RuntimeError("bug")]
)
async def test_a_failed_request_releases_its_slot(error):
    outcomes = iter([error, None])

    def factory() -> FakeClient:
        return FakeClient(Tracker(), delay=0.0, error=next(outcomes))

    app = make_app(factory, slots=1)

    async with http_client(app) as http:
        try:
            first = await http.get("/articles/First")
        except RuntimeError:
            first = None  # the ASGI transport re-raises an unexpected error
        second = await asyncio.wait_for(http.get("/articles/Second"), timeout=2)

    assert first is None or first.status_code in {400, 422}
    assert second.status_code == 200  # the single slot was free again


# --- the shared limit across per-request clients ----------------------------------------


async def test_concurrent_requests_share_one_rate_limit(article_response):
    interval = 0.02
    limiter = RateLimiter(1 / interval)
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json=article_response(title=request.url.params["titles"]))

    def factory() -> MediaWikiClient:  # a new client per request, like the container's Factory
        return MediaWikiClient(
            user_agent="UEZA-test",
            requests_per_second=100_000,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            rate_limiter=limiter,
        )

    app = make_app(factory, slots=6)

    async with http_client(app) as http:
        tasks = [asyncio.create_task(http.get(f"/articles/Page {i}")) for i in range(6)]
        stall = await longest_loop_stall(0.5)
        responses = await asyncio.gather(*tasks)

    ordered = sorted(stamps)
    gaps = [b - a for a, b in zip(ordered, ordered[1:], strict=False)]
    assert [r.status_code for r in responses] == [200] * 6
    assert len(stamps) == 12  # two upstream calls per article
    assert min(gaps) >= interval * 0.5
    assert ordered[-1] - ordered[0] >= 11 * interval * 0.8
    assert stall < 0.2  # the waiting happens in worker threads


# --- cache keys through the URL ---------------------------------------------------------


def cached_app(tmp_path, article_response):
    calls: list[str] = []
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=3600)

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params["titles"]
        calls.append(title)
        return httpx.Response(200, json=article_response(title=title))

    def factory() -> MediaWikiClient:
        return MediaWikiClient(
            user_agent="UEZA-test",
            requests_per_second=100_000,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            cache=cache,
        )

    return make_app(factory), calls


async def get_all(app, *paths: str) -> list[int]:
    async with http_client(app) as http:
        return [(await http.get(path)).status_code for path in paths]


async def test_url_encoded_underscore_and_first_letter_variants_hit_the_same_entry(
    tmp_path, article_response
):
    app, calls = cached_app(tmp_path, article_response)
    title = "Python (programming language)"

    await get_all(app, "/articles/" + quote(title))
    stored = len(calls)
    statuses = await get_all(
        app,
        "/articles/" + quote(title.replace(" ", "_")),
        "/articles/" + quote(title.lower()),
        "/articles/" + title.replace(" ", "%20").replace("(", "%28").replace(")", "%29"),
    )

    assert statuses == [200, 200, 200]
    assert len(calls) == stored  # nothing more went upstream


async def test_unicode_titles_match_across_composed_and_decomposed_forms(
    tmp_path, article_response
):
    app, calls = cached_app(tmp_path, article_response)

    await get_all(app, "/articles/" + quote("Café"))
    stored = len(calls)
    await get_all(app, "/articles/" + quote("Café"))
    assert len(calls) == stored  # NFD is the same title

    await get_all(app, "/articles/" + quote("Cafe"))
    assert len(calls) > stored  # a different title is fetched


async def test_a_double_encoded_title_is_not_merged_with_the_decoded_one(
    tmp_path, article_response
):
    app, calls = cached_app(tmp_path, article_response)

    await get_all(app, "/articles/Foo%20Bar")
    stored = len(calls)
    await get_all(app, "/articles/Foo%2520Bar")  # the title "Foo%20Bar", literally

    assert len(calls) > stored
