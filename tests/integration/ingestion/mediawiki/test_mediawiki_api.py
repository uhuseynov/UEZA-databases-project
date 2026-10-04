from collections.abc import Iterator

import pytest

from src.ingestion.mediawiki import (
    MediaWikiClient,
    MediaWikiPageNotFoundError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def wiki() -> Iterator[MediaWikiClient]:
    with MediaWikiClient(
        user_agent=("MariaDB-RAG-Hackathon-Integration-Test/0.1 (university project)"),
        requests_per_second=1.0,
    ) as client:
        yield client


def test_fetch_real_article(
    wiki: MediaWikiClient,
) -> None:
    article = wiki.get_article("Machine learning")

    assert article.page_id > 0
    assert article.title == "Machine learning"
    assert article.length > 0
    assert article.revision_id > 0

    assert article.text
    assert len(article.text) > 100

    assert article.categories
    assert article.links


def test_real_redirect(
    wiki: MediaWikiClient,
) -> None:
    article = wiki.get_article("ML")

    assert article.page_id > 0
    assert article.title


def test_real_missing_page(
    wiki: MediaWikiClient,
) -> None:
    with pytest.raises(MediaWikiPageNotFoundError):
        wiki.get_article("ThisPageShouldNotExistEgehan123456789")
