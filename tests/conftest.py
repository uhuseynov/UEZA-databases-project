from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.ingestion.mediawiki import MediaWikiClient

type RequestHandler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def client_factory():
    clients: list[httpx.Client] = []

    def create(
        handler: RequestHandler,
        *,
        max_retries: int = 3,
        batch_size: int = 20,
        cache=None,
    ) -> MediaWikiClient:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(
            transport=transport,
            headers={
                "User-Agent": "test-client",
            },
        )
        clients.append(http_client)
        return MediaWikiClient(
            user_agent="test-client",
            requests_per_second=100_000,
            max_retries=max_retries,
            batch_size=batch_size,
            client=http_client,
            cache=cache,
        )

    yield create

    for client in clients:
        client.close()


@pytest.fixture
def article_response():
    def create(
        *,
        title: str = "Machine learning",
        page_id: int = 233488,
        length: int = 1000,
        revision_id: int = 12345,
        timestamp: str = "2026-10-01T12:00:00Z",
        content: str = "'''Machine learning''' is...",
        categories: list[str] | None = None,
        links: list[str] | None = None,
    ) -> dict[str, Any]:
        page: dict[str, Any] = {
            "pageid": page_id,
            "title": title,
            "length": length,
            "revisions": [
                {
                    "revid": revision_id,
                    "timestamp": timestamp,
                    "slots": {
                        "main": {
                            "content": content,
                        }
                    },
                }
            ],
        }

        if categories is not None:
            page["categories"] = [
                {
                    "title": f"Category:{category}",
                }
                for category in categories
            ]

        if links is not None:
            page["links"] = [
                {
                    "title": link,
                }
                for link in links
            ]

        return {
            "query": {
                "pages": [page],
            }
        }

    return create
