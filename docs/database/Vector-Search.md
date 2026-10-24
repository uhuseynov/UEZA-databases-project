# Vector Search and Index Parameters

[← Database](./Home.md) | [Documentation Home](../Home.md)

How the vector index is defined, how MariaDB plans a search with and without SQL filters, and why the index uses `M=16`. The numbers come from experiments on generated vectors. Read [Limits](#limits) before quoting them.

## Summary

- The index is `VECTOR INDEX (embedding) M=16 DISTANCE=cosine`. `DISTANCE=cosine` matches the `VEC_DISTANCE_COSINE` searches. MariaDB's default distance is euclidean, which a cosine search cannot use.
- Run `ANALYZE TABLE articles, article_chunks, article_categories, article_links;` after every bulk load. Right after our test load, MariaDB ignored the vector index for an unfiltered search and scanned all chunks (0.68 s for 17,338 chunks). With fresh statistics it used the index (20 to 36 ms).
- With a selective SQL filter, MariaDB does not use the vector index. It finds the matching articles through the filter's index, reads their chunks and sorts them. The answer is exact and costs about 0.04 to 0.05 ms per matching chunk.
- `M=16` replaces MariaDB's default `M=6`: recall against exact search rose from 0.74 to 1.00 for the retriever statement. The price is a slower build (11.9 s instead of 3.8 s) and a slower search (35 ms instead of 20 ms).
- `mhnsw_ef_search` stays at its default of 20. It changed little for the single-table search and nothing for statements that join `articles`.

## The index

```sql
VECTOR INDEX (embedding) M=16 DISTANCE=cosine
```

- `embedding` must be `NOT NULL`, otherwise MariaDB cannot create a vector index.
- `DISTANCE=cosine` is part of the index. A search with another distance function cannot use it.
- `M` is the number of connections each node of the HNSW graph keeps. Larger values give more accurate results but slower builds, slower searches and more memory. MariaDB's default is 6 (`mhnsw_default_m`).
- `mhnsw_ef_search` (default 20) is a session variable: how many candidates a search examines.
- A table can have one vector index, tied to the 768 dimensions of the column.

## How MariaDB plans the search

The retriever statement joins `article_chunks` with `articles`, adds the filters in the `WHERE` clause and ends with `ORDER BY distance LIMIT k`. What MariaDB does with it depends on the filter and on the statistics. Measured on 17,338 chunks:

| Situation | Plan | Result | Time |
| --- | --- | --- | --- |
| No filter, statistics stale after the bulk load | scan `articles`, read their chunks, sort everything | exact | 0.68 s |
| No filter, after `ANALYZE TABLE` | vector index on `article_chunks`, then the join | approximate | about 20 to 36 ms, depending on `M` |
| Selective filter (66 to 1,357 chunks) | find the articles through the filter's index, read their chunks, sort | exact | 3.7 to 54 ms |
| Weak filter (`article_length >= 50000`: 12,230 chunks, 70%) | the same exact plan | exact | 485 ms |
| The weak filter with chunks forced first (`STRAIGHT_JOIN`) | vector index, filter while reading | approximate | 18 to 36 ms |

Consequences:

- The statement in `src/rag/retriever.py` needs no change. With fresh statistics it uses the vector index when there is no filter and an exact filter-first plan when the filter is selective. The statistics are the part to keep up to date.
- The exact plan costs about 0.04 to 0.05 ms per matching chunk, so it is cheaper than the index search (about 20 to 36 ms) up to roughly 500 to 900 matching chunks. For a weak filter MariaDB still chooses it, and the search takes 0.5 s here.
- Do not implement filters as "fetch the N nearest chunks, then filter". With a selective filter and a question about something else, this returned only 0 to 2.8 of 10 rows, even with N = 1000. The time also grows with N (3, 11 and 40 ms for N = 50, 200 and 1000).
- With a join, `mhnsw_ef_search` has no effect (see below), and the search took 20 to 36 ms, against about 1 ms for the same search on the chunks table alone.

## Choosing M and ef_search

Median over 20 query vectors, k = 10, `mhnsw_ef_search` = 20. Recall@10 is the share of the exact top 10 that the statement returned. Each cell shows recall and time.

| M | Index build | Chunks table alone | Retriever statement, no filter | Chunks first, weak filter |
| --- | --- | --- | --- | --- |
| 6 (default) | 3.8 s | 0.53, 0.8 ms | 0.74, 20.0 ms | 0.69, 22.5 ms |
| 8 | 6.0 s | 0.72, 1.0 ms | 0.84, 23.9 ms | 0.82, 23.8 ms |
| 16 | 11.9 s | 0.95, 0.7 ms | 1.00, 35.4 ms | 1.00, 36.2 ms |

`mhnsw_ef_search` from 10 to 160 changed the recall of the chunks-table-alone search only slightly (M=6: 0.49 to 0.57, M=8: 0.71 to 0.76, M=16: 0.95 to 0.97) and not at all for the two statements with a join (0.74, 0.84 and 1.00 for every value). `M` mattered much more.

Decision: `M=16`. The build takes about 12 s for 17,338 chunks, which is acceptable for an ingest that runs rarely. A search of 35 ms is small next to an LLM call. A search on the chunks table alone takes about 1 ms at recall 0.95 and could replace the join statement for unfiltered questions if latency ever matters.

## Method

- **Data:** 262 articles and 17,338 chunks. Titles, lengths, edit dates, dataset groups and categories come from `data/articles.csv`. Chunk counts follow article length (1,000-character chunks, 150 overlap). The 768-dimensional vectors are generated: dataset group centre plus article centre plus noise.
- **Queries:** 20 query vectors, each a stored chunk vector plus noise, so they are new points near real chunks.
- **Ground truth:** the exact answer of the same statement and filter, using `ORDER BY distance + 0`, which cannot use the vector index.
- **Timing:** the median of 3 runs, measured inside the server with `NOW(6)`, so a few tenths of a millisecond of round trip are included.
- **Machine:** Intel Core Ultra 7 255HX (20 threads), 30 GiB RAM, MariaDB 12.3.3 in a Podman container with default settings (`mhnsw_max_cache_size` is 16 MB).
- **Scripts and raw output:** [experiments/vector_filters](../../experiments/vector_filters/README.md).

## Limits

- The vectors are generated. Many chunks of one article are almost equally far from a query, so "overlap with exact search" is harsh, and the absolute recall values will not transfer to real embeddings. Compare the settings with each other.
- Not measured: index size and memory use, concurrent searches, inserts during searches, and `M` values above 16.
- One machine, 20 queries, 3 timing runs each.
- The first experiment ran before `ANALYZE TABLE`, so its plans show the stale-statistics behavior (`results/01-plans-before-analyze.txt`).
- The results must be repeated on the real embeddings once the ingest has loaded them: `make eval-explain` shows the plans, `make eval-sweep` varies `mhnsw_ef_search`, and comparing `M` values means rebuilding the index.
