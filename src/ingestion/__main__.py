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
        if args.action == "reindex":
            repository = ArticleRepository(database=database)
            seconds = await repository.rebuild_vector_index(args.m)
            _, m, distance = await repository.vector_index()
            print(f"\nVector index rebuilt in {seconds:.1f} s (M={m}, DISTANCE={distance}).")
            return

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


def _index_m(value: str) -> int:
    m = int(value)
    if not 3 <= m <= 200:
        raise argparse.ArgumentTypeError(f"M must be from 3 to 200, got {m}")
    return m


def main() -> None:
    parser = argparse.ArgumentParser(description="Wikipedia article ingestion")

    parser.add_argument(
        "action",
        choices=["ingest", "check", "reindex"],
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

    parser.add_argument(
        "--m",
        type=_index_m,
        default=None,
        help="reindex only: build the vector index with this M (3 to 200) instead of the current one",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s: %(message)s"),
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
