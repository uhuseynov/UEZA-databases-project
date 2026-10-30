#!/usr/bin/env python3
"""Does MariaDB size its vector search by the row-count estimate of the graph table?

Observation: right after the vector index is built, a search returns the exact top 10 for
every M and mhnsw_ef_search; after a server restart, index recall drops to about 0.85-0.91
for every M and ef_search. A restart keeps the graph but loses what MariaDB holds in memory.

Background (MariaDB 12.3 source, sql/vector_mhnsw.cc): a search marks visited nodes in a
Bloom filter whose size is capped at graph_size / 1.3. A full filter reports nodes as
"already visited" that were not, and those nodes are skipped. While the index is built,
graph_size is counted in memory, one per inserted node. After a restart it is read from
the storage engine's row estimate of the hidden table that stores the graph
(graph->file->stats.records), which for InnoDB comes from its persistent statistics.

So if those statistics undercount the graph, every search after a restart runs with a
filter that is too small. This script changes only that estimate:

 1. rebuild the index, restart MariaDB, print the statistics, measure   -> stats-as-is
 2. set the graph table's n_rows to the number of chunks, restart, measure -> stats-corrected
 3. put the original n_rows back, restart, measure                         -> stats-restored

Each measurement is two ef-sweeps (index recall against the full scan), one per statement
shape, with the query vector sent as binary. The results go to eval/results.

    uv run python experiments/index_cache/graph_stats.py
"""

import subprocess
import sys

from run import log, restart, root_sql, run

STATS = """
SELECT table_name, n_rows, last_update FROM mysql.innodb_table_stats
WHERE database_name = DATABASE() AND table_name LIKE 'article_chunks%';
SELECT NAME, NUM_ROWS, MODIFIED_COUNTER FROM information_schema.INNODB_SYS_TABLESTATS
WHERE NAME LIKE CONCAT(DATABASE(), '/article_chunks%');
"""

GRAPH_ROW = """
SELECT table_name, n_rows FROM mysql.innodb_table_stats
WHERE database_name = DATABASE() AND table_name LIKE 'article_chunks%'
  AND table_name <> 'article_chunks';
"""


def measure(label: str) -> None:
    for shape in ("join", "nearest_first"):
        log(f"Measuring: {label}, {shape}")
        completed = subprocess.run(
            [sys.executable, "-m", "src.evaluation", "ef-sweep", "--ef", "20", "80",
             "--shape", shape, "--vector-format", "binary", "--label", f"{label}-{shape}"],
            capture_output=True, text=True,
        )
        if completed.returncode != 0:
            sys.exit(f"evaluation failed:\n{completed.stderr[-3000:]}")
        for line in completed.stdout.splitlines():
            if line.startswith(("| exact ", "| 20 ", "| 80 ", "Saved ")):
                print(line)


def set_graph_rows(table: str, rows: int) -> None:
    log(f"Setting n_rows of {table} to {rows}")
    root_sql(
        f"UPDATE mysql.innodb_table_stats SET n_rows = {rows} "
        f"WHERE database_name = DATABASE() AND table_name = '{table}';"
    )


def main() -> None:
    log("Rebuilding the vector index")
    print(run([sys.executable, "-m", "src.ingestion", "reindex"]).strip().splitlines()[-1])
    restart()
    print(root_sql(STATS, check=False))

    row = root_sql(GRAPH_ROW, scalar=True)
    if not row:
        print("InnoDB keeps no persistent statistics for the graph table; nothing to change.")
        measure("stats-none")
        return
    table, original = row.splitlines()[0].split("\t")
    original = int(original)
    if not all(c.isalnum() or c in "#@_" for c in table):
        sys.exit(f"unexpected graph table name: {table!r}")
    chunks = int(root_sql("SELECT COUNT(*) FROM article_chunks;", scalar=True))
    print(f"graph table {table}: n_rows {original}, chunks {chunks}")

    measure("stats-as-is")
    print(root_sql(STATS, check=False))

    set_graph_rows(table, chunks)
    restart()
    measure("stats-corrected")
    print(root_sql(STATS, check=False))

    set_graph_rows(table, original)
    restart()
    measure("stats-restored")
    print(root_sql(STATS, check=False))
    log("Done. The statistics are back to what InnoDB had computed.")


if __name__ == "__main__":
    main()
