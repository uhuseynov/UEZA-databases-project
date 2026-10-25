"""Tests for MediaWiki client caching."""

import httpx

from src.ingestion.cache import ArticleCache


def test_client_uses_cached_article(
    tmp_path,
    client_factory,
    article_response,
) -> None:
    cache = ArticleCache(
        cache_dir=str(tmp_path),
        ttl_seconds=3600,
    )

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.params["prop"])

        return httpx.Response(
            200,
            json=article_response(
                title="Python",
                categories=["Programming languages"],
                links=["Computer science"],
            ),
        )

    client = client_factory(handler, cache=cache)

    first = client.get_article("Python")

    assert requests == ["info|revisions", "categories|links"]
    assert first.title == "Python"

    second = client.get_article("Python")

    assert len(requests) == 2
    assert second == first
