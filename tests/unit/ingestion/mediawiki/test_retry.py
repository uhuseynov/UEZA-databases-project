import httpx
import pytest

from src.ingestion.mediawiki import (
    MediaWikiAPIError,
    MediaWikiClient,
    MediaWikiRateLimitError,
    MediaWikiRequestError,
)


@pytest.fixture(autouse=True)
def disable_retry_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MediaWikiClient,
        "_backoff",
        staticmethod(lambda attempt: None),
    )

    monkeypatch.setattr(
        MediaWikiClient,
        "_wait_for_retry",
        staticmethod(lambda response, attempt: None),
    )


def test_retries_503(
    client_factory,
    article_response,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(503)

        return httpx.Response(
            200,
            json=article_response(),
        )

    client = client_factory(handler)

    article = client.get_article("Machine learning")

    assert attempts == 2
    assert article.page_id == 233488


@pytest.mark.parametrize(
    "status_code",
    [
        502,
        503,
        504,
    ],
)
def test_retries_transient_server_errors(
    client_factory,
    article_response,
    status_code: int,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(status_code)

        return httpx.Response(
            200,
            json=article_response(),
        )

    client = client_factory(handler)

    client.get_article("Machine learning")

    assert attempts == 2


def test_transient_error_exhausts_retries(
    client_factory,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        return httpx.Response(503)

    client = client_factory(
        handler,
        max_retries=2,
    )

    with pytest.raises(MediaWikiRequestError):
        client.get_article("Machine learning")

    assert attempts == 3


def test_retries_429(
    client_factory,
    article_response,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(
                429,
                headers={
                    "Retry-After": "1",
                },
            )

        return httpx.Response(
            200,
            json=article_response(),
        )

    client = client_factory(handler)

    client.get_article("Machine learning")

    assert attempts == 2


def test_rate_limit_exhausts_retries(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = client_factory(
        handler,
        max_retries=1,
    )

    with pytest.raises(MediaWikiRateLimitError):
        client.get_article("Machine learning")


def test_retries_maxlag(
    client_factory,
    article_response,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(
                200,
                json={
                    "error": {
                        "code": "maxlag",
                        "info": "Waiting for replicas",
                    }
                },
            )

        return httpx.Response(
            200,
            json=article_response(),
        )

    client = client_factory(handler)

    client.get_article("Machine learning")

    assert attempts == 2


def test_maxlag_exhausts_retries(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": {
                    "code": "maxlag",
                    "info": "Still lagging",
                }
            },
        )

    client = client_factory(
        handler,
        max_retries=1,
    )

    with pytest.raises(MediaWikiAPIError):
        client.get_article("Machine learning")


def test_non_retryable_http_error(
    client_factory,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1

        return httpx.Response(404)

    client = client_factory(handler)

    with pytest.raises(MediaWikiRequestError):
        client.get_article("Machine learning")

    assert attempts == 1
