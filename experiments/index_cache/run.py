#!/usr/bin/env python3
"""Does the size limit of MariaDB's vector index cache explain the slow index after a re-ingest?

Background (MariaDB 12.3 source, sql/vector_mhnsw.cc):
- The HNSW graph of a vector index is read into a cache. After a search, if the cache is
  larger than mhnsw_max_cache_size (16 MB by default), the whole cache is dropped, so the
  next search reads the graph from the table again.
- Deleting a row only marks its node as deleted. The node stays in the graph, and searches
  still walk through it.

So after every chunk was deleted and inserted again, the graph holds about twice as many
nodes. If that no longer fits into 16 MB, every search starts with an empty cache. This
script tests that by changing only the cache size:

 1. replace every chunk (delete and insert again, one transaction), restart MariaDB
 2. SET GLOBAL mhnsw_max_cache_size = 16 MB (MariaDB's default), measure -> label replaced-16mb
 3. 64 MB, measure                                        -> replaced-64mb
 4. 16 MB again, measure                                  -> replaced-16mb-again
 5. rebuild the index (drop and add), restart, 16 MB, measure -> rebuilt-16mb
 6. 64 MB again, measure                                  -> rebuilt-64mb
 7. restart MariaDB, which puts the cache size back to the value in docker-compose.yml

Each measurement is `python -m src.evaluation run` (all 71 questions, 1 warm-up and 3 timed
runs); the results go to eval/results like every other run. By default it uses the statement
and query format of the first run on 30 October (--shape join --vector-format text). The row counts of the tables,
including the hidden table that stores the graph, are printed after steps 1 and 5.

Run from the repository root with the compose database up and loaded:

    uv run python experiments/index_cache/run.py

It changes the stored chunks only by writing the same rows back, and it leaves the index
rebuilt with its current M. It needs `docker compose` and runs SQL as root inside the db
container (with the container's own MARIADB_ROOT_PASSWORD).
"""

import argparse
import subprocess
import sys
import time

MB = 1024 * 1024

REPLACE_CHUNKS = """
DROP TABLE IF EXISTS ueza_chunk_copy;
CREATE TABLE ueza_chunk_copy AS
  SELECT id, article_id, chunk_index, chunk_text, embedding FROM article_chunks;
START TRANSACTION;
DELETE FROM article_chunks WHERE id > 0;
INSERT INTO article_chunks (id, article_id, chunk_index, chunk_text, embedding)
  SELECT id, article_id, chunk_index, chunk_text, embedding FROM ueza_chunk_copy ORDER BY id;
COMMIT;
DROP TABLE ueza_chunk_copy;
ANALYZE TABLE article_chunks;
"""

# InnoDB writes '#' in table names as @0023, so the graph table article_chunks#i#01 shows up
# as article_chunks@0023i@002301. NUM_ROWS is InnoDB's estimate.
TABLE_ROWS = """
SELECT NAME, NUM_ROWS FROM information_schema.INNODB_SYS_TABLESTATS
WHERE NAME LIKE CONCAT(DATABASE(), '/article_chunks%');
SELECT COUNT(*) AS chunks FROM article_chunks;
"""


def log(message: str) -> None:
    print(f"\n[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run(command: list[str], *, stdin: str | None = None, check: bool = True) -> str:
    completed = subprocess.run(command, input=stdin, capture_output=True, text=True)
    if completed.returncode != 0 and check:
        sys.exit(f"{' '.join(command[:4])}... failed:\n{completed.stderr.strip()}")
    return completed.stdout + (completed.stderr if completed.returncode else "")


def root_sql(sql: str, *, check: bool = True, scalar: bool = False) -> str:
    """Run SQL as root in the db container, with the container's own root password."""
    output = "-N -B" if scalar else "--table"
    command = ["docker", "compose", "exec", "-T", "db", "sh", "-c",
               f'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" {output}']
    result = run(command, stdin=sql, check=check)
    return result.strip() if scalar else result


def restart() -> None:
    log("Restarting MariaDB")
    run(["docker", "compose", "restart", "db"])
    run(["docker", "compose", "up", "-d", "--wait", "db"])


def set_cache(size: int) -> None:
    log(f"SET GLOBAL mhnsw_max_cache_size = {size // MB} MB")
    root_sql(f"SET GLOBAL mhnsw_max_cache_size = {size};")
    print("now", root_sql("SELECT @@global.mhnsw_max_cache_size;", scalar=True))


def measure(label: str, args: argparse.Namespace) -> None:
    log(f"Measuring: {label}")
    completed = subprocess.run(
        [sys.executable, "-m", "src.evaluation", "run", "--runs", str(args.runs), "--label", label,
         "--shape", args.shape, "--vector-format", args.vector_format],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        sys.exit(f"evaluation failed:\n{completed.stderr[-3000:]}")
    for line in completed.stdout.splitlines():
        if line.startswith(("| all ", "| plain ", "| filtered ", "Saved ")):
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--small", type=int, default=16, help="small cache size in MB")
    parser.add_argument("--large", type=int, default=64, help="large cache size in MB")
    parser.add_argument("--shape", default="join", choices=["join", "nearest_first"])
    parser.add_argument("--vector-format", default="text", choices=["text", "binary"])
    args = parser.parse_args()

    print(root_sql("SELECT VERSION(), @@global.mhnsw_max_cache_size;"))
    small = args.small * MB

    log("Replacing every chunk (delete and insert again in one transaction)")
    start = time.perf_counter()
    root_sql(REPLACE_CHUNKS)
    print(f"done in {time.perf_counter() - start:.1f} s")
    print(root_sql(TABLE_ROWS, check=False))
    restart()

    set_cache(small)
    measure(f"replaced-{args.small}mb", args)
    set_cache(args.large * MB)
    measure(f"replaced-{args.large}mb", args)
    set_cache(small)
    measure(f"replaced-{args.small}mb-again", args)

    log("Rebuilding the vector index")
    print(run([sys.executable, "-m", "src.ingestion", "reindex"]).strip().splitlines()[-1])
    print(root_sql(TABLE_ROWS, check=False))
    restart()
    set_cache(small)
    measure(f"rebuilt-{args.small}mb", args)
    set_cache(args.large * MB)
    measure(f"rebuilt-{args.large}mb", args)
    restart()
    log("Done. The cache size is back to the value in docker-compose.yml.")


if __name__ == "__main__":
    main()
