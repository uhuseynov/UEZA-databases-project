"""Command-line interface for Wikipedia ingestion."""

import argparse
import asyncio
import logging

from src.config import settings
from src.containers import Container
from src.database.repositories.articles import ArticleRepository
from src.ingestion.consistency import check_database
from src.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


async def run(args: argparse.Namespace) -> None:
    container = Container()

    database = container.database()
    await database.connect()

    try:
        if args.action == "check":
            result = await check_database(
                database=database,
                csv_path=args.csv,
            )

            print("\nConsistency report:")

            for key, value in result.items():
                print(f"  {key}: {value}")

            if not result["ok"]:
                raise SystemExit(1)

            print("\nAll consistency checks passed.")
            return

        client = container.mediawiki_client()
        embedder = container.embedder()

        repository = ArticleRepository(
            database=database,
        )

        pipeline = IngestionPipeline(
            client=client,
            embedder=embedder,
            repository=repository,
        )

        try:
            articles, chunks = await pipeline.ingest_all(
                csv_path=args.csv,
                config=args.config,
                snapshot=not args.latest,
                limit=args.limit,
            )

            print(f"\nIngestion completed successfully.\nArticles: {articles}\nChunks: {chunks}")

        finally:
            client.close()

    finally:
        await database.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wikipedia article ingestion")

    parser.add_argument(
        "action",
        choices=["ingest", "check"],
        help="Operation to perform",
    )

    parser.add_argument(
        "--csv",
        default=settings.articles_csv_path,
        help="Article CSV path",
    )

    parser.add_argument(
        "--config",
        choices=["A", "B", "C"],
        default=settings.chunk_config,
        help="Chunking configuration",
    )

    parser.add_argument(
        "--latest",
        action="store_true",
        default=not settings.ingestion_snapshot,
        help="Fetch latest revisions instead of CSV snapshots",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles for testing",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
