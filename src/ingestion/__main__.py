"""Command-line interface for Wikipedia ingestion."""

import argparse
import asyncio
import logging

from src.config import settings
from src.containers import Container
from src.database.repositories.articles import ArticleRepository
from src.ingestion.consistency import check_database
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.sync import DEFAULT_REBUILD_SHARE, sync_articles, write_sync_report

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

        if args.action == "sync":
            client = container.mediawiki_client()
            repository = ArticleRepository(database=database)

            def pipeline_factory() -> IngestionPipeline:
                return IngestionPipeline(
                    client=client, embedder=container.embedder(), repository=repository
                )

            try:
                result = await sync_articles(
                    client=client,
                    repository=repository,
                    pipeline_factory=pipeline_factory,
                    csv_path=args.csv,
                    config=args.config,
                    dry_run=args.dry_run,
                    limit=args.limit,
                    rebuild_share=args.rebuild_share,
                )
            finally:
                client.close()

            json_path, md_path = write_sync_report(result, settings.eval_results_dir)
            print("\n" + md_path.read_text(encoding="utf-8"))
            print(f"Saved {json_path} and {md_path}")
            if result.failures:
                raise SystemExit(1)
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
        choices=["ingest", "check", "reindex", "sync"],
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
        "--dry-run",
        action="store_true",
        help="sync only: report the changed articles without replacing them",
    )

    parser.add_argument(
        "--rebuild-share",
        type=float,
        default=DEFAULT_REBUILD_SHARE,
        help="sync only: rebuild the vector index when at least this share of the chunks "
        f"was replaced (default {DEFAULT_REBUILD_SHARE})",
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
