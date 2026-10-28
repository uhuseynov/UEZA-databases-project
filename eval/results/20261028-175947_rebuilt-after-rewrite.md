# Evaluation: rebuilt-after-rewrite

Created 2026-10-28T17:59:47+00:00. HNSW index, mhnsw_ef_search=server default. 3 timed runs after 1 warm-up run(s).

## Retrieval (answerable questions)

| questions | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|---|
| all | 60 | 0.633 | 0.800 | 0.883 | 0.950 | 0.744 |
| plain | 43 | 0.628 | 0.837 | 0.930 | 0.977 | 0.761 |
| filtered | 17 | 0.647 | 0.706 | 0.765 | 0.882 | 0.703 |

## Search latency (MariaDB query only, embedding excluded)

| questions | samples | mean ms | std ms | p50 ms | p95 ms |
|---|---|---|---|---|---|
| all | 213 | 22.468 | 48.752 | 9.190 | 56.505 |
| plain | 162 | 9.208 | 2.011 | 8.759 | 12.747 |
| filtered | 51 | 64.588 | 87.665 | 18.272 | 270.937 |

Run-to-run: mean of the per-run averages 22.468 ms, standard deviation 0.522 ms over 3 runs.

## Not found

Distance of the closest chunk (lower is closer):

| questions | n | mean | min | median | max |
|---|---|---|---|---|---|
| answerable | 60 | 0.298 | 0.201 | 0.301 | 0.461 |
| unanswerable | 11 | 0.436 | 0.309 | 0.448 | 0.513 |

With RAG_MAX_DISTANCE=0.420: 0.967 of answerable questions keep their context, 0.727 of unanswerable ones are rejected.
Best separating threshold on this set: 0.3559 (balanced accuracy 0.896).

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
