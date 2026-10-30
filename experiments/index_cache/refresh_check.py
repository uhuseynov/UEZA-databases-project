#!/usr/bin/env python3
"""Check that a rebuilt index gets correct graph statistics, then measure the shipped setup.

`python -m src.ingestion reindex` now inserts and deletes one chunk after the rebuild, so
that InnoDB recalculates the statistics of the graph table (see graph_stats.py for why).
This script:

 1. rebuilds the index and prints the statistics right away and 30 seconds later
 2. restarts MariaDB and prints them again
 3. measures the shipped configuration (nearest-first statement, binary query vector, the
    server settings of docker-compose.yml): an ef-sweep and a full evaluation run

    uv run python experiments/index_cache/refresh_check.py
"""

import subprocess
import sys
import time

from graph_stats import STATS
from run import log, restart, root_sql, run


def evaluate(arguments: list[str]) -> None:
    log("Measuring: " + " ".join(arguments))
    completed = subprocess.run([sys.executable, "-m", "src.evaluation", *arguments],
                               capture_output=True, text=True)
    if completed.returncode != 0:
        sys.exit(f"evaluation failed:\n{completed.stderr[-3000:]}")
    print(completed.stdout)


def main() -> None:
    print(root_sql("SELECT @@global.mhnsw_ef_search, @@global.mhnsw_max_cache_size;"))

    log("Rebuilding the vector index")
    print(run([sys.executable, "-m", "src.ingestion", "reindex"]).strip().splitlines()[-1])
    print(root_sql(STATS, check=False))
    log("Waiting 30 s for InnoDB's background statistics")
    time.sleep(30)
    print(root_sql(STATS, check=False))

    restart()
    print(root_sql(STATS, check=False))

    evaluate(["ef-sweep", "--ef", "10", "20", "40", "80", "160", "--label", "final-ef-sweep"])
    evaluate(["run", "--runs", "5", "--label", "final"])
    print(root_sql(STATS, check=False))


if __name__ == "__main__":
    main()
