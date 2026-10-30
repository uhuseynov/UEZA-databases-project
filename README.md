A project for area 4, "Vector search and RAG, natively" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

# UEZA: Wikipedia question answering inside MariaDB

UEZA answers questions about 262 English Wikipedia articles on artificial intelligence. The article text, its metadata and the embedding vectors all live in MariaDB 12.3.3: the chunks sit in a `VECTOR(768)` column with an HNSW `VECTOR INDEX`, and one SQL statement finds the closest chunks and applies the filters at the same time. A language model then answers from those chunks and names its sources, or says that the answer is not in the articles.

**Main results** (details in [Results](#results)):

- The right article is among the 10 closest chunks for 95% of the 60 answerable test questions, and in first place for 62%: the same as an exact search over every chunk.
- A search takes 8 ms on average without a filter and 12 ms with one (p95 12 and 24 ms), measured from Python against MariaDB in Docker. The vector index returns 95% of the exact 10 nearest chunks.
- Three things about MariaDB's vector search made it up to 25 times faster or more accurate on our data, each tested by changing that one thing ([What we learned](#what-we-learned-about-the-vector-index)): sending the query vector as binary instead of text, taking the nearest chunks before the join, and keeping the index's cache and statistics right.
- `M=16` with `mhnsw_ef_search` 40: `M=32` returns 4 more of every 100 exact neighbours but takes 4.5 times as long to build, and does not find the right article more often ([M sweep](./docs/database/Vector-Search.md#choosing-m-and-ef_search)).
- A distance threshold rejects every off-topic question before the language model is called, but not questions that are close to the topic and still not answered by the articles.

## Quick start

You need Docker with Compose, `make` and [uv](https://docs.astral.sh/uv/). uv installs Python 3.14 by itself. The database is the `mariadb:12.3.3` image from `docker-compose.yml`, the version everything here was developed and measured with.

```bash
make quickstart
```

That one command copies `.env.example` to `.env`, installs the Python environment, starts MariaDB (`schema.sql` runs on the first start), loads 3 articles and starts the web app. The first run also downloads the embedding model, about 440 MB. The same steps one by one: `make setup`, `make db-up`, `make ingest-test`, `make run`.

Open <http://localhost:8000>, type a question and press **Search only**. The page shows the closest chunks with their cosine distance and needs no language model. The same search is available as `GET /search?q=...`.

**Ask** (`POST /ask`) also writes an answer, and needs an OpenAI-compatible language model. It can be a free local one, for example [Ollama](https://ollama.com) after `ollama pull qwen2.5:3b`, with these lines in `.env`:

```
LLM_API_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:3b
LLM_API_KEY=ollama
```

The whole corpus and the evaluation:

```bash
make ingest            # all 262 articles; about an hour on our laptop CPU
make ingest-check      # every article present, chunks complete, no orphan rows
make eval              # Recall@K, MRR, latency, not-found analysis
make reindex           # rebuild the vector index; make ingest does it after replacing articles
```

`docker-compose.yml` starts MariaDB with two vector settings, `mhnsw_ef_search=40` and a 64 MB index cache. If your database container was created before they were added, `docker compose up -d --wait db` recreates it with them; the data stays in its volume.

If port 3306 is already taken, for example by a MariaDB installed on the machine, set `MARIADB_PORT=3307` in `.env`. On Windows without `make`, run the commands behind each target in the [Makefile](./Makefile); [Ingestion](./docs/ingestion/Home.md) lists the ingest command and its options.

## One search, one statement

A question without a filter becomes this statement ([src/rag/retriever.py](./src/rag/retriever.py)):

```sql
SELECT c.id, a.title, c.chunk_text, n.distance
FROM (SELECT id, VEC_DISTANCE_COSINE(embedding, X'3a1f...') AS distance
      FROM article_chunks ORDER BY distance LIMIT 10) n
JOIN article_chunks c ON c.id = n.id
JOIN articles a ON a.id = c.article_id
ORDER BY n.distance;
```

The derived table gives the vector index its own `LIMIT 10`. `X'...'` is the query vector itself, 768 float32 values in the binary format of a `VECTOR` column; every filter value is a bound parameter. A question with filters keeps them in one `WHERE`:

```sql
SELECT c.id, a.title, c.chunk_text,
       VEC_DISTANCE_COSINE(c.embedding, X'3a1f...') AS distance
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE a.root_category = 'Reinforcement learning'
ORDER BY distance
LIMIT 10;
```

The other filters are ordinary SQL in the same `WHERE`: article length, edit date, a category (`EXISTS` on `article_categories`) and "linked from article X" (`EXISTS` on `article_links`). The `ORDER BY` has to be the bare distance or its alias, or MariaDB does not use the vector index. We use that on purpose: `ORDER BY distance + 0` gives the exact nearest neighbours by a full scan, which is the baseline for the index recall.

## Results

Measured on 30 October 2026 on our laptop (Windows 11, 12 logical CPUs, Docker Desktop) with MariaDB 12.3.3, the embedding model `BAAI/bge-base-en-v1.5` (768 dimensions), chunks of 256 tokens with 32 tokens overlap, `M=16`, `mhnsw_ef_search` 40 and a 64 MB index cache. The corpus is all 262 articles, 6,144 chunks. The questions are [data/ground_truth.csv](./data/ground_truth.csv): 71 questions, 43 plain, 17 with SQL filters and 11 whose answer is not in the articles. The run embeds all questions first, discards one warm-up pass and then times 5 passes. It was taken after a restart of the database, the state a running service is in.

Raw output: the [run](./eval/results/20261030-204715_final.md), the [`mhnsw_ef_search` sweep](./eval/results/20261030-204644_final-ef-sweep.md), the [M sweep](./eval/results/20261030-203723_m-sweep.md) and the [query plans](./eval/results/20261030-195010_explain.md), with a JSON file next to each run that holds every question.

### Retrieval quality

Recall@k is the share of answerable questions where a chunk of a correct article is among the k closest chunks. MRR is the mean of 1 / rank of the first correct chunk.

| Questions | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| all answerable | 60 | 0.617 | 0.800 | 0.867 | 0.950 | 0.733 |
| plain | 43 | 0.605 | 0.837 | 0.907 | 0.977 | 0.744 |
| with filters | 17 | 0.647 | 0.706 | 0.765 | 0.882 | 0.703 |

These are exactly the numbers of the exact search over every chunk ([full scan](./eval/results/20261030-195546_exact-binary.md)): the 5% of nearest chunks the index misses did not cost a correct article. Three questions miss at k = 10. Two of them are filtered (the ImageNet question behind "linked from Convolutional neural network" and the PCA question behind "Machine learning, longer than 100,000 characters"); for the third, the chunks of "Large language model" outrank the article "Hallucination (artificial intelligence)". When the right article is not first, the first result is usually a closely related article: SARSA for the Q-learning question, "Google DeepMind" for AlphaGo, "Decision tree learning" for the random forest question and "Cluster analysis" for k-means.

### Latency

Time of the MariaDB statement alone, in milliseconds, measured from Python (the question is embedded beforehand: 35 ms per question, in one batch).

| Questions | searches | mean | p50 | p95 |
| --- | --- | --- | --- | --- |
| plain | 270 | 8.4 | 7.4 | 11.7 |
| with filters | 85 | 11.8 | 9.6 | 24.4 |
| all | 355 | 9.2 | 7.7 | 19.6 |

The five timed passes averaged 8.5, 10.2, 8.6, 9.3 and 9.3 ms. The exact full scan took 19.3 ms per plain question. Inside MariaDB a plain search takes well under a millisecond (0.3 ms for one search under `ANALYZE`); most of the 8 ms is the round trip through the driver and Docker Desktop.

A filtered search never uses the vector index: MariaDB reads the chunks of the matching articles and computes every distance, so it is exact. Every filter in the ground truth averaged 8 to 21 ms; the slowest is "linked from Artificial intelligence", which covers 141 of the 262 articles.

The same questions on 28 October, before the changes described below, took 9.2 ms without a filter, but the index then returned only 92 to 94% of the exact top 10, and 68 ms with filters (p95 280 ms, "linked from" up to 297 ms).

### Not found

The distance of the closest chunk is 0.298 on average for the answerable questions (highest 0.461) and 0.438 for the unanswerable ones (lowest 0.309). With `RAG_MAX_DISTANCE=0.42`, 97% of the answerable questions keep their context and 8 of the 11 unanswerable ones are rejected before the language model is called. All seven football and tennis questions are rejected (0.437 to 0.536), and so is the AIBO question (0.439). Three questions about AI whose answer is not in the articles pass: Leela Chess Zero (0.309, closest article AlphaGo), PROSPECTOR (0.357, Expert system) and Xiaoice (0.389, History of artificial intelligence).

So the threshold filters out questions that are off topic, not questions that are close to the corpus. A lower threshold does not fix that: 0.356 rejects 10 of the 11, but it also takes the context away from 12% of the answerable questions. Those questions are left to the second check, the model answering `NOT_FOUND` when the passages do not contain the answer.

## What we learned about the vector index

- **Send the query vector as binary.** MariaDB evaluates `VEC_FromText('[0.0123,...]')` again for every row it compares. Written as a hex literal of the vector's binary value, the same search returned the same chunks for all 71 questions, and the full scan went from 608 to 24 ms, filtered searches from 95 to 12.6 ms on average, and the "linked from" filter from 358 to 23 ms. That filter's plan was fine all along; it covers 3,742 chunks, and each paid for parsing the text. ([Vector Search](./docs/database/Vector-Search.md#the-query-vector-text-or-binary))
- **Take the nearest chunks first, then join.** With `articles` joined in the same `SELECT`, the index returned the exact top 10 for every `M`, ignored `mhnsw_ef_search` and took 32 to 67 ms: it searched far more of the graph than the 10 rows needed. With the 10 nearest chunks taken from `article_chunks` alone in a derived table, recall follows `M` and `mhnsw_ef_search`, as for any HNSW index, and the search takes 0.3 ms inside MariaDB. ([Statement shape](./docs/database/Vector-Search.md#statement-shape-join-or-nearest-chunks-first))
- **`M=16`, `mhnsw_ef_search` 40, chosen on the real embeddings.** From `M` 6 to 64, the index recall at `mhnsw_ef_search` 40 rose from 0.87 to 0.99 and the build time from 2 s to 135 s. `M=16` finds the right article as often as the exact search, with 95% of the exact top 10, and builds in 5.5 s; the ingest rebuilds the index after every re-ingest, so build time counts. ([M sweep](./docs/database/Vector-Search.md#choosing-m-and-ef_search))
- **The index cache has to hold the deleted vectors too.** A deleted chunk stays in the HNSW graph until the index is rebuilt. After all chunks were replaced, a search took 72 ms with MariaDB's default 16 MB index cache, 20 ms with 64 MB and 72 ms again at 16 MB: the graph, deleted nodes included, no longer fit, and MariaDB drops the whole cache after a search that leaves it too large. We run MariaDB with 64 MB and rebuild the index after a re-ingest. ([Vector Index State](./docs/database/Index-State.md#cause-1-deleted-vectors-and-the-index-cache))
- **After a rebuild, InnoDB thinks the graph is empty.** `ALTER TABLE ... ADD VECTOR INDEX` leaves the hidden graph table with the statistics of an empty table, and after a restart MariaDB sizes every search by them: index recall stayed around 0.9 for every `M` and `mhnsw_ef_search`. Setting the row count right, and nothing else, gave 0.93 to 1.00; setting it back to 0 lost it again. `make reindex` now inserts and deletes one chunk, which makes InnoDB count the table. This was the cause of the "92 to 94%" in our earlier results. ([Vector Index State](./docs/database/Index-State.md#cause-2-the-graph-tables-statistics-after-a-rebuild))
- **With a filter, the vector index is not used.** MariaDB starts from the filter's index, reads the chunks of the matching articles and sorts them by distance, so filtered searches are exact. Right after a bulk load the statistics were stale and MariaDB scanned every chunk even without a filter; the ingest runs `ANALYZE TABLE` at the end.

## Why MariaDB and not a separate vector store

- **Filters and the vector search are one statement.** With a filter, MariaDB starts from the filter's index and the answer is exact. The usual alternative, "fetch the N nearest chunks, then filter", returned only 0 to 2.8 of 10 rows in our generated-vector experiment when the filter was selective and the question was about other articles, even with N = 1000.
- **Joins with the rest of the data.** "Linked from article X" is a join over the links table. A separate vector store would need the links copied into its metadata and kept in sync.
- **One transaction per article.** The ingest replaces an article's metadata, categories, links, chunks and vectors in one transaction ([src/database/repositories/articles.py](./src/database/repositories/articles.py)), so there is no second system to update and no window in which the two disagree.
- **One system** to run, back up and secure.

## Where this approach loses

- **The index needs looking after.** Deleted vectors stay in the graph until a rebuild, the default cache is too small for that, and a rebuild leaves the graph table's statistics wrong. We work around all three (64 MB cache, rebuild after a re-ingest, a statistics refresh after the rebuild), but each one first showed up as a puzzling measurement.
- **Small details decide the speed.** Writing the vector as text made searches up to 25 times slower, and the join in the same `SELECT` made the index search most of the graph. Neither is visible in `EXPLAIN`.
- **The query vector is part of the SQL text.** aiomysql cannot send bytes as a parameter with the PyMySQL version we use, so the 3,072 bytes of the vector are written into the statement as a hex literal. It is built from validated floats only, but it is 6 KB of SQL per search.
- **Rebuilds get slow with larger `M`:** 25 s at `M=32` and 135 s at `M=64` for 6,144 chunks.
- **Weak filters scan.** The optimizer chooses the exact plan even when the filter keeps most of the table. At 6,144 chunks that costs at most about as much as a full scan (19 to 24 ms); it grows with the corpus.
- **One vector index per table, tied to one dimension.** Comparing a 384-dimensional model needs a second table.
- **Not measured yet:** the comparison with FAISS on the same vectors, concurrent searches and the memory of the index.

## Data model

Four tables, created by [schema.sql](./schema.sql):

- `articles`: one row per article, with the metadata we filter on (`root_category`, `article_length`, `last_edit_date`) and the `revision_id` the sync compares.
- `article_categories`: one row per article and category.
- `article_links`: one row per article and outgoing link, stored as the linked title.
- `article_chunks`: the text chunks and their vectors:

```sql
CREATE TABLE article_chunks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    article_id  INT NOT NULL,
    chunk_index INT NOT NULL,                         -- position in the article, from 0
    chunk_text  TEXT NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    UNIQUE KEY uq_chunks_position (article_id, chunk_index),
    CONSTRAINT fk_chunks_article FOREIGN KEY (article_id) REFERENCES articles(id),
    VECTOR INDEX (embedding) M=16 DISTANCE=cosine
);
```

**Why it's built this way:**

- An article has many categories, so they get their own table. Filtering by category is an `EXISTS` check, and an article never appears twice in the results.
- `root_category` is the dataset group an article was collected from, such as "Deep learning". MediaWiki doesn't know it, so the loader copies it from `data/articles.csv`.
- Links are stored as titles, because most of them point outside our dataset. "Linked from article X" is then a join on `articles.title`, and it works whatever order the articles are loaded in.
- Titles are compared case-sensitively (`utf8mb4_bin`), because Wikipedia treats `AI` and `Ai` as different articles.
- `embedding` is `NOT NULL` because MariaDB only allows a vector index on a column that cannot be empty.
- The index uses `DISTANCE=cosine`. The default is euclidean, and a search with `VEC_DISTANCE_COSINE` cannot use a euclidean index.
- `article_chunks` is only ever the child side of a foreign key. MariaDB has an open bug (MDEV-35241) about dropping a table with a vector index when other tables reference it.

Where each column comes from is listed in [Database](./docs/database/Home.md).

## How it was built

```text
data/articles.csv ──► MediaWiki API ──► clean wikitext ──► 256-token chunks ──► bge-base embeddings
                      (revision at the CSV date)                                        │
                                                                                         ▼
question ──► embedding ──► one SQL statement: vector distance + filters ──► MariaDB 12.3.3
                                                                                         │
                                answer with [1] citations, or "not found" ◄── language model
```

- [Data decisions](./docs/data_decisions.md): topic, the 262 articles, cleaning and chunking rules
- [Ingestion](./docs/ingestion/Home.md): MediaWiki client, cache, rate limiting
- [Vector search and index parameters](./docs/database/Vector-Search.md): the index experiments
- [Retrieval and RAG](./docs/rag/Home.md): the search statement, the prompt and the not-found logic
- [Evaluation](./docs/evaluation/Home.md): ground truth, metrics and method
- [All documentation](./docs/Home.md): architecture, Docker, CI and the Git workflow

## Status

Done: schema and vector index, ingest of a fixed snapshot, hybrid search, the question-answering API and page, evaluation, and the index tuning on the real embeddings (query format, statement shape, `M` and `mhnsw_ef_search`, cache size, graph statistics).

Next:

- live sync with Wikipedia, and how fast the index slows down when only some chunks are replaced
- the FAISS baseline on the same vectors
- chunk sizes and embedding models compared on the same questions
- measuring how often the language model answers `NOT_FOUND` for the unanswerable questions
- reporting the two index behaviours (graph statistics after a rebuild, the whole-cache reset) to MariaDB

## Team

- **Aaryadeep**: database schema, vector column and index, similarity search and filtered SQL queries
- **Zeynalabidin**: data decisions (topic, article list, metadata, cleaning and chunking rules) and the ground-truth question set
- **Egehan**: ingestion and live sync (MediaWiki client, chunking, embeddings, loading into MariaDB), the FAISS comparison baseline, the Docker Compose stack and CI
- **Umid** (team lead): repo structure, RAG pipeline and backend, evaluation, final integration
