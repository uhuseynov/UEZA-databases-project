"""Tests for independent MediaWiki metadata pagination."""

import httpx


def test_collects_multiple_pages(
    client_factory,
    article_response,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        requests.append(params["prop"])

        if params["prop"] == "info|revisions":
            return httpx.Response(
                200,
                json=article_response(),
            )

        assert params["prop"] == "categories|links"
        assert "rvcontinue" not in params

        if "plcontinue" not in params:
            data = article_response(
                categories=["Machine learning"],
                links=["Artificial intelligence"],
            )
            data["continue"] = {
                "continue": "||",
                "plcontinue": "233488|0|Deep_learning",
            }
            return httpx.Response(200, json=data)

        assert params["continue"] == "||"
        assert params["plcontinue"] == "233488|0|Deep_learning"

        return httpx.Response(
            200,
            json=article_response(
                categories=["Artificial intelligence"],
                links=["Deep learning"],
            ),
        )

    client = client_factory(handler)
    article = client.get_article("Machine learning")

    assert requests == [
        "info|revisions",
        "categories|links",
        "categories|links",
    ]

    assert article.categories == (
        "Machine learning",
        "Artificial intelligence",
    )
    assert article.links == (
        "Artificial intelligence",
        "Deep learning",
    )


def test_deduplicates_paginated_values(
    client_factory,
    article_response,
) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1

        if request.url.params["prop"] == "info|revisions":
            return httpx.Response(200, json=article_response())

        data = article_response(
            categories=["Machine learning"],
            links=["Deep learning"],
        )

        if "plcontinue" not in request.url.params:
            data["continue"] = {
                "continue": "||",
                "plcontinue": "next",
            }

        return httpx.Response(200, json=data)

    client = client_factory(handler)
    article = client.get_article("Machine learning")

    assert requests == 3
    assert article.categories == ("Machine learning",)
    assert article.links == ("Deep learning",)
