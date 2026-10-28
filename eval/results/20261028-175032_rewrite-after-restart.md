# Evaluation: rewrite-after-restart

Created 2026-10-28T17:50:32+00:00. HNSW index, mhnsw_ef_search=server default. 3 timed runs after 1 warm-up run(s).

## Retrieval (answerable questions)

| questions | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|---|
| all | 60 | 0.617 | 0.800 | 0.867 | 0.950 | 0.733 |
| plain | 43 | 0.605 | 0.837 | 0.907 | 0.977 | 0.744 |
| filtered | 17 | 0.647 | 0.706 | 0.765 | 0.882 | 0.703 |

## Search latency (MariaDB query only, embedding excluded)

| questions | samples | mean ms | std ms | p50 ms | p95 ms |
|---|---|---|---|---|---|
| all | 213 | 67.939 | 43.173 | 67.215 | 84.917 |
| plain | 162 | 68.888 | 4.392 | 67.959 | 77.301 |
| filtered | 51 | 64.924 | 88.480 | 17.929 | 270.880 |

Run-to-run: mean of the per-run averages 67.939 ms, standard deviation 0.597 ms over 3 runs.

## Not found

Distance of the closest chunk (lower is closer):

| questions | n | mean | min | median | max |
|---|---|---|---|---|---|
| answerable | 60 | 0.298 | 0.201 | 0.301 | 0.461 |
| unanswerable | 11 | 0.429 | 0.309 | 0.448 | 0.493 |

With RAG_MAX_DISTANCE=0.420: 0.967 of answerable questions keep their context, 0.727 of unanswerable ones are rejected.
Best separating threshold on this set: 0.3559 (balanced accuracy 0.896).

Questions whose results changed between runs: 13

## Environment

- python: `3.14.8`
- platform: `Windows-11-10.0.26340-SP0`
- cpu_count: `12`
- embedding_model: `BAAI/bge-base-en-v1.5`
- embedding_dimension: `768`
- git_commit: `978faec`
- mariadb_version: `12.3.3-MariaDB-ubu2404`
- mhnsw_ef_search_default: `20`
- articles: `262`
- chunks: `6144`
