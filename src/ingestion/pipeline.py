"""Wikipedia article ingestion pipeline."""

import asyncio
import csv
import logging
from datetime import datetime
from pathlib import Path

from src.ingestion.chunker import chunk_article
from src.ingestion.cleaner import clean_wikitext

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "title",
    "pageid",
    "last_edit",
    "root_category",
}


def read_articles(
    csv_path: str = "data/articles.csv",
) -> list[dict[str, str]]:
    """Read and validate the article dataset."""

    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(f"Article dataset not found: {path}")

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise ValueError("CSV has no header")

        if not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            missing = REQUIRED_COLUMNS - set(reader.fieldnames)
            raise ValueError(f"Missing CSV columns: {sorted(missing)}")

        rows = list(reader)

    if not rows:
        raise ValueError("Article dataset is empty")

    titles = set()
    page_ids = set()

    for index, row in enumerate(rows, start=2):
        for column in REQUIRED_COLUMNS:
            if not row.get(column):
                raise ValueError(f"Row {index}: missing {column}")

        title = row["title"]
        page_id = int(row["pageid"])

        if page_id <= 0:
            raise ValueError(f"Row {index}: invalid page ID")

        datetime.fromisoformat(row["last_edit"].replace("Z", "+00:00"))

        if title in titles:
            raise ValueError(f"Duplicate article title: {title}")

        if page_id in page_ids:
            raise ValueError(f"Duplicate page ID: {page_id}")

        titles.add(title)
        page_ids.add(page_id)

    return rows


class IngestionPipeline:
    """Coordinate Wikipedia fetching, processing and storage."""

    def __init__(
        self,
        client,
        embedder,
        repository,
    ):
        self.client = client
        self.embedder = embedder
        self.repository = repository

        self.tokenizer = embedder.model.tokenizer

    async def ingest_one(
        self,
        row: dict[str, str],
        config: str = "A",
        snapshot: bool = True,
    ) -> int:
        """Ingest one article and return its chunk count."""

        title = row["title"]

        as_of = None

        if snapshot:
            as_of = datetime.fromisoformat(row["last_edit"].replace("Z", "+00:00"))

        logger.info(
            "Fetching article: %s",
            title,
        )

        # MediaWiki client is synchronous.
        wiki = await asyncio.to_thread(
            self.client.get_article,
            title,
            as_of=as_of,
        )

        if wiki.page_id != int(row["pageid"]):
            raise ValueError(f"Page ID mismatch for {title}")

        # Clean Wikipedia markup.
        cleaned = clean_wikitext(wiki.text)

        if not cleaned:
            raise ValueError(f"Article has no clean content: {title}")

        # Split into token-based chunks.
        chunks = chunk_article(
            title=title,
            text=cleaned,
            tokenizer=self.tokenizer,
            config=config,
        )

        if not chunks:
            raise ValueError(f"No chunks generated: {title}")

        logger.info(
            "%s: generated %d chunks",
            title,
            len(chunks),
        )

        # Run the embedding model outside DB transaction.
        vectors = await asyncio.to_thread(
            self.embedder.embed,
            chunks,
            "passage",
        )

        if len(vectors) != len(chunks):
            raise ValueError(f"Embedding count mismatch: {title}")

        # Repository owns the atomic database replacement.
        await self.repository.replace_article(
            wiki=wiki,
            csv_row=row,
            chunks=chunks,
            vectors=vectors,
        )

        return len(chunks)

    async def ingest_all(
        self,
        csv_path: str = "data/articles.csv",
        config: str = "A",
        snapshot: bool = True,
        limit: int | None = None,
    ) -> tuple[int, int]:
        """Ingest articles and report any failures."""

        rows = read_articles(csv_path)

        if limit is not None:
            if limit < 1:
                raise ValueError("Limit must be positive")

            rows = rows[:limit]

        total_articles = len(rows)
        total_chunks = 0
        successful = 0
        failures = []

        logger.info(
            "Starting ingestion of %d articles",
            total_articles,
        )

        for index, row in enumerate(rows, start=1):
            title = row["title"]

            try:
                chunks = await self.ingest_one(
                    row=row,
                    config=config,
                    snapshot=snapshot,
                )

                successful += 1
                total_chunks += chunks

                logger.info(
                    "[%d/%d] %s: %d chunks",
                    index,
                    total_articles,
                    title,
                    chunks,
                )

            except Exception as exc:
                logger.exception(
                    "[%d/%d] Failed: %s",
                    index,
                    total_articles,
                    title,
                )

                failures.append((title, str(exc)))

        # Refresh the optimizer statistics even if some articles failed. With stale
        # statistics MariaDB can skip the vector index and scan every chunk
        # (docs/database/Vector-Search.md).
        if successful:
            await self.repository.analyze()

        if failures:
            details = "\n".join(f"- {title}: {error}" for title, error in failures)

            raise RuntimeError(f"Ingestion incomplete: {len(failures)} failures\n{details}")

        logger.info(
            "Ingestion complete: %d articles, %d chunks",
            successful,
            total_chunks,
        )

        return successful, total_chunks
