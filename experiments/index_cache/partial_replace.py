#!/usr/bin/env python3
"""How does the vector index degrade when only part of the chunks is replaced, as a sync does?

A replaced chunk leaves a deleted node in the HNSW graph until the next rebuild
(docs/database/Index-State.md). This script replaces a growing share of the chunks, whole
articles at a time, and measures after each step, after a restart, with the 64 MB cache of
docker-compose.yml and with MariaDB's default 16 MB:

 1. rebuild the index (with the statistics refresh), restart        -> partial-0pct-*
 2. replace the chunks of the first articles until 10% are replaced -> partial-10pct-*
 3. ... 25%, 50% and 100% (counted from the start, all different articles)
 4. rebuild the index and restart

Each measurement is an ef-sweep at the server's mhnsw_ef_search (40): index recall against
the full scan and the latency of the questions without a filter. Replacing writes the same
rows back (same ids, text and vectors), in one transaction per step, so the data does not
change; only the graph collects deleted nodes. The results go to eval/results.

    uv run python experiments/index_cache/partial_replace.py
"""

import argparse
import subprocess
import sys
import time

from run import MB, TABLE_ROWS, log, restart, root_sql, run, set_cache

REPLACE_ARTICLES = """
DROP TABLE IF EXISTS ueza_chunk_copy;
CREATE TABLE ueza_chunk_copy AS
  SELECT id, article_id, chunk_index, chunk_text, embedding FROM article_chunks
  WHERE article_id IN ({ids});
START TRANSACTION;
DELETE FROM article_chunks WHERE article_id IN ({ids});
INSERT INTO article_chunks (id, article_id, chunk_index, chunk_text, embedding)
  SELECT id, article_id, chunk_index, chunk_text, embedding FROM ueza_chunk_copy ORDER BY id;
COMMIT;
DROP TABLE ueza_chunk_copy;
ANALYZE TABLE article_chunks;
"""


def chunk_counts() -> list[tuple[int, int]]:
    output = root_sql(
        "SELECT article_id, COUNT(*) FROM article_chunks GROUP BY article_id ORDER BY article_id;",
        scalar=True,
    )
    return [(int(a), int(n)) for a, n in (line.split("\t") for line in output.splitlines())]


def measure(label: str, runs: int) -> None:
    log(f"Measuring: {label}")
    completed = subprocess.run(
        [sys.executable, "-m", "src.evaluation", "ef-sweep", "--ef", "40", "--runs", str(runs),
         "--label", label],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        sys.exit(f"evaluation failed:\n{completed.stderr[-3000:]}")
    for line in completed.stdout.splitlines():
        if line.startswith(("| exact ", "| 40 ", "Saved ")):
            print(line)


def measure_both(label: str, runs: int, large: int, small: int) -> None:
    set_cache(large * MB)
    measure(f"{label}-{large}mb", runs)
    set_cache(small * MB)
    measure(f"{label}-{small}mb", runs)
    set_cache(large * MB)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--steps", type=int, nargs="+", default=[10, 25, 50, 100],
                        help="cumulative shares of the chunks to replace, in percent")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--large", type=int, default=64, help="large cache size in MB")
    parser.add_argument("--small", type=int, default=16, help="small cache size in MB")
    args = parser.parse_args()

    log("Rebuilding the vector index")
    print(run([sys.executable, "-m", "src.ingestion", "reindex"]).strip().splitlines()[-1])
    restart()
    print(root_sql(TABLE_ROWS, check=False))
    measure_both("partial-0pct", args.runs, args.large, args.small)

    articles = chunk_counts()
    total = sum(n for _, n in articles)
    replaced, position = 0, 0
    for percent in args.steps:
        target = total * percent / 100
        batch = []
        while position < len(articles) and replaced < target:
            article_id, count = articles[position]
            batch.append(article_id)
            replaced += count
            position += 1
        if batch:
            log(f"Replacing {len(batch)} more articles: {replaced} of {total} chunks "
                f"({100 * replaced / total:.1f}%) replaced since the rebuild")
            start = time.perf_counter()
            root_sql(REPLACE_ARTICLES.format(ids=",".join(str(a) for a in batch)))
            print(f"done in {time.perf_counter() - start:.1f} s")
        restart()
        print(root_sql(TABLE_ROWS, check=False))
        measure_both(f"partial-{percent}pct", args.runs, args.large, args.small)

    log("Rebuilding the vector index")
    print(run([sys.executable, "-m", "src.ingestion", "reindex"]).strip().splitlines()[-1])
    restart()
    log("Done. The index is rebuilt and the cache size is back to docker-compose.yml.")


if __name__ == "__main__":
    main()
