import datetime
import time

from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki.models import WikiArticle


def test_article_cache_set_and_get(tmp_path):
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=60)
    article = WikiArticle(
        page_id=1,
        title="Test Article",
        text="Content",
        length=7,
        revision_id=100,
        last_modified=datetime.datetime.now(datetime.UTC),
        categories=("CatA",),
        links=("LinkA",),
    )

    cache.set(article)
    retrieved = cache.get("Test Article")

    assert retrieved is not None
    assert retrieved.page_id == 1
    assert retrieved.title == "Test Article"
    assert retrieved.categories == ("CatA",)
    assert retrieved.links == ("LinkA",)


def test_article_cache_miss(tmp_path):
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=60)
    assert cache.get("Non Existent") is None


def test_article_cache_ttl_expiration(tmp_path):
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=1)
    article = WikiArticle(
        page_id=2,
        title="Expiring",
        text="Content",
        length=7,
        revision_id=101,
        last_modified=datetime.datetime.now(datetime.UTC),
        categories=(),
        links=(),
    )

    cache.set(article)
    assert cache.get("Expiring") is not None

    time.sleep(1.1)
    assert cache.get("Expiring") is None
