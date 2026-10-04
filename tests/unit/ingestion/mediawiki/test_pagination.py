import httpx


def test_collects_multiple_pages(
    client_factory,
    article_response,
) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1

        if requests == 1:
            data = article_response(
                categories=["Machine learning"],
                links=["Artificial intelligence"],
            )

            data["continue"] = {
                "continue": "||",
                "plcontinue": "233488|0|Deep_learning",
            }

            return httpx.Response(
                200,
                json=data,
            )

        assert request.url.params["continue"] == "||"

        assert request.url.params["plcontinue"] == "233488|0|Deep_learning"

        return httpx.Response(
            200,
            json=article_response(
                categories=["Artificial intelligence"],
                links=["Deep learning"],
            ),
        )

    client = client_factory(handler)

    article = client.get_article("Machine learning")

    assert requests == 2

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

        if requests == 1:
            data = article_response(
                categories=["Machine learning"],
                links=["Deep learning"],
            )

            data["continue"] = {
                "continue": "||",
                "plcontinue": "next",
            }

            return httpx.Response(
                200,
                json=data,
            )

        return httpx.Response(
            200,
            json=article_response(
                categories=["Machine learning"],
                links=["Deep learning"],
            ),
        )

    client = client_factory(handler)

    article = client.get_article("Machine learning")

    assert article.categories == ("Machine learning",)

    assert article.links == ("Deep learning",)
