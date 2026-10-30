# Vector Search and Index Parameters

[← Database](./Home.md) | [Documentation Home](../Home.md)

How the vector index is defined, how a search is written and how MariaDB plans it, and why the index uses `M=16` and `mhnsw_ef_search` 40. The measurements on the real embeddings are from 30 October 2026. Our first experiments, on generated vectors, are kept [at the end](#first-experiments-on-generated-vectors), with what changed since.

## Summary

- **Send the query vector as binary, not as text.** MariaDB evaluates `VEC_FromText(...)` again for every row it compares. Written as a hex literal of its binary value, the same vector made a full scan 25 times faster (608 to 24 ms) and filtered searches 7.5 times faster (mean 95 to 12.6 ms), with the same results.
- **Without a filter, take the nearest chunks first, then join.** With the join in the same `SELECT`, MariaDB searched the graph far beyond the 10 rows it needed: it returned the exact top 10, but took 32 to 67 ms and ignored `mhnsw_ef_search`. With the nearest chunks taken from `article_chunks` alone, the index behaves as HNSW should: `M` and `mhnsw_ef_search` trade recall for speed.
- **`M=16`, `mhnsw_ef_search` 40.** After a restart, the search returns 95% of the exact top 10, and the correct article is among the first 10 chunks as often as with the exact search. `M=32` would add about 0.04 index recall for 4.5 times the build time.
- **With a filter, MariaDB does not use the vector index.** It finds the matching articles through the filter's index, reads their chunks and sorts them by distance, so the answer is exact.
- **Keep the statistics right.** `ANALYZE TABLE` after a bulk load, or the index is not used at all; and after a rebuild, the statistics of the hidden graph table ([Vector Index State](./Index-State.md)).

## The index

```sql
VECTOR INDEX (embedding) M=16 DISTANCE=cosine
```

- `embedding` must be `NOT NULL`, otherwise MariaDB cannot create a vector index.
- `DISTANCE=cosine` is part of the index. A search with another distance function cannot use it.
- `M` is the number of connections each node of the HNSW graph keeps (twice as many on the bottom layer). Larger values give more accurate results but slower builds, slower searches and more memory. MariaDB's default is 6 (`mhnsw_default_m`).
- `mhnsw_ef_search` is how many candidates a search keeps; MariaDB never searches for fewer than that, even with a smaller `LIMIT`. Our `docker-compose.yml` sets it to 40 for the server (MariaDB's default is 20); `retrieve(..., ef_search=...)` overrides it for one query.
- `mhnsw_max_cache_size` is the memory for one index's graph. Our `docker-compose.yml` sets 64 MB instead of 16 MB ([why](./Index-State.md#cause-1-deleted-vectors-and-the-index-cache)).
- A table can have one vector index, tied to the 768 dimensions of the column.

## The search statement

[src/rag/retriever.py](../../src/rag/retriever.py) writes a search without a filter like this:

```sql
SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, c.chunk_index, c.chunk_text, n.distance
FROM (SELECT id, VEC_DISTANCE_COSINE(embedding, X'3a1f...') AS distance
      FROM article_chunks ORDER BY distance LIMIT :k) n
JOIN article_chunks c ON c.id = n.id
JOIN articles a ON a.id = c.article_id
ORDER BY n.distance
```

and a search with filters like this:

```sql
SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, c.chunk_index, c.chunk_text,
       VEC_DISTANCE_COSINE(c.embedding, X'3a1f...') AS distance
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE a.root_category = :root_category AND a.article_length >= :min_length
ORDER BY distance
LIMIT :k
```

- `X'...'` is the query vector: 768 little-endian float32 values, 3,072 bytes, the format of a `VECTOR` column. It is the only value written into the SQL text. It is built from the validated floats and contains only `0-9a-f`; every filter value is a bound parameter. (We would bind the bytes too, but aiomysql cannot with the PyMySQL version we use.)
- MariaDB uses the vector index only when the `ORDER BY` is the bare `VEC_DISTANCE_*` call or its alias, with a `LIMIT`. `ORDER BY distance + 0` forces the full scan that gives the exact answer, which the evaluation uses as the reference.
- The old forms are still available, for the measurements below: `shape="join"` and `vector_format="text"` in `retrieve()`, `--shape` and `--vector-format` in `python -m src.evaluation`.

## The query vector: text or binary

Until 30 October the statement sent the vector as text, `VEC_FromText('[0.01234567,-0.5,...]')`. `ANALYZE` (the statement run, with the time measured inside MariaDB, [explain report](../../eval/results/20261030-195010_explain.md)) put almost all the time of a full scan outside reading the rows (`r_other_time_ms`): 644 of 683 ms with text, 9.6 of 13.1 ms with the binary literal. The two statements differ only in how the vector is written, so the time goes into `VEC_FromText`: MariaDB parses the 768 numbers again for every row it compares.

The whole question set, same state of the index, 3 timed passes (milliseconds, measured from Python):

| | Text | Binary |
| --- | --- | --- |
| Full scan, plain questions, mean | 607.7 | 24.4 |
| Index search with the join, plain, mean | 54.6 | 48.2 |
| Filtered questions, mean / p95 | 95.2 / 397.0 | 12.6 / 27.8 |
| "Linked from" questions, mean | 358.4 | 23.1 |

Both formats returned the same chunks for all 71 questions; the distances differ by at most 0.000001. Raw output: [text](../../eval/results/20261030-195106_text.md), [binary](../../eval/results/20261030-195151_binary.md), [exact text](../../eval/results/20261030-195501_exact-text.md), [exact binary](../../eval/results/20261030-195546_exact-binary.md).

The index search gains little: the index reads the query vector once, and the select list computes the distance only for the rows returned. Filtered searches and the full scan compute a distance for every candidate row, and they gain 7 to 25 times. The "linked from" filter was slow only for this reason: "Artificial intelligence" links to 141 of our 262 articles, 3,742 chunks, and each of them paid for parsing the vector.

## Statement shape: join or nearest chunks first

With the join in the same `SELECT`, `EXPLAIN` shows the vector index on `article_chunks` and then `articles` by primary key, as expected. But the search behaves as if the index were asked for far more than 10 rows. In the M sweep below, measured right after each build, the join returned exactly the exact top 10 for every `M` and every `mhnsw_ef_search`, and took longer as `M` grew. With the nearest chunks taken first, in a derived table with its own `LIMIT`, recall depends on `M` and `mhnsw_ef_search`, as for any HNSW index:

| M | Join: index recall, plain mean | Nearest first: index recall at ef 20 / 40 / 80 | Nearest first: plain mean |
| --- | --- | --- | --- |
| 8 | 1.000, 32 to 40 ms | 0.861 / 0.911 / 0.926 | 11 to 13 ms |
| 16 | 1.000, 49 to 53 ms | 0.911 / 0.948 / 0.972 | 15 to 22 ms |
| 32 | 1.000, 61 to 67 ms | 0.974 / 0.987 / 0.991 | 20 to 56 ms |

`EXPLAIN` for the nearest-first statement shows the vector index in the derived table (`DERIVED article_chunks index embedding`), then 10 primary-key lookups each into `article_chunks` and `articles`. For one random vector, `ANALYZE` measured 0.3 ms inside MariaDB for it and 39 ms for the join. Most of the 10 ms we measure from Python is the round trip through Docker Desktop and the driver.

We have not traced in the source where the join's limit comes from; MariaDB caps it at 10,000 candidates (`max_ef`). The join's exact results came at the cost of searching most of the graph, which a larger corpus would make slower and slower. The retriever uses the nearest-first shape for every search without a filter. Filtered searches keep the join, because there MariaDB starts from the filter.

## Choosing M and ef_search

`python -m src.evaluation m-sweep` drops and adds the index for each `M` and measures the 54 questions without a filter right after the build and after a restart. The table uses the measurements right after the build: they are what a restart gives once the graph statistics are right ([Vector Index State](./Index-State.md#cause-2-the-graph-tables-statistics-after-a-rebuild)). Index recall is for the nearest-first statement at `mhnsw_ef_search` 20 / 40 / 80; Recall@10 is the share of the 43 answerable plain questions with a chunk of the correct article in the top 10 (0.977 with the exact search).

| M | Build | Index recall@10 | Recall@10 | Plain mean |
| --- | --- | --- | --- | --- |
| 6 | 2.1 s | 0.819 / 0.865 / 0.904 | 0.930 / 0.930 / 0.977 | 11 to 12 ms* |
| 8 | 2.3 s | 0.861 / 0.911 / 0.926 | 0.930 / 0.977 / 0.977 | 11 to 13 ms |
| **16** | **5.5 s** | **0.911 / 0.948 / 0.972** | **0.954 / 0.977 / 0.977** | **15 to 22 ms** |
| 32 | 24.6 s | 0.974 / 0.987 / 0.991 | 0.977 / 0.977 / 0.977 | 20 to 56 ms |
| 48 | 56.6 s | 0.989 / 0.998 / 1.000 | 0.977 / 0.977 / 0.977 | 25 to 30 ms* |
| 64 | 134.8 s | 0.987 / 0.994 / 1.000 | 0.977 / 0.977 / 0.977 | 29 to 55 ms* |

\* From the first sweep, with the query vector as text, which adds a few milliseconds. Raw output: [first sweep, text](../../eval/results/20261030-201017_m-sweep.md), [second sweep, binary](../../eval/results/20261030-203723_m-sweep.md).

**Decision: `M=16` with `mhnsw_ef_search` 40.**

- From `mhnsw_ef_search` 40 on, `M=16` finds the correct article as often as the exact search (Recall@10 0.977) and returns 95% of the exact top 10.
- `M=32` returns 98.7% at the same setting, but takes 4.5 times as long to build (24.6 s against 5.5 s, for 6,144 chunks), and the correct article is not found more often. `M=48` and `64` take 10 and 25 times as long.
- `M=8` and MariaDB's default `M=6` build in about 2 s, but stay below 0.93 and 0.91 index recall even at `mhnsw_ef_search` 80, and `M=6` needs 80 to find the correct article as often.
- The build time matters because the ingest rebuilds the index after every re-ingest, and a live sync will make rebuilds regular.

After a restart, with the statistics refreshed, the shipped setting gave ([final sweep](../../eval/results/20261030-204644_final-ef-sweep.md)):

| `mhnsw_ef_search` | 10 | 20 | **40** | 80 | 160 |
| --- | --- | --- | --- | --- | --- |
| index recall@10, plain | 0.907 | 0.941 | **0.954** | 0.974 | 0.982 |
| plain mean | 10.7 ms | 10.3 ms | 11.0 ms | 11.1 ms | 10.7 ms |

The full scan took 19.3 ms per plain question in the same run. At 6,144 chunks the index saves less than half the time; the full scan grows with the number of chunks, the index search much more slowly.

## Filtered searches

A filtered search keeps the join, and MariaDB plans it from the filter. `EXPLAIN` on the real data ([explain report](../../eval/results/20261030-195010_explain.md)):

- **Category:** `article_categories` by its category index (28 articles), then `articles` and their chunks; distances computed for those chunks and sorted.
- **`article_length >= 50000`:** `articles` by the length index (about 115 articles by the optimizer's estimate), then their chunks.
- **Linked from:** the source article by its unique title (`const`), all 262 `articles` checked against `article_links` by its `linked_title` index, then the chunks of the 141 linked articles. The `EXISTS` was turned into a semi-join; the plan is fine, and the cost was the vector text (above).

The plans are the same whether the statement could use the vector index or not, so a filtered search is exact: its index recall is always 1.000. With the binary query vector every filter in the ground truth averaged 8 to 21 ms ([final run](../../eval/results/20261030-204715_final.md)).

A filter that keeps most of the table still gets the exact plan. On generated vectors, a filter that kept 70% of the chunks took 485 ms with the text vector (below); we have not repeated that with the binary vector.

## First experiments on generated vectors

Before the real embeddings were loaded, we measured on 17,338 chunks with generated vectors (dataset group centre plus article centre plus noise), 20 query vectors near stored chunks, timed inside the server, query vector as text. Scripts and raw output: [experiments/vector_filters](../../experiments/vector_filters/README.md).

| Situation | Plan | Result | Time |
| --- | --- | --- | --- |
| No filter, statistics stale after the bulk load | scan `articles`, read their chunks, sort everything | exact | 0.68 s |
| No filter, after `ANALYZE TABLE` | vector index on `article_chunks`, then the join | approximate | about 20 to 36 ms, depending on `M` |
| Selective filter (66 to 1,357 chunks) | the filter's index, the chunks of those articles, sort | exact | 3.7 to 54 ms |
| Weak filter (`article_length >= 50000`: 12,230 chunks, 70%) | the same exact plan | exact | 485 ms |
| The weak filter with chunks forced first (`STRAIGHT_JOIN`) | vector index, filter while reading | approximate | 18 to 36 ms |

| M | Index build | Chunks table alone | Retriever statement (join), no filter |
| --- | --- | --- | --- |
| 6 (default) | 3.8 s | 0.53, 0.8 ms | 0.74, 20.0 ms |
| 8 | 6.0 s | 0.72, 1.0 ms | 0.84, 23.9 ms |
| 16 | 11.9 s | 0.95, 0.7 ms | 1.00, 35.4 ms |

(recall against exact search, time; `mhnsw_ef_search` 20)

What still holds, and what changed:

- **Still holds:** run `ANALYZE TABLE` after a bulk load; selective filters get an exact filter-first plan; and "fetch the N nearest chunks, then filter" does not work for selective filters (it returned 0 to 2.8 of 10 rows, even with N = 1000).
- **Already visible here:** the chunks table alone took about 1 ms, the join 20 to 36 ms, and `mhnsw_ef_search` changed nothing for the join. We concluded then that the join "needs no change". On the real data the same pattern led to the nearest-first statement.
- **Changed:** we chose `M=16` here for the join's recall of 1.00, which was really the join searching most of the graph. The real-data sweep above chose `M=16` again, for other reasons. The cost per matching chunk of an exact plan (0.04 to 0.05 ms here) was most likely mostly the text vector.

## Method

- **Data:** 262 articles, 6,144 chunks of 256 tokens, `BAAI/bge-base-en-v1.5` vectors.
- **Questions:** the 71 ground-truth questions; the M sweep and the `mhnsw_ef_search` sweeps use the 54 without a filter.
- **Reference:** the exact answer of the same question, `ORDER BY distance + 0`, a full scan.
- **Timing:** from Python, around the statement alone (the question is embedded beforehand), one warm-up pass and 3 or 5 timed passes; `ANALYZE` for the time inside MariaDB.
- **Machine:** Windows 11 laptop, 12 logical CPUs, MariaDB 12.3.3 in Docker Desktop.
- **Commands:** `python -m src.evaluation m-sweep`, `ef-sweep`, `run` and `explain` ([Evaluation](../evaluation/Home.md)).

## Limits

- One machine, one data set and one version of MariaDB, sequential searches only. Concurrent searches and the memory of the index are not measured.
- The latency from Python includes about 10 ms of round trip that is not MariaDB's; differences of a few milliseconds between settings are within the noise of these runs.
- The M sweep measured "right after the build" for the table above. The state after a restart with refreshed statistics was measured for `M=16` only.
- The cause of the join's behaviour is not traced in the source.
