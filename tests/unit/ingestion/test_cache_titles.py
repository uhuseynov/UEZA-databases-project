"""Cache keys follow MediaWiki's title rules, and no more than that."""

import hashlib
import json
import os
from datetime import UTC, datetime

import httpx
import pytest

from src.ingestion.cache import ArticleCache, normalize_title
from src.ingestion.mediawiki import MediaWikiClient, WikiArticle


def article(
    title: str = "Machine learning", revision_id: int = 100, page_id: int = 7
) -> WikiArticle:
    return WikiArticle(
        page_id=page_id,
        title=title,
        text="Content",
        length=7,
        revision_id=revision_id,
        last_modified=datetime(2026, 10, 1, tzinfo=UTC),
        categories=("CatA",),
        links=("LinkA",),
    )


@pytest.fixture
def cache(tmp_path) -> ArticleCache:
    return ArticleCache(cache_dir=str(tmp_path), ttl_seconds=3600)


def files(cache: ArticleCache) -> list[str]:
    return sorted(path.name for path in cache.cache_path.iterdir())


# --- which spellings are one page ------------------------------------------------------------

SAME_PAGE = [
    ("Machine learning", "Machine_learning"),
    ("Machine learning", "machine learning"),  # the first letter is case-insensitive
    ("Machine learning", "  Machine   learning "),
    ("Machine learning", "Machine__learning"),
    ("Machine learning", "Machine _ learning"),
    ("Python (programming language)", "Python_(programming_language)"),
    ("Café", "Café"),  # NFC and NFD
    ("Ångström", "Ångström"),
    ("IPhone", "iPhone"),
    ("Zürich", "zürich"),
]


@pytest.mark.parametrize(("first", "second"), SAME_PAGE)
def test_spellings_that_mediawiki_treats_as_one_title_share_a_key(cache, first, second):
    assert normalize_title(first) == normalize_title(second)
    assert cache._get_file_path(first) == cache._get_file_path(second)


DIFFERENT_PAGES = [
    ("IPhone", "Iphone"),  # only the first letter is case-insensitive
    ("AI", "Ai"),
    ("Machine learning", "Machine Learning"),
    ("Café", "Cafe"),
    ("Ångström", "Angstrom"),
    ("Foo Bar", "Foo%20Bar"),  # percent-encoding is decoded by the URL layer, never here
    ("Foo Bar", "Foo%2520Bar"),
    ("Foo", "Foo (disambiguation)"),
    ("Foo", "Foo."),
    ("Foo+Bar", "Foo Bar"),  # "+" is a plus sign in a title, not a space
    ("Foo-Bar", "Foo Bar"),
]


@pytest.mark.parametrize(("first", "second"), DIFFERENT_PAGES)
def test_distinct_pages_never_share_a_key(cache, first, second):
    assert cache._get_file_path(first) != cache._get_file_path(second)


def test_only_the_first_letter_is_capitalized():
    assert normalize_title("machine learning (ML)") == "Machine learning (ML)"
    assert normalize_title("iPhone 15 pro") == "IPhone 15 pro"


def test_a_first_letter_whose_capital_is_longer_is_left_alone():
    assert "ß".upper() == "SS"
    assert normalize_title("ßeta") == "ßeta"


def test_titles_are_not_lowercased_or_otherwise_rewritten():
    title = "Hubert Dreyfus's views on artificial intelligence"

    assert normalize_title(title) == title
    assert normalize_title("Kolmogorov–Arnold Networks") == "Kolmogorov–Arnold Networks"


@pytest.mark.parametrize(
    "canonical", ["Machine learning", "IPhone", "Python (programming language)"]
)
def test_normalizing_a_canonical_title_changes_nothing(canonical):
    assert normalize_title(canonical) == canonical


# --- compatibility with files written by earlier versions ------------------------------------


