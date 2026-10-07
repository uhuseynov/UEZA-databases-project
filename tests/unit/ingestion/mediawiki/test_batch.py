import httpx


def test_get_articles(
    client_factory,
    article_response,
) -> None:
    batch_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_requests

        prop = request.url.params["prop"]

        if prop == "info|revisions":
            batch_requests += 1

            assert request.url.params["titles"] == ("Machine learning|Deep learning")

            ml = article_response(
                title="Machine learning",
            )["query"]["pages"][0]

            dl = article_response(
                title="Deep learning",
                page_id=2,
                content="Deep learning...",
            )["query"]["pages"][0]

            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [ml, dl],
                    }
                },
            )

        title = request.url.params["titles"]

        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 1,
                            "title": title,
                            "categories": [{"title": f"Category:{title}"}],
                            "links": [],
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    articles = client.get_articles(
        [
            "Machine learning",
            "Deep learning",
        ]
    )

    assert len(articles) == 2

    assert [article.title for article in articles] == [
        "Machine learning",
        "Deep learning",
    ]

    assert batch_requests == 1


def test_get_articles_deduplicates_titles(
    client_factory,
    article_response,
) -> None:
    seen_batch_titles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prop = request.url.params["prop"]

        if prop == "info|revisions":
            titles = request.url.params["titles"]

            seen_batch_titles.extend(titles.split("|"))

            pages = [
                article_response(
                    title=title,
                )["query"]["pages"][0]
                for title in titles.split("|")
            ]

            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": pages,
                    }
                },
            )

        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 1,
                            "title": request.url.params["titles"],
                        }
                    ]
                }
            },
        )

    client = client_factory(handler)

    client.get_articles(
        [
            "Machine learning",
            "Machine learning",
            " Deep learning ",
        ]
    )

    assert seen_batch_titles == [
        "Machine learning",
        "Deep learning",
    ]


def test_get_articles_respects_batch_size(
    client_factory,
    article_response,
) -> None:
    batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["prop"] == "info|revisions":
            titles = request.url.params["titles"].split("|")

            batches.append(titles)

            pages = [
                article_response(
                    title=title,
                )["query"]["pages"][0]
                for title in titles
            ]

            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": pages,
                    }
                },
            )

        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 1,
                            "title": request.url.params["titles"],
                        }
                    ]
                }
            },
        )

    client = client_factory(
        handler,
        batch_size=2,
    )

    client.get_articles(
        [
            "A",
            "B",
            "C",
            "D",
            "E",
        ]
    )

    assert batches == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]
