import httpx
import pytest

from src.ingestion.mediawiki import (
    MediaWikiAPIError,
    MediaWikiInvalidResponseError,
)


def test_api_error(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": {
                    "code": "badvalue",
                    "info": "Something went wrong",
                }
            },
        )

    client = client_factory(handler)

    with pytest.raises(
        MediaWikiAPIError,
        match="badvalue",
    ):
        client.get_article("Machine learning")


def test_invalid_json(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not json",
        )

    client = client_factory(handler)

    with pytest.raises(
        MediaWikiInvalidResponseError,
        match="invalid JSON",
    ):
        client.get_article("Machine learning")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": {}},
        {"query": {"pages": None}},
        {"query": {"pages": "wrong"}},
    ],
)
def test_invalid_pages(
    client_factory,
    payload,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
        )

    client = client_factory(handler)

    with pytest.raises(MediaWikiInvalidResponseError):
        client.get_article("Machine learning")


def test_missing_revision(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 233488,
                            "title": "Machine learning",
                            "length": 1000,
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    with pytest.raises(
        MediaWikiInvalidResponseError,
        match="no revision data",
    ):
        client.get_article("Machine learning")


def test_missing_revision_content(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 233488,
                            "title": "Machine learning",
                            "length": 1000,
                            "revisions": [
                                {
                                    "revid": 12345,
                                    "timestamp": "2026-10-01T12:00:00Z",
                                }
                            ],
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    with pytest.raises(
        MediaWikiInvalidResponseError,
        match="main slot content",
    ):
        client.get_article("Machine learning")


def test_invalid_timestamp(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=article_response(
                timestamp="definitely-not-a-date",
            ),
        )

    client = client_factory(handler)

    with pytest.raises(MediaWikiInvalidResponseError):
        client.get_article("Machine learning")
