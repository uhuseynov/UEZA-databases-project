"""Wikipedia MediaWiki API client."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Self

import httpx

from .errors import (
    MediaWikiAPIError,
    MediaWikiInvalidResponseError,
    MediaWikiPageNotFoundError,
    MediaWikiRateLimitError,
    MediaWikiRequestError,
)
from .models import WikiArticle
from .rate_limiter import RateLimiter

if TYPE_CHECKING:
    from src.ingestion.cache import ArticleCache
    from src.logger import AppLogger


type JsonObject = dict[str, Any]


class MediaWikiClient:
    BASE_URL = "https://en.wikipedia.org/w/api.php"

    def __init__(
        self,
        *,
        user_agent: str,
        requests_per_second: float = 2.0,
        timeout: float = 10.0,
        max_retries: int = 3,
        maxlag: int = 5,
        batch_size: int = 20,
        client: httpx.Client | None = None,
        logger: AppLogger | None = None,
        cache: ArticleCache | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent cannot be empty")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if maxlag < 0:
            raise ValueError("maxlag cannot be negative")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        self._max_retries = max_retries
        self._maxlag = maxlag
        self._batch_size = batch_size

        self._rate_limiter = RateLimiter(requests_per_second)
        self._owns_client = client is None
        self._logger = logger.get_logger(__name__) if logger else logging.getLogger(__name__)
        self._cache = cache

        self._client = client or httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_article(
        self,
        title: str,
        *,
        as_of: datetime | None = None,
    ) -> WikiArticle:
        """Fetch a latest or historical Wikipedia article."""

        title = title.strip()

        if not title:
            raise ValueError("title cannot be empty")

        if as_of is not None:
            if as_of.tzinfo is None:
                raise ValueError("as_of must be timezone-aware")
            as_of = as_of.astimezone(UTC)

        # Only latest requests use the TTL cache.
        if as_of is None and self._cache:
            cached = self._cache.get(title)
            if cached is not None:
                self._logger.info("Cache hit: %s", title)
                return cached

        article = self._fetch_article(
            title,
            as_of=as_of,
        )

        if as_of is None and self._cache:
            self._cache.set(article)

        return article

    def get_articles(
        self,
        titles: Iterable[str],
    ) -> list[WikiArticle]:
        """Fetch the latest versions of multiple articles."""

        normalized = self._normalize_titles(titles)

        if not normalized:
            return []

        result = []
        pending = []

        for title in normalized:
            cached = self._cache.get(title) if self._cache else None

            if cached is not None:
                result.append(cached)
            else:
                pending.append(title)

        for batch in self._batched(pending, self._batch_size):
            fetched = self._fetch_batch(batch)

            for article in fetched:
                if self._cache:
                    self._cache.set(article)

            result.extend(fetched)

        return result

    def _fetch_article(
        self,
        title: str,
        *,
        as_of: datetime | None = None,
    ) -> WikiArticle:
        """Fetch the requested revision and current page metadata."""

        # First request: fetch ONLY the selected revision.
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "info|revisions",
            "rvprop": "ids|timestamp|size|content",
            "rvslots": "main",
            "rvlimit": "1",
        }

        if as_of is not None:
            params.update(
                {
                    "rvstart": as_of.isoformat().replace("+00:00", "Z"),
                    "rvdir": "older",
                }
            )

        data = self._request(params)
        page = self._extract_single_page(data, title)

        revision = self._extract_revision(page)
        raw_text = self._extract_text(revision)

        # Second phase: fetch categories and links separately.
        # This prevents revision pagination from leaking
        # into metadata continuation requests.
        categories, links = self._fetch_article_metadata(title)

        return self._build_article(
            page=page,
            revision=revision,
            raw_text=raw_text,
            categories=categories,
            links=links,
        )

    def _fetch_batch(
        self,
        titles: list[str],
    ) -> list[WikiArticle]:
        """Fetch latest revisions in batches."""

        if not titles:
            return []

        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(titles),
            "redirects": "1",
            "prop": "info|revisions",
            "rvprop": "ids|timestamp|size|content",
            "rvslots": "main",
        }

        data = self._request(params)
        pages = self._extract_pages(data)
        articles = []

        for page in pages:
            if page.get("missing") is True:
                continue

            title = page.get("title")

            if not isinstance(title, str):
                raise MediaWikiInvalidResponseError("Page title is missing")

            categories, links = self._fetch_article_metadata(title)

            revision = self._extract_revision(page)

            articles.append(
                self._build_article(
                    page=page,
                    revision=revision,
                    raw_text=self._extract_text(revision),
                    categories=categories,
                    links=links,
                )
            )

        return articles

    def _fetch_article_metadata(
        self,
        title: str,
    ) -> tuple[list[str], list[str]]:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "categories|links",
            "cllimit": "max",
            # Maintenance categories ("Articles with short description", ...)
            # are hidden on Wikipedia and are useless as search filters.
            "clshow": "!hidden",
            "pllimit": "max",
            "plnamespace": "0",
        }

        categories = []
        links = []

        while True:
            response = self._request(params)
            page = self._extract_single_page(response, title)

            categories.extend(self._extract_categories(page))
            links.extend(self._extract_links(page))

            continuation = response.get("continue")
            if not isinstance(continuation, dict):
                break

            params = {**params, **continuation}

        return (
            self._deduplicate(categories),
            self._deduplicate(links),
        )

    @staticmethod
    def _query_params(title: str) -> JsonObject:
        return {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "info|revisions|categories|links",
            "rvprop": "ids|timestamp|size|content",
            "rvslots": "main",
            "cllimit": "max",
            "clshow": "!hidden",
            "pllimit": "max",
            "plnamespace": "0",
        }

    def _request(self, params: JsonObject) -> JsonObject:
        request_params = {
            **params,
            "maxlag": self._maxlag,
        }

        for attempt in range(self._max_retries + 1):
            self._rate_limiter.wait()

            try:
                response = self._client.get(
                    self.BASE_URL,
                    params=request_params,
                )
            except httpx.RequestError as exc:
                if attempt == self._max_retries:
                    raise MediaWikiRequestError(f"Network request failed: {exc}") from exc

                self._backoff(attempt)
                continue

            if response.status_code in {429, 502, 503, 504}:
                if attempt == self._max_retries:
                    if response.status_code == 429:
                        raise MediaWikiRateLimitError("MediaWiki rate limit exceeded")
                    raise MediaWikiRequestError(f"HTTP {response.status_code}")

                self._wait_for_retry(response, attempt)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise MediaWikiRequestError(f"HTTP {response.status_code}") from exc

            try:
                data = response.json()
            except ValueError as exc:
                raise MediaWikiInvalidResponseError("Invalid JSON response") from exc

            if not isinstance(data, dict):
                raise MediaWikiInvalidResponseError("Expected JSON object")

            error = data.get("error")

            if isinstance(error, dict):
                code = str(error.get("code", "unknown"))
                info = str(error.get("info", "Unknown error"))

                if code == "maxlag":
                    if attempt == self._max_retries:
                        raise MediaWikiAPIError(f"maxlag: {info}")
                    self._wait_for_retry(response, attempt)
                    continue

                raise MediaWikiAPIError(f"{code}: {info}")

            return data

        raise MediaWikiRequestError("All retry attempts exhausted")

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(2**attempt + random.uniform(0, 0.5))

    @classmethod
    def _wait_for_retry(
        cls,
        response: httpx.Response,
        attempt: int,
    ) -> None:
        value = response.headers.get("Retry-After")

        if value:
            try:
                time.sleep(max(0, float(value)))
                return
            except ValueError:
                pass

            try:
                retry_at = parsedate_to_datetime(value)
                now = datetime.now(retry_at.tzinfo)
                time.sleep(
                    max(
                        0,
                        (retry_at - now).total_seconds(),
                    )
                )
                return
            except TypeError, ValueError:
                pass

        cls._backoff(attempt)

    @staticmethod
    def _extract_pages(
        data: JsonObject,
    ) -> list[JsonObject]:
        try:
            pages = data["query"]["pages"]
        except (KeyError, TypeError) as exc:
            raise MediaWikiInvalidResponseError("Missing query.pages") from exc

        if not isinstance(pages, list):
            raise MediaWikiInvalidResponseError("query.pages must be a list")

        if not all(isinstance(page, dict) for page in pages):
            raise MediaWikiInvalidResponseError("Invalid page structure")

        return pages

    @classmethod
    def _extract_single_page(
        cls,
        data: JsonObject,
        requested_title: str,
    ) -> JsonObject:
        pages = cls._extract_pages(data)

        if len(pages) != 1:
            raise MediaWikiInvalidResponseError(f"Expected one page for {requested_title}")

        page = pages[0]

        if page.get("missing") is True:
            raise MediaWikiPageNotFoundError(f"Article not found: {requested_title}")

        return page

    @staticmethod
    def _extract_revision(
        page: JsonObject,
    ) -> JsonObject:
        revisions = page.get("revisions")

        if not isinstance(revisions, list) or not revisions:
            raise MediaWikiInvalidResponseError("Article has no accessible revision")

        revision = revisions[0]

        if not isinstance(revision, dict):
            raise MediaWikiInvalidResponseError("Invalid revision object")

        return revision

    @staticmethod
    def _extract_text(
        revision: JsonObject,
    ) -> str:
        try:
            content = revision["slots"]["main"]["content"]
        except (KeyError, TypeError) as exc:
            raise MediaWikiInvalidResponseError("Revision content missing") from exc

        if not isinstance(content, str):
            raise MediaWikiInvalidResponseError("Revision content must be text")

        return content

    @staticmethod
    def _extract_categories(
        page: JsonObject,
    ) -> list[str]:
        values = page.get("categories", [])

        if not isinstance(values, list):
            raise MediaWikiInvalidResponseError("Invalid categories")

        result = []

        for category in values:
            if not isinstance(category, dict):
                raise MediaWikiInvalidResponseError("Invalid category entry")

            title = category.get("title")

            if not isinstance(title, str):
                raise MediaWikiInvalidResponseError("Category title missing")

            result.append(title.removeprefix("Category:"))

        return result

    @staticmethod
    def _extract_links(
        page: JsonObject,
    ) -> list[str]:
        values = page.get("links", [])

        if not isinstance(values, list):
            raise MediaWikiInvalidResponseError("Invalid links")

        result = []

        for link in values:
            if not isinstance(link, dict):
                raise MediaWikiInvalidResponseError("Invalid link entry")

            title = link.get("title")

            if not isinstance(title, str):
                raise MediaWikiInvalidResponseError("Link title missing")

            result.append(title)

        return result

    @staticmethod
    def _deduplicate(
        values: list[str],
    ) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _normalize_titles(
        titles: Iterable[str],
    ) -> list[str]:
        result = []

        for title in titles:
            if not isinstance(title, str):
                raise TypeError("Article titles must be strings")

            normalized = title.strip()

            if not normalized:
                raise ValueError("Article title cannot be empty")

            result.append(normalized)

        return list(dict.fromkeys(result))

    @staticmethod
    def _batched(
        values: list[str],
        batch_size: int,
    ) -> Iterable[list[str]]:
        for index in range(0, len(values), batch_size):
            yield values[index : index + batch_size]

    @staticmethod
    def _build_article(
        *,
        page: JsonObject,
        revision: JsonObject,
        raw_text: str,
        categories: list[str],
        links: list[str],
    ) -> WikiArticle:
        try:
            return WikiArticle(
                page_id=int(page["pageid"]),
                title=str(page["title"]),
                text=raw_text,
                # The size of the fetched revision, so a snapshot keeps the length it
                # had at the snapshot date; the page's current length is the fallback.
                length=int(revision.get("size", page["length"])),
                revision_id=int(revision["revid"]),
                last_modified=datetime.fromisoformat(
                    str(revision["timestamp"]).replace("Z", "+00:00")
                ),
                categories=tuple(categories),
                links=tuple(links),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaWikiInvalidResponseError("Incomplete article metadata") from exc
