import httpx
import pytest

from src.ingestion.mediawiki import (
    MediaWikiPageNotFoundError,
)


def test_get_article(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["action"] == "query"
        assert request.url.params["titles"] == "Machine learning"
        assert request.url.params["redirects"] == "1"
        assert request.url.params["plnamespace"] == "0"

        return httpx.Response(
            200,
            json=article_response(
                categories=[
                    "Machine learning",
                    "Artificial intelligence",
                ],
                links=[
                    "Artificial intelligence",
                    "Deep learning",
                ],
            ),
        )

    client = client_factory(handler)

    article = client.get_article("Machine learning")

    assert article.page_id == 233488
    assert article.title == "Machine learning"
    assert article.length == 1000
    assert article.revision_id == 12345

    assert article.last_modified.isoformat() == ("2026-10-01T12:00:00+00:00")

    assert article.text == "'''Machine learning''' is..."

    assert article.categories == (
        "Machine learning",
        "Artificial intelligence",
    )

    assert article.links == (
        "Artificial intelligence",
        "Deep learning",
    )


def test_get_article_strips_title(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == "Machine learning"

        return httpx.Response(
            200,
            json=article_response(),
        )

    client = client_factory(handler)

    client.get_article("   Machine learning   ")


def test_get_article_rejects_empty_title(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP request should not be made")

    client = client_factory(handler)

    with pytest.raises(
        ValueError,
        match="title cannot be empty",
    ):
        client.get_article("   ")


def test_missing_page(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "DoesNotExist123",
                            "missing": True,
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    with pytest.raises(
        MediaWikiPageNotFoundError,
        match="DoesNotExist123",
    ):
        client.get_article("DoesNotExist123")


def test_redirect(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["redirects"] == "1"

        data = article_response(
            title="Machine learning",
        )

        data["query"]["redirects"] = [
            {
                "from": "ML",
                "to": "Machine learning",
            }
        ]

        return httpx.Response(
            200,
            json=data,
        )

    client = client_factory(handler)

    article = client.get_article("ML")

    assert article.title == "Machine learning"
    assert article.page_id == 233488
