# mhnsw_ef_search sweep

Created 2026-10-30T20:31:29+00:00. 3 timed runs per setting. Statement shape nearest_first, query vector as binary. Index recall = share of the exact top-10 chunks (full scan) that the index returned.

| ef_search | index recall@10 | plain | filtered | Recall@10 | MRR | mean ms | p95 ms | plain mean ms | filtered mean ms | filtered < 10 results |
|---|---|---|---|---|---|---|---|---|---|---|
| exact | 1.000 | 1.000 | 1.000 | 0.950 | 0.733 | 19.740 | 26.876 | 21.122 | 15.351 | 0 |
| 20 | 0.925 | 0.902 | 1.000 | 0.933 | 0.730 | 14.610 | 24.621 | 14.456 | 15.099 | 0 |
| 80 | 0.934 | 0.913 | 1.000 | 0.933 | 0.730 | 16.607 | 28.440 | 16.239 | 17.777 | 0 |

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
