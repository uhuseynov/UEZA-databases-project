"""Command line entry point.

    uv run python -m src.evaluation run --runs 5
    uv run python -m src.evaluation run --exact --label exact
    uv run python -m src.evaluation ef-sweep --ef 10 20 40 80 160
    uv run python -m src.evaluation explain


Results are written to EVAL_RESULTS_DIR as JSON (all data) and Markdown (tables).
"""

import argparse
import asyncio
import math
import os
import platform
import random
import subprocess
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config import Settings, settings
from src.containers import Container
from src.database import Database
from src.evaluation.ground_truth import load_ground_truth
from src.evaluation.report import write_report
from src.evaluation.runner import EvalConfig, ef_search_sweep, evaluate
from src.rag.models import SearchFilters
from src.rag.retriever import VectorRetriever

EXPLAIN_COLUMNS = ("id", "select_type", "table", "type", "key", "rows", "Extra")


async def collect_environment(database: Database, config: Settings) -> dict[str, Any]:
    environment: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "embedding_model": config.embedding_model_name,
        "embedding_dimension": config.embedding_dimension,
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        environment["git_commit"] = commit
    except (OSError, subprocess.SubprocessError):
        pass

    async with database.get_session() as session:
        environment["mariadb_version"] = (
            await session.execute(text("SELECT VERSION()"))
        ).scalar_one()
        environment["mhnsw_ef_search_default"] = (
            await session.execute(text("SELECT @@global.mhnsw_ef_search"))
        ).scalar_one()
        environment["articles"] = (
            await session.execute(text("SELECT COUNT(*) FROM articles"))
        ).scalar_one()
        environment["chunks"] = (
            await session.execute(text("SELECT COUNT(*) FROM article_chunks"))
        ).scalar_one()
    return environment


async def explain_plans(retriever: VectorRetriever, dimension: int) -> str:
    """EXPLAIN for the search with and without a filter, index vs exact search.

    Uses a random unit vector, so it needs neither the embedding model nor the ground truth.
    """
    rng = random.Random(0)
    vector = [rng.gauss(0, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(x * x for x in vector))
    vector = [x / norm for x in vector]

    cases = [
        ("no filter", SearchFilters()),
        ("article_length >= 50000", SearchFilters(min_length=50_000)),
        ("category filter", SearchFilters(category="Machine learning")),
    ]
    parts = ["# Query plans", ""]
    for name, filters in cases:
        for exact in (False, True):
            rows = await retriever.explain(vector, k=10, filters=filters, exact=exact)
            mode = "exact (ORDER BY distance + 0)" if exact else "index (ORDER BY distance)"
            parts += [f"## {name}, {mode}", "", "| " + " | ".join(EXPLAIN_COLUMNS) + " |",
                      "|" + "---|" * len(EXPLAIN_COLUMNS)]
            parts += ["| " + " | ".join(str(row.get(col, "")) for col in EXPLAIN_COLUMNS) + " |"
                      for row in rows]
            parts.append("")
    return "\n".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.evaluation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth", default=settings.ground_truth_path)
    parser.add_argument("--results-dir", default=settings.eval_results_dir)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Recall@K, MRR, latency and not-found analysis")
    run.add_argument("--label", default=None)
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--warmup", type=int, default=1)
    run.add_argument("--ef-search", type=int, default=None)
    run.add_argument("--exact", action="store_true", help="full scan instead of the HNSW index")

    sweep = commands.add_parser("ef-sweep", help="index recall and latency per mhnsw_ef_search")
    sweep.add_argument("--ef", type=int, nargs="+", default=[10, 20, 40, 80, 160])
    sweep.add_argument("--runs", type=int, default=3)
    sweep.add_argument("--warmup", type=int, default=1)
    sweep.add_argument("--k", type=int, default=10)

    commands.add_parser("explain", help="query plans: is the vector index used?")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    questions = []
    if args.command != "explain":
        try:
            questions = load_ground_truth(args.ground_truth)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Cannot load the ground truth: {exc}", file=sys.stderr)
            return 2

    container = Container()
    container.app_logger().setup()
    database = container.database()
    await database.connect()
    try:
        try:
            environment = await collect_environment(database, settings)
        except SQLAlchemyError as exc:
            print(
                "Cannot query MariaDB. Is the database running (make db-up) and is the data "
                f"loaded (make ingest)?\n{type(exc).__name__}: {exc.orig if hasattr(exc, 'orig') else exc}",
                file=sys.stderr,
            )
            return 3
        retriever = container.retriever()
        if args.command == "explain":
            print(await explain_plans(retriever, settings.embedding_dimension))
            return 0
        embedder = await asyncio.to_thread(container.embedder)

        if args.command == "run":
            label = args.label or (
                "exact" if args.exact else f"ef-{args.ef_search}" if args.ef_search else "default"
            )
            config = EvalConfig(
                label=label,
                runs=args.runs,
                warmup_runs=args.warmup,
                ef_search=args.ef_search,
                exact=args.exact,
                not_found_threshold=settings.rag_max_distance,
            )
            report = await evaluate(questions, embedder, retriever, config, environment)
        else:
            report = await ef_search_sweep(
                questions, embedder, retriever, args.ef,
                runs=args.runs, warmup_runs=args.warmup, k=args.k, environment=environment,
            )
            report["label"] = "ef-sweep"
    finally:
        await database.disconnect()

    json_path, md_path = write_report(report, args.results_dir)
    print(md_path.read_text(encoding="utf-8"))
    print(f"Saved {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
