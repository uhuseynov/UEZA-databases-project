"""Command line entry point.

    uv run python -m src.evaluation run --runs 5
    uv run python -m src.evaluation run --exact --label exact
    uv run python -m src.evaluation run --shape nearest_first --vector-format binary
    uv run python -m src.evaluation ef-sweep --ef 10 20 40 80 160
    uv run python -m src.evaluation m-sweep --m 6 8 16 32 48 64 --ef 20 40 80
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
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config import Settings, settings
from src.containers import Container
from src.database import Database
from src.database.repositories.articles import ArticleRepository, vector_index_definition
from src.evaluation.ground_truth import load_ground_truth
from src.evaluation.report import write_report
from src.evaluation.runner import EvalConfig, ef_search_sweep, evaluate, m_sweep
from src.rag.models import SearchFilters
from src.rag.retriever import (
    DEFAULT_SHAPE,
    DEFAULT_VECTOR_FORMAT,
    SHAPES,
    VECTOR_FORMATS,
    VectorRetriever,
)

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
        environment["mhnsw_max_cache_size"] = (
            await session.execute(text("SELECT @@global.mhnsw_max_cache_size"))
        ).scalar_one()
        create_table = (await session.execute(text("SHOW CREATE TABLE article_chunks"))).one()[1]
    try:
        _, m, distance = vector_index_definition(create_table)
        environment["vector_index_m"] = m
        environment["vector_index_distance"] = distance
    except ValueError:
        environment["vector_index_m"] = None
    return environment


# A title that is in the data set (data/articles.csv) and links to many other articles.
LINKED_FROM_EXAMPLE = "Artificial intelligence"


def _random_unit_vector(dimension: int) -> list[float]:
    rng = random.Random(0)
    vector = [rng.gauss(0, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def _plan_nodes(plan: Any, key: str) -> list[dict[str, Any]]:
    """Every object stored under ``key`` anywhere in an ANALYZE FORMAT=JSON tree."""
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for name, item in value.items():
                if name == key and isinstance(item, dict):
                    found.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(plan)
    return found


def summarize_analyze(plan: dict[str, Any]) -> list[str]:
    """Markdown lines: total time, then rows and time per table, then the sorts."""
    total = plan.get("query_block", {}).get("r_total_time_ms")
    lines = [f"Total {total:.2f} ms in the server." if isinstance(total, int | float)
             else "Total time not reported.", ""]
    columns = ("table_name", "access_type", "key", "rows", "r_loops", "r_rows",
               "r_table_time_ms", "r_other_time_ms", "r_filtered")
    lines += ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for table in _plan_nodes(plan, "table"):
        if "table_name" in table:
            lines.append("| " + " | ".join(str(table.get(c, "")) for c in columns) + " |")
    sorts = _plan_nodes(plan, "filesort")
    for sort in sorts:
        lines.append(
            f"\nfilesort: {sort.get('r_total_time_ms', '?')} ms, "
            f"{sort.get('r_output_rows', '?')} rows out, "
            f"priority queue {sort.get('r_used_priority_queue', '?')}"
        )
    return lines


async def explain_plans(retriever: VectorRetriever, dimension: int) -> str:
    """EXPLAIN for the search with and without a filter, index vs exact search, and
    ANALYZE (the statement run, with rows and times measured) for the slow cases.

    Uses a random unit vector, so it needs neither the embedding model nor the ground truth.
    """
    vector = _random_unit_vector(dimension)
    linked = SearchFilters(linked_from=LINKED_FROM_EXAMPLE)

    cases = [
        ("no filter", SearchFilters(), "join"),
        ("no filter, nearest chunks first", SearchFilters(), "nearest_first"),
        ("article_length >= 50000", SearchFilters(min_length=50_000), "join"),
        ("category filter", SearchFilters(category="Machine learning"), "join"),
        (f"linked from {LINKED_FROM_EXAMPLE}", linked, "join"),
    ]
    parts = ["# Query plans", "", f"Created {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}.", ""]
    for name, filters, shape in cases:
        for exact in (False, True):
            rows = await retriever.explain(vector, k=10, filters=filters, exact=exact, shape=shape)
            mode = "exact (ORDER BY distance + 0)" if exact else "index (ORDER BY distance)"
            parts += [f"## {name}, {mode}", "", "| " + " | ".join(EXPLAIN_COLUMNS) + " |",
                      "|" + "---|" * len(EXPLAIN_COLUMNS)]
            parts += ["| " + " | ".join(str(row.get(col, "")) for col in EXPLAIN_COLUMNS) + " |"
                      for row in rows]
            parts.append("")

    analyzed = [
        ("no filter, index", SearchFilters(), False, "join"),
        ("no filter, nearest chunks first, index", SearchFilters(), False, "nearest_first"),
        ("no filter, exact", SearchFilters(), True, "join"),
        (f"linked from {LINKED_FROM_EXAMPLE}", linked, False, "join"),
        ("category filter", SearchFilters(category="Machine learning"), False, "join"),
    ]
    parts += ["# ANALYZE: the statements run, with measured rows and times", "",
              "The same random vector; each statement once with the query vector as text "
              "(`VEC_FromText`) and once as its binary value.", ""]
    for name, filters, exact, shape in analyzed:
        for vector_format in VECTOR_FORMATS:
            plan = await retriever.analyze(vector, k=10, filters=filters, exact=exact,
                                           shape=shape, vector_format=vector_format)
            parts += [f"## {name}, vector as {vector_format}", "", *summarize_analyze(plan), ""]
    return "\n".join(parts)


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _index_m(value: str) -> int:
    m = int(value)
    if not 3 <= m <= 200:
        raise argparse.ArgumentTypeError(f"M must be from 3 to 200, got {m}")
    return m


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.evaluation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth", default=settings.ground_truth_path)
    parser.add_argument("--results-dir", default=settings.eval_results_dir)
    commands = parser.add_subparsers(dest="command", required=True)

    def statement_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--shape", choices=SHAPES, default=DEFAULT_SHAPE,
                             help="statement for searches without a filter")
        command.add_argument("--vector-format", choices=VECTOR_FORMATS,
                             default=DEFAULT_VECTOR_FORMAT,
                             help="send the query vector as text or as its binary value")

    run = commands.add_parser("run", help="Recall@K, MRR, latency and not-found analysis")
    run.add_argument("--label", default=None)
    run.add_argument("--runs", type=_positive, default=5)
    run.add_argument("--warmup", type=int, default=1)
    run.add_argument("--ef-search", type=int, default=None)
    run.add_argument("--exact", action="store_true", help="full scan instead of the HNSW index")
    statement_options(run)

    sweep = commands.add_parser("ef-sweep", help="index recall and latency per mhnsw_ef_search")
    sweep.add_argument("--label", default="ef-sweep")
    sweep.add_argument("--ef", type=_positive, nargs="+", default=[10, 20, 40, 80, 160])
    sweep.add_argument("--runs", type=_positive, default=3)
    sweep.add_argument("--warmup", type=int, default=1)
    sweep.add_argument("--k", type=_positive, default=10)
    statement_options(sweep)

    msweep = commands.add_parser(
        "m-sweep",
        help="rebuild the vector index for several M values and measure each, "
             "right after the build and after a restart of the db container",
    )
    msweep.add_argument("--m", type=_index_m, nargs="+", default=[6, 8, 16, 32, 48, 64])
    msweep.add_argument("--ef", type=_positive, nargs="+", default=[20, 40, 80])
    msweep.add_argument("--shapes", choices=SHAPES, nargs="+", default=list(SHAPES))
    msweep.add_argument("--runs", type=_positive, default=3)
    msweep.add_argument("--warmup", type=int, default=1)
    msweep.add_argument("--k", type=_positive, default=10)
    msweep.add_argument("--vector-format", choices=VECTOR_FORMATS, default=DEFAULT_VECTOR_FORMAT)
    msweep.add_argument("--no-restart", action="store_true",
                        help="do not restart the db container (docker compose) after each build")

    commands.add_parser("explain", help="query plans: is the vector index used?")
    return parser


async def restart_database(database: Database, timeout: float = 120) -> None:
    """Restart the db service of docker-compose.yml and wait until MariaDB answers again."""
    await database.disconnect()
    for command in (["docker", "compose", "restart", "db"],
                    ["docker", "compose", "up", "-d", "--wait", "db"]):
        completed = await asyncio.to_thread(
            subprocess.run, command, capture_output=True, text=True, timeout=timeout, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: {completed.stderr.strip()}")
    await database.connect()
    deadline = time.monotonic() + timeout
    while True:
        try:
            async with database.get_session() as session:
                await session.execute(text("SELECT 1"))
            return
        except SQLAlchemyError:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(1)


async def run_m_sweep(args: argparse.Namespace, questions, embedder, retriever,
                      database: Database, environment: dict[str, Any]) -> dict[str, Any]:
    repository = ArticleRepository(database)
    _, original_m, _ = await repository.vector_index()
    if original_m is None:  # no M in the definition: the server default was used
        async with database.get_session() as session:
            original_m = int((await session.execute(text("SELECT @@mhnsw_default_m"))).scalar_one())

    async def rebuild(m: int) -> float:
        print(f"M={m}: rebuilding the vector index...", file=sys.stderr, flush=True)
        seconds = await repository.rebuild_vector_index(m)
        print(f"M={m}: built in {seconds:.1f} s, measuring...", file=sys.stderr, flush=True)
        return seconds

    async def restart() -> None:
        print("Restarting the db container...", file=sys.stderr, flush=True)
        await restart_database(database)

    try:
        return await m_sweep(
            questions, embedder, retriever, args.m, args.ef,
            rebuild=rebuild, restart=None if args.no_restart else restart,
            shapes=args.shapes, runs=args.runs, warmup_runs=args.warmup, k=args.k,
            vector_format=args.vector_format, environment=environment,
        )
    finally:
        print(f"Putting the vector index back to M={original_m}...", file=sys.stderr, flush=True)
        try:
            if database.engine is None:
                await database.connect()
            await repository.rebuild_vector_index(original_m)
            if not args.no_restart:
                await restart()
        except Exception as exc:  # noqa: BLE001 - tell the user how to finish by hand
            print(f"Could not put the index back ({type(exc).__name__}: {exc}). Run: "
                  f"uv run python -m src.ingestion reindex --m {original_m}",
                  file=sys.stderr)


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
            markdown = await explain_plans(retriever, settings.embedding_dimension)
            directory = Path(args.results_dir)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{datetime.now(UTC):%Y%m%d-%H%M%S}_explain.md"
            path.write_text(markdown + "\n", encoding="utf-8")
            print(markdown)
            print(f"Saved {path}")
            return 0
        embedder = await asyncio.to_thread(container.embedder)

        if args.command == "run":
            label = args.label or _run_label(args)
            config = EvalConfig(
                label=label,
                runs=args.runs,
                warmup_runs=args.warmup,
                ef_search=args.ef_search,
                exact=args.exact,
                not_found_threshold=settings.rag_max_distance,
                shape=args.shape,
                vector_format=args.vector_format,
            )
            report = await evaluate(questions, embedder, retriever, config, environment)
        elif args.command == "ef-sweep":
            report = await ef_search_sweep(
                questions, embedder, retriever, args.ef,
                runs=args.runs, warmup_runs=args.warmup, k=args.k, environment=environment,
                shape=args.shape, vector_format=args.vector_format,
            )
            report["label"] = args.label
        else:
            report = await run_m_sweep(args, questions, embedder, retriever, database, environment)
    finally:
        await database.disconnect()

    json_path, md_path = write_report(report, args.results_dir)
    print(md_path.read_text(encoding="utf-8"))
    print(f"Saved {json_path} and {md_path}")
    return 0


def _run_label(args: argparse.Namespace) -> str:
    parts = ["exact" if args.exact else f"ef-{args.ef_search}" if args.ef_search else "default"]
    if args.shape != DEFAULT_SHAPE:
        parts.append(args.shape.replace("_", "-"))
    if args.vector_format != DEFAULT_VECTOR_FORMAT:
        parts.append(args.vector_format)
    return "-".join(parts)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
