# Vector Index State

[← Database](./Home.md) | [Documentation Home](../Home.md)

The same `VECTOR INDEX`, with the same `M` and `mhnsw_ef_search`, searched at three different speeds on our data, and with different results, depending on what had happened to it before. This page records the measurements, in the order they were taken on 28 October 2026.

## Setup

- MariaDB 12.3.3 in Docker Desktop on a Windows 11 laptop (12 logical CPUs), default server settings.
- 262 articles, 6,144 chunks, `BAAI/bge-base-en-v1.5` vectors (768 dimensions), `VECTOR INDEX (embedding) M=16 DISTANCE=cosine`, `mhnsw_ef_search` 20.
- Each run is `make eval`: the 71 questions of the ground truth, one warm-up pass, then 3 timed passes. "Plain" is the 54 questions without a filter, 162 searches per run.
- The exact answer is the same statement ordered by `distance + 0`, a full scan that cannot use the index.

## Results

| State of the index | How we got there | Plain search, mean | Same top 10 as the exact search |
| --- | --- | --- | --- |
| A. Chunks replaced | `make ingest` over an existing load: every article's chunks deleted and inserted again | 70.1 and 69.5 ms (two runs) | 71 of 71 questions |
| B. A, then `OPTIMIZE TABLE article_chunks` | 1.5 s | 71.9 and 70.2 ms | 71 of 71 |
| C. B, then the index dropped and added again | `ALTER TABLE ... DROP INDEX`, `ADD VECTOR INDEX ... M=16 DISTANCE=cosine`, 5.2 s | 36.2 ms | 71 of 71 |
| D. C, then the server restarted | `docker compose restart db` | 9.2 and 9.1 ms (two runs) | 54 and 53 of 71 |
| E. D, then all chunks deleted and inserted again | one transaction, 11.0 s with a backup copy | 69.1 ms | 71 of 71 |
| F. E, then the server restarted | | 68.9 ms | 71 of 71 |

The raw output of every run is in [eval/results](../../eval/results/): the files labelled `all262-run1/2`, `all262-optimized-run1/2`, `all262-reindexed`, `all262-restarted` and `-run2`, `rewrite-before-restart` and `rewrite-after-restart`.

Two `mhnsw_ef_search` sweeps in state D, each after its own restart, measured the share of the exact top 10 that the index returned:

| `mhnsw_ef_search` | 10 | 20 | 40 | 80 | 160 |
| --- | --- | --- | --- | --- | --- |
| index recall@10, first restart | 0.920 | 0.930 | 0.935 | 0.932 | 0.932 |
| index recall@10, second restart | 0.924 | 0.925 | 0.924 | 0.934 | 0.937 |
| plain search, mean, second restart | 10.8 ms | 10.6 ms | 12.8 ms | 13.0 ms | 13.3 ms |

The full scan took 444 ms per plain question. The same sweep in state A gave an index recall of 1.000 at every setting.

## What this means

- **Replacing chunks makes the index twice as slow, and only a rebuild fixes it.** States A, E and F are about 70 ms; neither `OPTIMIZE TABLE` nor a restart brings that back, dropping and adding the index does (C). A likely explanation is that deleted vectors stay in the graph and every search still walks through them, but we have not verified the cause. For us it means: rebuild the index after a re-ingest or a large sync. `make ingest` now does this by itself whenever it replaced stored articles, and `make reindex` does it on demand (5.2 s for 6,144 vectors).
- **Right after a build the index behaves differently than after a restart.** In state C the search took 36 ms and returned exactly the exact top 10; after a restart (D) it took 9 ms and returned 92 to 94% of it. The questions whose results changed are mostly the ones far from every chunk: 9 of the 11 unanswerable questions, against 8 of the 60 answerable ones, and for the answerable ones the rank of the first correct chunk stayed the same in all but one. We have not found out why the two states differ.
- **Measure after a restart.** A running service sees its index after restarts, not right after a build; for our rebuilt index that is state D. Numbers taken right after building it overstate the recall and understate the speed. Our README reports state D.
- **`mhnsw_ef_search` does little in state D.** From 10 to 160 the index recall moves from about 0.92 to 0.94, for a few milliseconds more.
- **Filtered searches are not affected.** They never use the vector index (see [Vector Search](./Vector-Search.md)): in every state the 51 filtered searches took a median of 17 to 24 ms, and the "linked from" filter 190 to 285 ms.

## Limits

- One machine, one small data set (6,144 vectors) and one version of MariaDB, with the default `mhnsw_max_cache_size`.
- The causes above are not verified. We did not look at the server's internal state of the index.
- State D was measured for an index built with `ADD VECTOR INDEX`. An index built row by row during a first load and then restarted was not measured in a controlled way: on 28 October, before any rebuild, a plain search took 52 ms, and we do not know whether the server had been restarted since the first load.
- We did not measure how the slowdown grows when only part of the chunks is replaced, which is what a live sync does.

## Reproducing it

```bash
make eval                                       # the current state
docker compose exec db mariadb -uueza -pueza_password ueza_db -e "OPTIMIZE TABLE article_chunks;"
make reindex                                    # drop and add the vector index
docker compose restart db                       # then make eval again
make eval-sweep                                 # index recall against the full scan
```
