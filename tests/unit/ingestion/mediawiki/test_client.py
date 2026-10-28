"""Tests for the MediaWiki article client."""

from datetime import UTC, datetime

import httpx
import pytest

from src.ingestion.mediawiki import MediaWikiPageNotFoundError


def test_get_article(client_factory, article_response) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        requests.append(params["prop"])

        assert params["action"] == "query"
        assert params["titles"] == "Machine learning"
        assert params["redirects"] == "1"

        if params["prop"] == "info|revisions":
            assert params["rvprop"] == "ids|timestamp|size|content"
            assert params["rvslots"] == "main"
            return httpx.Response(200, json=article_response())

        assert params["prop"] == "categories|links"
        assert params["plnamespace"] == "0"

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

    assert requests == ["info|revisions", "categories|links"]
    assert article.page_id == 233488
    assert article.title == "Machine learning"
    assert article.length == 1000
    assert article.revision_id == 12345
    assert article.last_modified.isoformat() == "2026-10-01T12:00:00+00:00"
    assert article.text == "'''Machine learning''' is..."
    assert article.categories == (
        "Machine learning",
        "Artificial intelligence",
    )
    assert article.links == (
        "Artificial intelligence",
        "Deep learning",
    )


def test_get_article_strips_title(client_factory, article_response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == "Machine learning"
        return httpx.Response(200, json=article_response())

    client = client_factory(handler)
    article = client.get_article("   Machine learning   ")

    assert article.title == "Machine learning"


def test_get_article_rejects_empty_title(client_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP request should not be made")

    client = client_factory(handler)

    with pytest.raises(ValueError, match="title cannot be empty"):
        client.get_article("   ")


def test_missing_page(client_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"query": {"pages": [{"title": "DoesNotExist123", "missing": True}]}},
        )

    client = client_factory(handler)

    with pytest.raises(MediaWikiPageNotFoundError, match="DoesNotExist123"):
        client.get_article("DoesNotExist123")


def test_redirect(client_factory, article_response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["redirects"] == "1"

        data = article_response(title="Machine learning")
        data["query"]["redirects"] = [{"from": "ML", "to": "Machine learning"}]

        return httpx.Response(200, json=data)

    client = client_factory(handler)
    article = client.get_article("ML")

    assert article.title == "Machine learning"
    assert article.page_id == 233488


def test_snapshot_uses_the_revision_size_and_skips_hidden_categories(
    client_factory, article_response
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params

        if params["prop"] == "info|revisions":
            assert params["rvstart"] == "2026-01-01T00:00:00Z"
            assert params["rvdir"] == "older"
            # The page is 5000 bytes today; the revision at the snapshot date was 4200.
            return httpx.Response(200, json=article_response(length=5000, size=4200))

        assert params["clshow"] == "!hidden"
        return httpx.Response(200, json=article_response())

    client = client_factory(handler)
    snapshot = datetime(2026, 1, 1, tzinfo=UTC)
    article = client.get_article("Machine learning", as_of=snapshot)

    assert article.length == 4200
