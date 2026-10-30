# mhnsw_ef_search sweep

Created 2026-10-30T20:29:05+00:00. 3 timed runs per setting. Statement shape join, query vector as binary. Index recall = share of the exact top-10 chunks (full scan) that the index returned.

| ef_search | index recall@10 | plain | filtered | Recall@10 | MRR | mean ms | p95 ms | plain mean ms | filtered mean ms | filtered < 10 results |
|---|---|---|---|---|---|---|---|---|---|---|
| exact | 1.000 | 1.000 | 1.000 | 0.950 | 0.733 | 23.807 | 33.854 | 24.850 | 20.494 | 0 |
| 20 | 1.000 | 1.000 | 1.000 | 0.950 | 0.733 | 39.657 | 58.419 | 46.868 | 16.751 | 0 |
| 80 | 1.000 | 1.000 | 1.000 | 0.950 | 0.733 | 35.984 | 49.859 | 42.186 | 16.286 | 0 |

## Environment

- python: `3.14.8`
- platform: `Windows-11-10.0.26340-SP0`
- cpu_count: `12`
- embedding_model: `BAAI/bge-base-en-v1.5`
- embedding_dimension: `768`
- git_commit: `b8932a0`
- mariadb_version: `12.3.3-MariaDB-ubu2404`
- mhnsw_ef_search_default: `20`
- articles: `262`
- chunks: `6144`
- mhnsw_max_cache_size: `16777216`
- vector_index_m: `16`
- vector_index_distance: `cosine`
