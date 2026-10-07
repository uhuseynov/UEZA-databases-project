import httpx

import pytest

from src.ingestion.mediawiki import (
    MediaWikiClient,
    MediaWikiPageNotFoundError,
)

pytestmark = pytest.mark.integration


def test_fetch_article(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "en.wikipedia.org"
        assert request.url.path == "/w/api.php"
        assert request.headers["User-Agent"].startswith("UEZA-Databases-Project/")
        assert request.url.params["action"] == "query"
        assert request.url.params["format"] == "json"
        assert request.url.params["formatversion"] == "2"
        assert request.url.params["titles"] == "Machine learning"
        assert request.url.params["redirects"] == "1"
        assert request.url.params["prop"] == "info|revisions|categories|links"
        assert request.url.params["rvprop"] == "ids|timestamp|content"
        assert request.url.params["rvslots"] == "main"
        assert request.url.params["cllimit"] == "max"
        assert request.url.params["pllimit"] == "max"
        assert request.url.params["plnamespace"] == "0"
        assert request.url.params["maxlag"] == "5"

        return httpx.Response(
            200,
            json=article_response(
                categories=["Machine learning", "Artificial intelligence"],
                links=["Artificial intelligence", "Deep learning"],
                content=(
                    "Machine learning is a field of study in artificial intelligence "
                    "that uses data and algorithms to improve performance over time."
                ),
            ),
        )

    client = client_factory(handler)
    article = client.get_article("Machine learning")

    assert article.page_id > 0
    assert article.title == "Machine learning"
    assert article.length > 0
    assert article.revision_id > 0

    assert article.text
    assert len(article.text) > 100

    assert article.categories
    assert article.links


def test_redirect(
    client_factory,
    article_response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == "ML"
        assert request.url.params["redirects"] == "1"

        data = article_response(title="Machine learning")
        data["query"]["redirects"] = [{"from": "ML", "to": "Machine learning"}]
        return httpx.Response(200, json=data)

    client = client_factory(handler)
    article = client.get_article("ML")

    assert article.page_id > 0
    assert article.title == "Machine learning"
    assert article.title


def test_missing_page(
    client_factory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == "ThisPageShouldNotExistEgehan123456789"
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "ThisPageShouldNotExistEgehan123456789",
                            "missing": True,
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    with pytest.raises(MediaWikiPageNotFoundError):
        client.get_article("ThisPageShouldNotExistEgehan123456789")
