# FAISS Baseline

[← Database](./Home.md) | [Documentation Home](../Home.md)

The same 6,144 vectors and the same 71 questions, searched by FAISS next to MariaDB. FAISS is the usual choice for a separate vector index, so this is the comparison behind "why MariaDB": what the separate index wins, and what it costs once the rest of the data lives in a database.

Measured on 6 November 2026, with the shipped MariaDB setup (nearest-first statement, binary query vector, `M=16`, `mhnsw_ef_search` 40) after a restart. Raw output: [eval/results/20261106-172053_faiss.md](../../eval/results/20261106-172053_faiss.md).

## Summary

- **Both compare the same vectors the same way.** MariaDB's full scan and FAISS's exact search returned the same top 10 for all 71 questions.
- **FAISS searches faster, the application does not.** An HNSW search takes 0.09 ms in FAISS and 0.46 ms inside MariaDB. But an application with FAISS still needs the text from the database: FAISS plus one query for the text took 6.3 ms, MariaDB's single statement 5.1 ms.
- **At the same `ef`, MariaDB's index found more of the true neighbours:** 95% of the exact top 10 at 40, where FAISS returned 90% and needed `efSearch` 80 for 95%.
- **Filters are where a separate index loses.** FAISS has no metadata, so a filtered question first needs the matching chunk ids from MariaDB (16.6 ms on average), then the FAISS search, then the text: 17.2 ms in total and 87% of the exact answer, against 8.4 ms and the exact answer from MariaDB's one statement. "Take the 10 nearest, then filter" returned fewer than 10 chunks for 16 of the 17 filtered questions.
- **FAISS builds faster and cannot delete.** Its HNSW index built in 0.6 s against MariaDB's 5.5 s, but `remove_ids` is not implemented for it: replacing an article means rebuilding the index or filtering the old ids out forever.

## Setup

