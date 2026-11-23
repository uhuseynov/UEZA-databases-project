"""One rate limiter can be shared by many clients, and by the clients of the container."""

import threading
import time

import httpx

from src.containers import Container
from src.ingestion.mediawiki import MediaWikiClient
from src.ingestion.mediawiki.rate_limiter import RateLimiter

INTERVAL = 0.04  # 25 requests per second


def make_clients(count: int, stamps: list[float], *, limiter_for) -> list[MediaWikiClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json={"query": {}})

    return [
        MediaWikiClient(
            user_agent="UEZA-test",
            requests_per_second=100_000,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            rate_limiter=limiter_for(index),
        )
        for index in range(count)
    ]


def run_concurrently(clients: list[MediaWikiClient], requests_each: int) -> None:
    def work(client: MediaWikiClient) -> None:
        for _ in range(requests_each):
            client._request({"action": "query"})

    threads = [threading.Thread(target=work, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def gaps(stamps: list[float]) -> list[float]:
    ordered = sorted(stamps)
    return [later - earlier for earlier, later in zip(ordered, ordered[1:], strict=False)]


def test_clients_sharing_a_limiter_share_its_limit():
    stamps: list[float] = []
    shared = RateLimiter(1 / INTERVAL)
    clients = make_clients(4, stamps, limiter_for=lambda index: shared)

    run_concurrently(clients, requests_each=3)

    assert len(stamps) == 12
    assert min(gaps(stamps)) >= INTERVAL * 0.5  # never faster than the shared limit, with slack
    assert max(stamps) - min(stamps) >= 11 * INTERVAL * 0.8


def test_clients_with_their_own_limiters_do_not_limit_each_other():
    """The behaviour before the limiter was shared: the control for the test above."""
    stamps: list[float] = []
    clients = make_clients(4, stamps, limiter_for=lambda index: RateLimiter(1 / INTERVAL))

    run_concurrently(clients, requests_each=1)

    assert len(stamps) == 4
    assert max(stamps) - min(stamps) < INTERVAL  # four clients, four requests at once


def test_waiting_for_a_slot_is_not_a_lock_around_the_request_itself():
    """The limiter only spaces the *start* of requests: a slow request does not hold up the next
    slot, so unrelated requests overlap."""
    shared = RateLimiter(1 / INTERVAL)
    running = 0
    peak = 0
    guard = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        time.sleep(0.25)  # a slow upstream
        with guard:
            running -= 1
        return httpx.Response(200, json={"query": {}})

    clients = [
        MediaWikiClient(
            user_agent="UEZA-test",
            requests_per_second=100_000,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            rate_limiter=shared,
        )
        for _ in range(4)
    ]

    started = time.monotonic()
    run_concurrently(clients, requests_each=1)

    assert peak >= 3  # the four slow requests ran side by side
    assert time.monotonic() - started < 4 * 0.25 * 0.6


def test_a_client_without_a_limiter_builds_its_own_from_the_rate():
    client = MediaWikiClient(user_agent="UEZA-test", requests_per_second=4.0)
    try:
        assert client._rate_limiter._interval == 0.25
    finally:
        client.close()


def test_the_container_gives_every_client_the_same_limiter():
    container = Container()
    first, second = container.mediawiki_client(), container.mediawiki_client()
    try:
        assert first._rate_limiter is second._rate_limiter
        assert first._rate_limiter is container.mediawiki_rate_limiter()
        assert first._cache is second._cache
        assert first._client is not second._client  # but each owns its HTTP connections
    finally:
        first.close()
        second.close()


def test_the_shared_limiter_uses_the_configured_rate():
    container = Container()

    assert (
        container.mediawiki_rate_limiter()._interval
        == 1 / container.config().mediawiki_requests_per_second
    )
