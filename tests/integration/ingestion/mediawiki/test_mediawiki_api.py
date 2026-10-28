"""Integration-style tests for the MediaWiki client."""

import httpx
import pytest

from src.ingestion.mediawiki import MediaWikiPageNotFoundError

pytestmark = pytest.mark.integration


def test_fetch_article(client_factory, article_response) -> None:
    seen = []

    content = (
        "Machine learning is a field of study in artificial intelligence "
        "that uses data and algorithms to improve performance over time."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        seen.append(params["prop"])

        assert request.url.host == "en.wikipedia.org"
        assert request.url.path == "/w/api.php"
        assert request.headers["User-Agent"].startswith("UEZA-Databases-Project/")
        assert params["action"] == "query"
        assert params["format"] == "json"
        assert params["formatversion"] == "2"
        assert params["titles"] == "Machine learning"
        assert params["redirects"] == "1"
        assert params["maxlag"] == "5"

        if params["prop"] == "info|revisions":
            assert params["rvprop"] == "ids|timestamp|size|content"
            assert params["rvslots"] == "main"
            assert params["rvlimit"] == "1"

            return httpx.Response(
                200,
                json=article_response(content=content),
            )

        assert params["prop"] == "categories|links"
        assert params["cllimit"] == "max"
        assert params["pllimit"] == "max"
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

    assert seen == ["info|revisions", "categories|links"]
    assert article.page_id == 233488
    assert article.title == "Machine learning"
    assert article.length > 0
    assert article.revision_id > 0
    assert article.text == content
    assert article.categories == (
        "Machine learning",
        "Artificial intelligence",
    )
    assert article.links == (
        "Artificial intelligence",
        "Deep learning",
    )


def test_redirect(client_factory, article_response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == "ML"
        assert request.url.params["redirects"] == "1"

        data = article_response(title="Machine learning")
        data["query"]["redirects"] = [{"from": "ML", "to": "Machine learning"}]

        return httpx.Response(200, json=data)

    client = client_factory(handler)
    article = client.get_article("ML")

    assert article.page_id == 233488
    assert article.title == "Machine learning"


def test_missing_page(client_factory) -> None:
    title = "ThisPageShouldNotExistEgehan123456789"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["titles"] == title

        return httpx.Response(
            200,
            json={"query": {"pages": [{"title": title, "missing": True}]}},
        )

    client = client_factory(handler)

    with pytest.raises(MediaWikiPageNotFoundError):
        client.get_article(title)