- `python -m src.evaluation faiss` ([src/evaluation/faiss_baseline.py](../../src/evaluation/faiss_baseline.py)) reads every vector from MariaDB (1.0 s) and builds two FAISS 1.15.1 indexes in memory: `IndexFlatIP` (exact) and `IndexHNSWFlat` with `M=16`, the same as MariaDB's index, and FAISS's default `efConstruction` 40.
- The vectors are normalised and compared by inner product, which ranks them like `VEC_DISTANCE_COSINE`.
- Every question is searched on its own, as the application does, after one warm-up pass and in 3 timed passes. FAISS runs on one thread, like one MariaDB statement.
- Index recall is the share of the exact top 10 (FAISS's exact search) that a method returned. Recall@10 is the share of answerable questions with a chunk of the correct article in the top 10.
- MariaDB's own time comes from `ANALYZE`, one run per question. All other times are measured from Python and include the round trip through Docker Desktop.

## Questions without a filter (54)

| Method | `ef` | Index recall@10 | Recall@10 | Mean | p95 |
| --- | --- | --- | --- | --- | --- |
| FAISS exact (`IndexFlatIP`) | – | 1.000 | 0.977 | 1.93 ms | 2.52 ms |
| FAISS HNSW | 10 | 0.778 | 0.930 | 0.07 ms | 0.09 ms |
| FAISS HNSW | 20 | 0.859 | 0.954 | 0.06 ms | 0.09 ms |
| FAISS HNSW | 40 | 0.898 | 0.977 | 0.09 ms | 0.13 ms |
| FAISS HNSW | 80 | 0.954 | 0.977 | 0.16 ms | 0.21 ms |
| FAISS HNSW | 160 | 0.980 | 0.977 | 0.39 ms | 0.56 ms |
| **MariaDB statement** | 40 | **0.952** | **0.977** | **5.09 ms** | **7.55 ms** |
| FAISS HNSW, then MariaDB for the text | 40 | 0.898 | 0.977 | 6.26 ms | 8.40 ms |

Inside MariaDB the statement took 0.46 ms on average (p95 0.76 ms).

- FAISS's HNSW search is about 5 times faster than MariaDB's inside the server, and 50 times faster than the statement as the application sees it. Almost all of MariaDB's 5 ms is the round trip, which an application with FAISS pays too, for the text.
- At `ef` 40, MariaDB returned 95% of the exact neighbours and FAISS 90%. We did not tune FAISS beyond its defaults; with `efSearch` 80 it matches MariaDB's recall at 0.16 ms.
- From `ef` 40 on, both find the correct article as often as the exact search.

## Questions with a filter (17)

| Method | `ef` | Index recall@10 | Recall@10 | Fewer than 10 chunks | Mean | p95 |
| --- | --- | --- | --- | --- | --- | --- |
| FAISS exact over the allowed ids | – | 1.000 | 0.882 | 0 | 0.21 ms | 0.71 ms |
| FAISS HNSW, allowed ids as selector | 10 | 0.729 | 0.765 | 2 | 0.06 ms | 0.08 ms |
| FAISS HNSW, allowed ids as selector | 40 | 0.871 | 0.824 | 1 | 0.12 ms | 0.14 ms |
| FAISS HNSW, allowed ids as selector | 160 | 0.982 | 0.882 | 0 | 0.36 ms | 0.43 ms |
| FAISS HNSW, 10 nearest, then filter | 40 | 0.494 | 0.588 | 16 | 0.14 ms | 0.26 ms |
| FAISS HNSW, 100 nearest, then filter | 100 | 0.888 | 0.765 | 2 | 0.36 ms | 0.57 ms |
| FAISS HNSW, 1,000 nearest, then filter | 1000 | 1.000 | 0.882 | 0 | 4.37 ms | 4.98 ms |
| **MariaDB statement** | – | **1.000** | **0.882** | **0** | **8.38 ms** | **19.02 ms** |
| MariaDB ids, FAISS HNSW with selector, MariaDB text | 40 | 0.871 | 0.824 | 1 | 17.15 ms | 40.28 ms |

The FAISS rows except the last do not include the 16.6 ms on average (p95 48.7 ms) that MariaDB took to return the ids of the allowed chunks: between 16 and 3,742 per question, median 142. Inside MariaDB the filtered statement took 3.4 ms on average (p95 13.7 ms).

- **The ids are the expensive part.** Once FAISS has them, an exact search over them takes 0.2 ms. Getting them takes longer than MariaDB's whole filtered search, in part because they have to cross the connection: up to 3,742 ids for "linked from Artificial intelligence".
- **HNSW with a selector is approximate.** At `efSearch` 40 it lost 13% of the exact answer and returned fewer than 10 chunks for one question; it needed 160 to come close.
- **Post-filtering fails on selective filters.** With the 10 nearest chunks, 16 of the 17 questions got fewer than 10 chunks back, on average 4.9. With 1,000 it was exact, at 4.4 ms. How many are enough depends on the filter, which is what MariaDB's optimizer decides for us.
- MariaDB's statement is exact for every filter, because it starts from the filter's index (see [Vector Search](./Vector-Search.md#filtered-searches)).

## Build, size and updates

| | FAISS | MariaDB |
| --- | --- | --- |
| Build the HNSW index (6,144 vectors, `M=16`) | 0.59 s (`efConstruction` 40, one thread) | 5.5 s (`ADD VECTOR INDEX`) |
| Size | 18.8 MB in the process (flat index 18.0 MB) | the graph table, cached up to `mhnsw_max_cache_size` (64 MB here) |
| Replace one article (94 vectors) | HNSW: not possible (`remove_ids not implemented for this type of index`); the flat index: 1.6 ms | one transaction with the article's other rows; deleted nodes stay in the graph until a rebuild |

FAISS builds about 9 times faster. But the vectors also have to get there: reading them from MariaDB took 1.0 s, and every change to an article has to reach both systems, which MariaDB does in the article's own transaction ([Ingestion](../ingestion/Home.md#5-store-srcdatabaserepositoriesarticlespy)).

## Limits

- FAISS was run with its defaults (`efConstruction` 40) and MariaDB with ours; MariaDB builds with an internal construction `ef` of 10 (`sql/vector_mhnsw.cc`). Neither was tuned against the other.
- One machine and sequential searches. FAISS's throughput with several threads and concurrent MariaDB searches are not measured.
- FAISS ran inside the Python process. A FAISS service behind its own API would add a round trip of its own.
- The first run of the day was taken right after the integration tests had rebuilt the index, without a restart: MariaDB returned 99.4% of the exact neighbours there ([run](../../eval/results/20261106-161313_faiss.md)). The numbers above are the second run, after a restart, the state the README reports.

## Reproducing it

```bash
uv sync                                   # faiss-cpu is in the dev dependency group
uv run python -m src.evaluation faiss     # --ef, --fetch, --m, --ef-construction, --threads
```
