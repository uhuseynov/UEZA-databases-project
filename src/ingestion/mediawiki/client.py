from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterable
from datetime import datetime
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
    from ingestion.cache import ArticleCache
    from logger import AppLogger

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
            raise ValueError("batch_size must be greater than 0")

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

    def get_article(self, title: str) -> WikiArticle:
        title = title.strip()

        if not title:
            raise ValueError("title cannot be empty")

        if self._cache:
            cached = self._cache.get(title)
            if cached is not None:
                self._logger.info(
                    "Cache hit for article: '%s' (Page ID: %d)", title, cached.page_id
                )
                return cached

        self._logger.info("Cache miss. Fetching article from MediaWiki API: '%s'", title)
        article = self._fetch_article(title)

        if self._cache:
            self._cache.set(article)
            self._logger.debug("Article cached: '%s'", article.title)

        return article

    def get_articles(
        self,
        titles: Iterable[str],
    ) -> list[WikiArticle]:
        normalized = self._normalize_titles(titles)
        if not normalized:
            return []

        articles: list[WikiArticle] = []
        titles_to_fetch: list[str] = []

        if self._cache:
            for title in normalized:
                cached = self._cache.get(title)
                if cached is not None:
                    self._logger.info(
                        "Cache hit for article: '%s' (Page ID: %d)", title, cached.page_id
                    )
                    articles.append(cached)
                else:
                    titles_to_fetch.append(title)
        else:
            titles_to_fetch = normalized

        if titles_to_fetch:
            self._logger.info("Fetching %d articles in batches from API...", len(titles_to_fetch))
            for batch in self._batched(titles_to_fetch, self._batch_size):
                fetched = self._fetch_batch(batch)
                for article in fetched:
                    if self._cache:
                        self._cache.set(article)
                    articles.append(article)

        return articles

    def _fetch_article(self, title: str) -> WikiArticle:
        params = self._query_params(title)

        first_response = self._request(params)
        page = self._extract_single_page(first_response, title)

        return self._build_article_with_continuation(
            page=page,
            first_response=first_response,
            params=params,
            requested_title=title,
        )

    def _fetch_batch(
        self,
        titles: list[str],
    ) -> list[WikiArticle]:
        if not titles:
            return []

        #
        # Important:
        #
        # Fetch the basic article data in a single request, then finish each
        # article independently. This keeps continuation handling simple and
        # predictable.
        #

        params: dict[str, Any] = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(titles),
            "redirects": "1",
            "prop": "info|revisions",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
        }

        data = self._request(params)
        pages = self._extract_pages(data)

        articles: list[WikiArticle] = []

        for page in pages:
            if page.get("missing") is True:
                continue

            title = page.get("title")

            if not isinstance(title, str):
                raise MediaWikiInvalidResponseError("MediaWiki page is missing a valid title")

            #
            # Categories and links can independently require continuation.
            # Fetching them per canonical article keeps the implementation
            # understandable.
            #

            metadata = self._fetch_article_metadata(title)

            revision = self._extract_revision(page)
            text = self._extract_text(revision)

            articles.append(
                self._build_article(
                    page=page,
                    revision=revision,
                    text=text,
                    categories=metadata[0],
                    links=metadata[1],
                )
            )

        return articles

    def _fetch_article_metadata(
        self,
        title: str,
    ) -> tuple[list[str], list[str]]:
        params: dict[str, Any] = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "categories|links",
            "cllimit": "max",
            "pllimit": "max",
            "plnamespace": "0",
        }

        categories: list[str] = []
        links: list[str] = []

        while True:
            data = self._request(params)
            page = self._extract_single_page(data, title)

            categories.extend(self._extract_categories(page))
            links.extend(self._extract_links(page))

            continuation = data.get("continue")

            if not isinstance(continuation, dict):
                break

            params = params | continuation

        return (
            self._deduplicate(categories),
            self._deduplicate(links),
        )

    def _build_article_with_continuation(
        self,
        *,
        page: JsonObject,
        first_response: JsonObject,
        params: dict[str, Any],
        requested_title: str,
    ) -> WikiArticle:
        categories = self._extract_categories(page)
        links = self._extract_links(page)

        continuation = first_response.get("continue")

        while isinstance(continuation, dict):
            continued_params = params | continuation

            # Content is already available from the first request.
            continued_params["rvprop"] = "ids|timestamp"

            response = self._request(continued_params)

            continued_page = self._extract_single_page(
                response,
                requested_title,
            )

            categories.extend(self._extract_categories(continued_page))

            links.extend(self._extract_links(continued_page))

            continuation = response.get("continue")

        revision = self._extract_revision(page)
        text = self._extract_text(revision)

        return self._build_article(
            page=page,
            revision=revision,
            text=text,
            categories=self._deduplicate(categories),
            links=self._deduplicate(links),
        )

    def _build_article(
        self,
        *,
        page: JsonObject,
        revision: JsonObject,
        text: str,
        categories: list[str],
        links: list[str],
    ) -> WikiArticle:
        try:
            return WikiArticle(
                page_id=int(page["pageid"]),
                title=str(page["title"]),
                text=text,
                length=int(page["length"]),
                revision_id=int(revision["revid"]),
                last_modified=datetime.fromisoformat(str(revision["timestamp"])),
                categories=tuple(categories),
                links=tuple(links),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaWikiInvalidResponseError(
                "MediaWiki response is missing required article fields"
            ) from exc

    @staticmethod
    def _query_params(title: str) -> dict[str, Any]:
        return {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": title,
            "redirects": "1",
            "prop": "info|revisions|categories|links",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "cllimit": "max",
            "pllimit": "max",
            "plnamespace": "0",
        }

    def _request(
        self,
        params: dict[str, Any],
    ) -> JsonObject:
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
                    self._logger.error("MediaWiki request failed permanently: %s", exc)
                    raise MediaWikiRequestError(f"MediaWiki request failed: {exc}") from exc

                self._logger.warning(
                    "Network error on attempt %d: %s. Retrying...", attempt + 1, exc
                )
                self._backoff(attempt)
                continue

            if response.status_code == 429:
                if attempt == self._max_retries:
                    self._logger.error("MediaWiki 429 rate limit exhausted.")
                    raise MediaWikiRateLimitError("MediaWiki rate limit exceeded")

                self._logger.warning(
                    "Received HTTP 429 on attempt %d. Waiting for retry...", attempt + 1
                )
                self._wait_for_retry(response, attempt)
                continue

            if response.status_code in {502, 503, 504}:
                if attempt == self._max_retries:
                    self._logger.error("MediaWiki HTTP %d retries exhausted.", response.status_code)
                    raise MediaWikiRequestError(f"MediaWiki returned HTTP {response.status_code}")

                self._logger.warning(
                    "Received HTTP %d on attempt %d. Waiting for retry...",
                    response.status_code,
                    attempt + 1,
                )
                self._wait_for_retry(response, attempt)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._logger.error("MediaWiki non-retryable HTTP error: %s", exc)
                raise MediaWikiRequestError(
                    f"MediaWiki returned HTTP {response.status_code}"
                ) from exc

            try:
                data = response.json()
            except ValueError as exc:
                raise MediaWikiInvalidResponseError("MediaWiki returned invalid JSON") from exc

            if not isinstance(data, dict):
                raise MediaWikiInvalidResponseError("MediaWiki response is not a JSON object")

            error = data.get("error")

            if isinstance(error, dict):
                code = str(error.get("code", "unknown"))
                info = str(
                    error.get(
                        "info",
                        "Unknown MediaWiki API error",
                    )
                )

                if code == "maxlag":
                    if attempt == self._max_retries:
                        self._logger.error("MediaWiki maxlag persisted: %s", info)
                        raise MediaWikiAPIError(f"MediaWiki maxlag persisted: {info}")

                    self._logger.warning(
                        "MediaWiki maxlag hit on attempt %d: %s. Retrying...", attempt + 1, info
                    )
                    self._wait_for_retry(response, attempt)
                    continue

                self._logger.error("MediaWiki API error [%s]: %s", code, info)
                raise MediaWikiAPIError(f"MediaWiki API error [{code}]: {info}")

            return data

        raise MediaWikiRequestError("MediaWiki request failed after retries")

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = (2**attempt) + random.uniform(0.0, 0.5)
        time.sleep(delay)

    @classmethod
    def _wait_for_retry(
        cls,
        response: httpx.Response,
        attempt: int,
    ) -> None:
        retry_after = response.headers.get("Retry-After")

        if retry_after is not None:
            delay = cls._parse_retry_after(retry_after)

            if delay is not None:
                time.sleep(delay)
                return

        cls._backoff(attempt)

    @staticmethod
    def _parse_retry_after(
        value: str,
    ) -> float | None:
        try:
            return max(0.0, float(value))
        except ValueError:
            pass

        try:
            retry_at = parsedate_to_datetime(value)
            now = datetime.now(retry_at.tzinfo)

            return max(
                0.0,
                (retry_at - now).total_seconds(),
            )
        except TypeError, ValueError:
            return None

    @staticmethod
    def _extract_pages(
        data: JsonObject,
    ) -> list[JsonObject]:
        try:
            pages = data["query"]["pages"]
        except (KeyError, TypeError) as exc:
            raise MediaWikiInvalidResponseError(
                "MediaWiki response does not contain query.pages"
            ) from exc

        if not isinstance(pages, list):
            raise MediaWikiInvalidResponseError("MediaWiki query.pages is not a list")

        for page in pages:
            if not isinstance(page, dict):
                raise MediaWikiInvalidResponseError("MediaWiki returned an invalid page object")

        return pages

    @classmethod
    def _extract_single_page(
        cls,
        data: JsonObject,
        requested_title: str,
    ) -> JsonObject:
        pages = cls._extract_pages(data)

        if not pages:
            raise MediaWikiInvalidResponseError("MediaWiki response contains no pages")

        page = pages[0]

        if page.get("missing") is True:
            raise MediaWikiPageNotFoundError(f"Wikipedia page not found: {requested_title}")

        return page

    @staticmethod
    def _extract_revision(
        page: JsonObject,
    ) -> JsonObject:
        revisions = page.get("revisions")

        if not isinstance(revisions, list) or not revisions:
            raise MediaWikiInvalidResponseError("Article has no revision data")

        revision = revisions[0]

        if not isinstance(revision, dict):
            raise MediaWikiInvalidResponseError("Invalid revision data")

        return revision

    @staticmethod
    def _extract_text(
        revision: JsonObject,
    ) -> str:
        try:
            text = revision["slots"]["main"]["content"]
        except (KeyError, TypeError) as exc:
            raise MediaWikiInvalidResponseError(
                "Revision does not contain main slot content"
            ) from exc

        if not isinstance(text, str):
            raise MediaWikiInvalidResponseError("Article content is not a string")

        return text

    @staticmethod
    def _extract_categories(
        page: JsonObject,
    ) -> list[str]:
        categories = page.get("categories", [])

        if not isinstance(categories, list):
            raise MediaWikiInvalidResponseError("Invalid categories response")

        return [
            title.removeprefix("Category:")
            for category in categories
            if isinstance(category, dict)
            and isinstance(
                title := category.get("title"),
                str,
            )
        ]

    @staticmethod
    def _extract_links(
        page: JsonObject,
    ) -> list[str]:
        links = page.get("links", [])

        if not isinstance(links, list):
            raise MediaWikiInvalidResponseError("Invalid links response")

        return [
            title
            for link in links
            if isinstance(link, dict)
            and isinstance(
                title := link.get("title"),
                str,
            )
        ]

    @staticmethod
    def _deduplicate(
        values: Iterable[str],
    ) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _normalize_titles(
        titles: Iterable[str],
    ) -> list[str]:
        normalized = [title.strip() for title in titles if title.strip()]

        return list(dict.fromkeys(normalized))

    @staticmethod
    def _batched(
        values: list[str],
        size: int,
    ) -> Iterable[list[str]]:
        for start in range(0, len(values), size):
            yield values[start : start + size]
