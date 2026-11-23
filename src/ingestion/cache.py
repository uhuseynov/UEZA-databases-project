"""Disk cache for MediaWiki articles."""

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .mediawiki.models import WikiArticle


def normalize_title(title: str) -> str:
    """The form of a title under which the cache stores and finds it.

    Merges only spellings that MediaWiki itself treats as the same page title on English
    Wikipedia, and nothing else:

    - Unicode is normalized to NFC (MediaWiki does the same);
    - underscores are spaces, and runs of spaces and underscores are one space;
    - leading and trailing spaces are dropped;
    - the first letter is capitalized (``$wgCapitalLinks`` is on there), unless capitalizing
      it would change its length.

    The rest of the title keeps its case: ``IPhone`` and ``Iphone`` are different pages.
    Percent-encoding is a matter of the URL and is already decoded when a title arrives here;
    a literal ``%20`` in a title stays literal. Redirects cannot be resolved by spelling: see
    ``ArticleCache.set``.
    """

    title = unicodedata.normalize("NFC", title)
    title = re.sub(r"[ _]+", " ", title).strip(" ")

    if title:
        first = title[0].upper()
        if len(first) == 1:
            title = first + title[1:]

    return title


class ArticleCache:
    """Cache latest Wikipedia articles on disk."""

    def __init__(
        self,
        cache_dir: str = ".cache/articles",
        ttl_seconds: int = 86400,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds cannot be negative")

        self.cache_path = Path(cache_dir)
        self.cache_path.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.ttl_seconds = ttl_seconds

    def _get_file_path(
        self,
        title: str,
    ) -> Path:
        """Generate a collision-resistant cache filename for the normalized title."""

        return self._path_for(normalize_title(title))

    def _path_for(self, exact_title: str) -> Path:
        digest = hashlib.sha256(exact_title.encode("utf-8")).hexdigest()

        return self.cache_path / f"{digest}.json"

    def _is_fresh(self, path: Path) -> bool:
        try:
            age = datetime.now(UTC).timestamp() - path.stat().st_mtime
        except OSError:
            return False

        return age < self.ttl_seconds

    def get(
        self,
        title: str,
    ) -> WikiArticle | None:
        """Return cached article if still valid.

        The title is looked up in its normalized form. Entries written before the
        normalization existed were stored under the title MediaWiki returned, which is
        normalized already, so they are found as before; the title exactly as given is tried
        last, for entries under any other spelling. A redirect alias that was fetched before
        points at its target (see ``set``); an alias nobody has fetched is a miss.
        """

        stripped = title.strip()

        if not stripped:
            raise ValueError("Article title cannot be empty")

        article = self._load(self._get_file_path(stripped), follow_alias=True)

        if article is None:
            legacy_path = self._path_for(stripped)
            if legacy_path != self._get_file_path(stripped):
                article = self._load(legacy_path, follow_alias=False)

        return article

    def _load(self, path: Path, *, follow_alias: bool) -> WikiArticle | None:
        if not path.is_file() or not self._is_fresh(path):
            return None

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as handle:
                data = json.load(handle)

            if "alias_of" in data:
                if not follow_alias:
                    return None

                return self._load(self._get_file_path(str(data["alias_of"])), follow_alias=False)

            article = WikiArticle(
                page_id=int(data["page_id"]),
                title=str(data["title"]),
                text=str(data["text"]),
                length=int(data["length"]),
                revision_id=int(data["revision_id"]),
                last_modified=datetime.fromisoformat(data["last_modified"]),
                categories=tuple(data["categories"]),
                links=tuple(data["links"]),
            )

            if article.page_id <= 0:
                return None

            return article

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ):
            return None

    def set(
        self,
        article: WikiArticle,
        requested_title: str | None = None,
    ) -> None:
        """Atomically write an article to disk, under its normalized canonical title.

        ``requested_title`` is the title the caller asked for. When MediaWiki answered with
        another page (a redirect: "ML" for "Machine learning"), a small alias entry
        remembers that, so the next request for the alias is served from the cache. That is
        all that can be known locally: an alias that was never fetched has to be resolved by
        MediaWiki. The alias entry expires like any other, so a changed redirect is noticed.
        """

        self._write(self._get_file_path(article.title), self._serialize(article))

        if requested_title is not None:
            alias_path = self._get_file_path(requested_title)

            if requested_title.strip() and alias_path != self._get_file_path(article.title):
                self._write(alias_path, {"alias_of": article.title})

    @staticmethod
    def _serialize(article: WikiArticle) -> dict:
        data = asdict(article)
        data["last_modified"] = article.last_modified.isoformat()

        return data

    def _write(self, path: Path, data: dict) -> None:
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path,
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)

                json.dump(
                    data,
                    handle,
                    ensure_ascii=False,
                )

            os.replace(
                temporary_path,
                path,
            )

        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
