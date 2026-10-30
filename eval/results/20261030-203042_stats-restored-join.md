# mhnsw_ef_search sweep

Created 2026-10-30T20:30:42+00:00. 3 timed runs per setting. Statement shape join, query vector as binary. Index recall = share of the exact top-10 chunks (full scan) that the index returned.

| ef_search | index recall@10 | plain | filtered | Recall@10 | MRR | mean ms | p95 ms | plain mean ms | filtered mean ms | filtered < 10 results |
|---|---|---|---|---|---|---|---|---|---|---|
| exact | 1.000 | 1.000 | 1.000 | 0.950 | 0.733 | 18.161 | 25.416 | 19.888 | 12.677 | 0 |
| 20 | 0.931 | 0.909 | 1.000 | 0.933 | 0.722 | 12.795 | 22.803 | 12.227 | 14.600 | 0 |
| 80 | 0.930 | 0.907 | 1.000 | 0.950 | 0.735 | 14.910 | 26.225 | 14.875 | 15.019 | 0 |

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