def legacy_file(cache: ArticleCache, key: str, article: WikiArticle) -> str:
    """A cache file as the version before the normalization wrote it: sha256 of the title."""
    name = hashlib.sha256(key.encode()).hexdigest() + ".json"
    data = {
        "page_id": article.page_id,
        "title": article.title,
        "text": article.text,
        "length": article.length,
        "revision_id": article.revision_id,
        "last_modified": article.last_modified.isoformat(),
        "categories": list(article.categories),
        "links": list(article.links),
    }
    (cache.cache_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return name


def test_entries_written_by_the_earlier_version_are_still_found(cache):
    name = legacy_file(cache, "Machine learning", article())

    assert cache.get("Machine learning") == article()
    assert cache.get("machine_learning") == article()  # and by the new spellings
    assert files(cache) == [name]


def test_a_lookup_never_rewrites_or_deletes_an_existing_entry(cache):
    name = legacy_file(cache, "Machine learning", article())
    path = cache.cache_path / name
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    cache.get("Machine learning")
    cache.get("machine_learning")
    cache.get("Never stored")

    assert files(cache) == [name]
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_an_entry_under_an_unusual_spelling_is_found_through_the_exact_title(cache):
    name = legacy_file(cache, "Odd__Title", article(title="Odd Title"))

    assert cache.get("Odd__Title") == article(title="Odd Title")
    assert files(cache) == [name]


def test_new_entries_use_the_normalized_canonical_title(cache):
    cache.set(article("Machine learning"))

    assert files(cache) == [hashlib.sha256(b"Machine learning").hexdigest() + ".json"]


# --- redirect aliases ----------------------------------------------------------------------


def test_an_alias_that_was_never_fetched_is_a_miss(cache):
    cache.set(article("Machine learning"))

    assert cache.get("ML") is None


def test_a_fetched_alias_points_at_its_target(cache):
    cache.set(article("Machine learning"), requested_title="Ml basics")

    assert cache.get("Ml basics") == article("Machine learning")
    assert cache.get("ml_basics") == article("Machine learning")  # spelling variants of the alias
    assert cache.get("ML basics") is None  # a different title: only the first letter is folded
    assert len(files(cache)) == 2


def test_no_alias_is_written_for_another_spelling_of_the_same_title(cache):
    cache.set(article("Machine learning"), requested_title="machine_learning")

    assert len(files(cache)) == 1


def test_an_alias_is_a_miss_once_its_target_is_gone(cache):
    cache.set(article("Machine learning"), requested_title="ML")
    os.remove(cache._get_file_path("Machine learning"))

    assert cache.get("ML") is None


def test_an_alias_expires_on_its_own_so_a_changed_redirect_is_noticed(cache):
    cache.set(article("Machine learning"), requested_title="ML")
    old = datetime.now(UTC).timestamp() - 7200
    os.utime(cache._get_file_path("ML"), (old, old))

    assert cache.get("ML") is None
    assert cache.get("Machine learning") is not None


def test_an_alias_does_not_chain_to_another_alias(cache):
    cache.set(article("Machine learning"), requested_title="ML")
    cache.set(article("Machine learning"), requested_title="Machine Learning (field)")
    alias_path = cache._get_file_path("ML")
    other = cache._get_file_path("Machine Learning (field)")
    alias_path.write_text(json.dumps({"alias_of": "Machine Learning (field)"}), encoding="utf-8")

    assert other.is_file()
    assert cache.get("ML") is None


def test_a_real_article_replaces_an_alias_of_the_same_title(cache):
    cache.set(article("Machine learning"), requested_title="ML")
    cache.set(article("ML", revision_id=5, page_id=9))

    assert cache.get("ML") == article("ML", revision_id=5, page_id=9)


# --- through the client, over mocked HTTP --------------------------------------------------


def make_client(cache: ArticleCache, handler) -> MediaWikiClient:
    return MediaWikiClient(
        user_agent="UEZA-test",
        requests_per_second=100_000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache=cache,
    )


def test_a_redirect_is_resolved_upstream_once_then_served_locally(cache, article_response):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["titles"])
        data = article_response(title="Machine learning", page_id=233488)
        data["query"]["redirects"] = [{"from": "ML", "to": "Machine learning"}]
        return httpx.Response(200, json=data)

    client = make_client(cache, handler)

    first = client.get_article("ML")
    assert len(calls) == 2  # an alias that was never resolved needs MediaWiki
    assert first.title == "Machine learning"

    assert client.get_article("ML") == first
    assert client.get_article("Machine_learning") == first
    assert client.get_article("Machine learning") == first
    assert len(calls) == 2  # nothing more went upstream


def test_another_spelling_of_a_stored_title_does_not_go_upstream(cache, article_response):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["titles"])
        return httpx.Response(200, json=article_response(title="Python (programming language)"))

    client = make_client(cache, handler)
    client.get_article("Python (programming language)")
    stored = len(calls)

    client.get_article("Python_(programming_language)")
    client.get_article("python (programming language)")

    assert len(calls) == stored


def test_a_distinct_title_is_fetched_not_confused_with_a_cached_one(cache, article_response):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        title = request.url.params["titles"]
        calls.append(title)
        return httpx.Response(200, json=article_response(title=title))

    client = make_client(cache, handler)
    client.get_article("IPhone")
    after_first = len(calls)

    client.get_article("Iphone")

    assert len(calls) > after_first
