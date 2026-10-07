import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .mediawiki import WikiArticle


class ArticleCache:
    """Stores fetched WikiArticles on disk to prevent redundant API calls."""

    def __init__(self, cache_dir: str = ".cache/articles", ttl_seconds: int = 86400) -> None:
        self.cache_path = Path(cache_dir)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def _get_file_path(self, title: str) -> Path:
        safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title.lower())
        return self.cache_path / f"{safe_title}.json"

    def get(self, title: str) -> WikiArticle | None:
        file_path = self._get_file_path(title)
        if not file_path.exists():
            return None

        # TTL kontrolü
        age = datetime.now(UTC).timestamp() - file_path.stat().st_mtime
        if age > self.ttl_seconds:
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            return WikiArticle(
                page_id=data["page_id"],
                title=data["title"],
                text=data["text"],
                length=data["length"],
                revision_id=data["revision_id"],
                last_modified=datetime.fromisoformat(data["last_modified"]),
                categories=tuple(data["categories"]),
                links=tuple(data["links"]),
            )
        except OSError, KeyError, TypeError, ValueError:
            return None

    def set(self, article: WikiArticle) -> None:
        file_path = self._get_file_path(article.title)
        data = asdict(article)
        data["last_modified"] = article.last_modified.isoformat()

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
