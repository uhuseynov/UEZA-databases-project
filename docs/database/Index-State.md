# Vector Index State

[← Database](./Home.md) | [Documentation Home](../Home.md)

The same `VECTOR INDEX`, with the same `M` and `mhnsw_ef_search`, searched at three different speeds on our data, and with different results, depending on what had happened to it before. On 28 October we recorded the states; on 30 October we found the two causes and tested each by changing only that one thing. This page has both, and what the project does about them.

## Summary

- **Deleted vectors stay in the graph, and the graph then no longer fits into the index cache.** After every chunk was deleted and inserted again, a plain search took 72 ms. Raising `mhnsw_max_cache_size` from 16 MB to 64 MB, with nothing else changed, brought it to 20 ms, and setting it back to 72 ms again. `docker-compose.yml` now starts MariaDB with a 64 MB cache, and the ingest rebuilds the index after replacing articles.
- **After a rebuild, InnoDB believes the graph table is empty.** `ALTER TABLE ... ADD VECTOR INDEX` fills the hidden table that holds the HNSW graph without InnoDB counting the rows, so its statistics say 0 rows. After a restart MariaDB reads the size of the graph from these statistics, and searches then skip part of the graph: index recall@10 0.88 to 0.92 instead of 0.93 to 1.00. Setting the statistic to the real count, with nothing else changed, restored the full recall; setting it back to 0 lost it again. `make reindex` now inserts and deletes one chunk after the rebuild, which makes InnoDB count the table.
- **Both explain the states of 28 October**, see [the table below](#the-states-of-28-october).

## Setup

- MariaDB 12.3.3 in Docker Desktop on a Windows 11 laptop (12 logical CPUs).
- 262 articles, 6,144 chunks, `BAAI/bge-base-en-v1.5` vectors (768 dimensions), `VECTOR INDEX (embedding) M=16 DISTANCE=cosine`.
- Measurements are runs of `python -m src.evaluation` on the 71 ground-truth questions: one warm-up pass, then 3 timed passes. "Plain" means the 54 questions without a filter; a filtered search never uses the vector index ([Vector Search](./Vector-Search.md)).
- Index recall@10 is the share of the exact top 10 (a full scan, `ORDER BY distance + 0`) that a search returned, over the plain questions.
- The mechanisms below come from reading the MariaDB 12.3 source, `sql/vector_mhnsw.cc`. We did not instrument the server; what we verified is the effect of changing one setting at a time.

## Cause 1: deleted vectors and the index cache

What the source does:

- MariaDB keeps the graph in a cache. After each search, if the cache is larger than `mhnsw_max_cache_size` (16 MB by default), the whole cache is dropped (`MHNSW_Share::release`), and the next search reads the nodes it needs from the graph table again.
- Deleting a row only marks its node as deleted (`mhnsw_invalidate`). The node stays in the graph: a search does not return it, but still walks through it. Only a rebuild removes it.

So after a re-ingest, which deletes and inserts every chunk of a replaced article, the graph holds about twice as many nodes as there are chunks. The experiment ([experiments/index_cache/run.py](../../experiments/index_cache/run.py)) deleted and inserted all 6,144 chunks in one transaction, restarted MariaDB and then changed only the cache size. Searches used the statement and query format of that time (the join, query vector as text):

| State | `mhnsw_max_cache_size` | Plain: mean | p95 |
| --- | --- | --- | --- |
| all chunks replaced | 16 MB (default) | 72.5 ms | 91.5 ms |
| the same | 64 MB | 19.9 ms | 24.4 ms |
| the same | 16 MB again | 71.6 ms | 82.0 ms |
| index rebuilt, restarted | 16 MB | 11.4 ms | 14.9 ms |
| the same | 64 MB | 11.4 ms | 23.4 ms |

Filtered searches took 66 to 68 ms in all three "replaced" runs: they do not use the index, so the cache does not matter to them.

With the rebuilt index and the 16 MB cache, 22 of the 71 questions got different chunks in different passes of the same run; with 64 MB, none did. We take that as a hint that the rebuilt graph with `M=16` is also close to 16 MB, but we did not measure the cache's memory.

What we do about it:

- `docker-compose.yml` starts MariaDB with `--mhnsw-max-cache-size=64M`. A live sync replaces some articles between rebuilds, and every replaced chunk leaves a deleted node behind.
- `make ingest` rebuilds the index when it replaced stored articles, and `make reindex` rebuilds it on demand (about 5 s for 6,144 chunks).

## Cause 2: the graph table's statistics after a rebuild

What the source does:

- A search marks the nodes it has visited in a Bloom filter. The filter's size is estimated from the size of the graph and capped at `graph_size / 1.3`. A filter that is too small reports nodes as visited that were not, and the search skips them.
- While an index is being built, `graph_size` is counted in memory, one per inserted node. After a restart it is read from the storage engine's row estimate of the hidden graph table (`MHNSW_Share::acquire`, `graph->file->stats.records`), which for InnoDB comes from its persistent statistics.

After `make reindex` and a restart, `mysql.innodb_table_stats` showed:

| table_name | n_rows |
| --- | --- |
| `article_chunks` | 4,159 (an estimate; the table has 6,144 rows) |
| `article_chunks#i#02`, the graph | 0 |

The graph table was filled by the `ALTER TABLE`, which InnoDB did not count as modifications (`MODIFIED_COUNTER` 0), so it never recalculated the statistics of the then empty table. `ANALYZE TABLE article_chunks` does not reach it.

The experiment ([experiments/index_cache/graph_stats.py](../../experiments/index_cache/graph_stats.py)) changed only that number, with `UPDATE mysql.innodb_table_stats` and a restart after each step. Each step ran an `mhnsw_ef_search` sweep for both statement shapes, with the query vector as binary:

| `n_rows` of the graph table | Join, ef 20 / 80 | Nearest chunks first, ef 20 / 80 | Plain mean, join / nearest first (ef 20) |
| --- | --- | --- | --- |
| 0, as InnoDB had it | 0.894 / 0.894 | 0.881 / 0.920 | 17.9 / 26.0 ms |
| 6,144 | **1.000 / 1.000** | **0.928 / 0.974** | 46.9 / 12.4 ms |
| 0 again | 0.909 / 0.907 | 0.902 / 0.913 | 12.2 / 14.5 ms |

The numbers are index recall@10 for the plain questions. With the right row count, a search after a restart behaves as it does right after a build ([M sweep](./Vector-Search.md#choosing-m-and-ef_search)); with 0, recall stays around 0.9 whatever `M` or `mhnsw_ef_search`. The join statement also gets slower with the right count, because it then searches much further than the 10 rows it needs ([Vector Search](./Vector-Search.md#statement-shape-join-or-nearest-chunks-first)).

What we do about it: `rebuild_vector_index` (behind `make reindex` and the automatic rebuild after an ingest) inserts one chunk, a copy of an existing one, and deletes it again. That counts as a modification of the graph table, and InnoDB recalculates its statistics. [experiments/index_cache/refresh_check.py](../../experiments/index_cache/refresh_check.py) showed `n_rows` 5,376 for the graph table right after `make reindex` (an estimate from sampled pages), and the same after a restart. The deleted copy stays in the graph as one deleted node, like every deleted chunk until the next rebuild.

The first load of the articles inserts row by row, which InnoDB counts, so an index that was never rebuilt does not have this problem. It also explains why searches after our integration tests behaved like a fresh build: the tests insert and delete a few rows after rebuilding the index.

We think both behaviours are worth reporting to MariaDB: the statistics of a graph table built by `ALTER TABLE`, and a whole-cache reset as the only way of staying under `mhnsw_max_cache_size`.

## The states of 28 October

These were measured with the statement and query format of that time (the join, query vector as text, `mhnsw_ef_search` 20, 16 MB cache), before we knew the causes:

| State | How we got there | Plain search, mean | Same top 10 as the exact search | Explained by |
| --- | --- | --- | --- | --- |
| A. Chunks replaced | `make ingest` over an existing load | 70.1 and 69.5 ms (two runs) | 71 of 71 questions | cause 1: the graph with deleted nodes does not fit into the cache |
| B. A, then `OPTIMIZE TABLE article_chunks` | 1.5 s | 71.9 and 70.2 ms | 71 of 71 | the same; `OPTIMIZE TABLE` did not change the time |
| C. B, then the index dropped and added again | 5.2 s | 36.2 ms | 71 of 71 | right after a build: the graph size is known, and the join searches far beyond 10 rows |
| D. C, then the server restarted | `docker compose restart db` | 9.2 and 9.1 ms (two runs) | 54 and 53 of 71 | cause 2: `n_rows` 0, searches skip part of the graph |
| E. D, then all chunks deleted and inserted again | one transaction, 11.0 s | 69.1 ms | 71 of 71 | cause 1; the inserts also made InnoDB count the graph table |
| F. E, then the server restarted | | 68.9 ms | 71 of 71 | cause 1 |

The raw output is in [eval/results](../../eval/results/) (files of 28 October: `all262-run1/2`, `all262-optimized-run1/2`, `all262-reindexed`, `all262-restarted` and `-run2`, `rewrite-before-restart`, `rewrite-after-restart`), and the experiments of 30 October under their labels (`replaced-16mb`, `replaced-64mb`, `replaced-16mb-again`, `rebuilt-16mb`, `rebuilt-64mb`, `stats-as-is-*`, `stats-corrected-*`, `stats-restored-*`, `final-ef-sweep`, `final`).

## What it means for measuring

- An index's state is part of a measurement. We now record `vector_index_m`, `mhnsw_max_cache_size` and `mhnsw_ef_search` in every result file, and measure after a restart, which is the state a running service is in.
- The numbers in the README up to 28 October (9 ms, 92 to 94% of the exact top 10) were taken in state D, with the statistics problem. The current numbers are taken with the fixes above.

## Limits

- One machine, one data set (6,144 vectors), one version of MariaDB (12.3.3).
- The mechanisms are read from the source, not observed inside the server. We did not measure the cache's memory use, and we did not try sizes between 16 and 64 MB.
- The refresh relies on InnoDB's automatic recalculation (`innodb_stats_auto_recalc`, on by default) and gives an estimate (5,376 for 6,144 nodes), not an exact count.
- We have not measured how fast the index slows down when only part of the chunks is replaced, as a live sync does.

## Reproducing it

Each script runs from the repository root with the compose database up and loaded, and prints what it changed:

```bash
uv run python experiments/index_cache/run.py            # cause 1: replaced chunks, 16 MB and 64 MB cache
uv run python experiments/index_cache/graph_stats.py    # cause 2: n_rows of the graph table 0, correct, 0
uv run python experiments/index_cache/refresh_check.py  # make reindex refreshes the statistics; final measurement
```

They run SQL as root inside the db container, change only what is described above and put it back at the end (`run.py` leaves the index rebuilt).
