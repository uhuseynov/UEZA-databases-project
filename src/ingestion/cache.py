"""Disk cache for MediaWiki articles."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .mediawiki.models import WikiArticle


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
        """Generate a collision-resistant cache filename."""

        digest = hashlib.sha256(title.encode("utf-8")).hexdigest()

        return self.cache_path / f"{digest}.json"

    def get(
        self,
        title: str,
    ) -> WikiArticle | None:
        """Return cached article if still valid."""

        if not title.strip():
            raise ValueError("Article title cannot be empty")

        path = self._get_file_path(title)

        if not path.is_file():
            return None

        age = datetime.now(UTC).timestamp() - path.stat().st_mtime

        if age >= self.ttl_seconds:
            return None

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as handle:
                data = json.load(handle)

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
    ) -> None:
        """Atomically write an article to disk."""

        path = self._get_file_path(article.title)

        data = asdict(article)
        data["last_modified"] = article.last_modified.isoformat()

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
