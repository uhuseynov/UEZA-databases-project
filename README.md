A project for area 4, "Vector search and RAG, natively" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

# UEZA: Wikipedia question answering inside MariaDB

UEZA answers questions about 262 English Wikipedia articles on artificial intelligence. The article text, its metadata and the embedding vectors all live in MariaDB 12.3.3: the chunks sit in a `VECTOR(768)` column with an HNSW `VECTOR INDEX`, and one SQL statement finds the closest chunks and applies the filters at the same time. A language model then answers from those chunks and names its sources, or says that the answer is not in the articles.

**Main results** (details in [Results](#results)):

- The right article is among the 10 closest chunks for 95% of the 60 answerable test questions, and in first place for 65%.
- A search without filters takes 35 to 52 ms in MariaDB (two runs on the same laptop). The vector index returns the same 10 chunks as an exact full scan for every test question, and is about 10 times faster.
- Selective filters make the search faster (median 20 to 28 ms); the "linked from" filter makes it slower (184 to 339 ms).
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
```

If port 3306 is already taken, for example by a MariaDB installed on the machine, set `MARIADB_PORT=3307` in `.env`. On Windows without `make`, run the commands behind each target in the [Makefile](./Makefile); [Ingestion](./docs/ingestion/Home.md) lists the ingest command and its options.

## One search, one statement

This is the statement `src/rag/retriever.py` sends for every question, here with one filter:

```sql
SELECT c.id, a.title, c.chunk_text,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText(:query_vector)) AS distance
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE a.root_category = 'Reinforcement learning'
ORDER BY distance
LIMIT 10;
```

The other filters are ordinary SQL in the same `WHERE`: article length, edit date, a category (`EXISTS` on `article_categories`) and "linked from article X" (`EXISTS` on `article_links`). The `ORDER BY` has to be the bare distance or its alias, or MariaDB does not use the vector index. We use that on purpose: `ORDER BY distance + 0` gives the exact nearest neighbours by a full scan, which is the baseline for the index recall.

## Results

Measured twice on the same laptop (Windows 11, 12 logical CPUs, Docker Desktop), on 26 and 28 October 2026, with MariaDB 12.3.3, the embedding model `BAAI/bge-base-en-v1.5` (768 dimensions), chunks of 256 tokens with 32 tokens overlap, `M=16` and `mhnsw_ef_search` 20. The corpus is 258 of the 262 articles, 5,992 chunks: four articles failed to ingest because the cleaner took `{|` inside a math formula for a table, which is fixed now, and the measurements will be repeated on all 262. The questions are [data/ground_truth.csv](./data/ground_truth.csv): 71 questions, 43 plain, 17 with SQL filters and 11 whose answer is not in the articles. Each run embeds all questions first, discards one warm-up pass and then times 3 passes.

### Retrieval quality

Recall@k is the share of answerable questions where a chunk of a correct article is among the k closest chunks. MRR is the mean of 1 / rank of the first correct chunk.

| Questions | n | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| all answerable | 60 | 0.650 | 0.800 | 0.867 | 0.950 | 0.750 |
| plain | 43 | 0.651 | 0.837 | 0.907 | 0.977 | 0.768 |
| with filters | 17 | 0.647 | 0.706 | 0.765 | 0.882 | 0.703 |

Both runs returned exactly these numbers. Three questions miss at k = 10. Two of them are filtered (the ImageNet question behind "linked from Convolutional neural network" and the PCA question behind "Machine learning, longer than 100,000 characters"); for the third, the chunks of "Large language model" outrank the article "Hallucination (artificial intelligence)". When the right article is not first, the first result is usually a closely related article: SARSA for the Q-learning question, "Google DeepMind" for AlphaGo.

### Latency

Time of the MariaDB statement alone, in milliseconds. Embedding the questions is measured separately (25 and 44 ms per question in the two runs, embedded in one batch).

| Run | plain: mean | p50 | p95 | with filters: mean | p50 | p95 | mean of each timed pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 (26 Oct) | 35.2 | 34.2 | 43.7 | 63.0 | 19.9 | 265.4 | 42.0, 42.3, 41.3 |
| 2 (28 Oct) | 51.6 | 47.5 | 75.5 | 82.4 | 27.5 | 317.4 | 50.4, 71.1, 55.5 |

Each run has 162 plain and 51 filtered searches. The second run was 40 to 50% slower and much less steady from pass to pass, on the same machine, data and questions: a laptop is not a controlled machine, so read the absolute numbers as an order of magnitude and compare settings within one run.

A selective filter makes the search faster, because MariaDB then answers it exactly from the few matching chunks (see the next section). The slow tail is the "linked from" filter alone: 184 to 283 ms per search in run 1 and 210 to 339 ms in run 2, against at most 57 and 89 ms for every other filter.

### Not found

The distance of the closest chunk is 0.298 on average for the answerable questions (highest 0.461) and 0.431 for the unanswerable ones (lowest 0.309). With `RAG_MAX_DISTANCE=0.42`, 97% of the answerable questions keep their context and 8 of the 11 unanswerable ones are rejected before the language model is called. All seven football and tennis questions are rejected (0.437 to 0.493). Three questions about AI whose answer is not in the articles pass: Leela Chess Zero (0.309, closest article AlphaGo), PROSPECTOR (0.357, Expert system) and Xiaoice (0.389, History of artificial intelligence).

So the threshold filters out questions that are off topic, not questions that are close to the corpus. A lower threshold does not fix that: 0.356 rejects 10 of the 11, but it also takes the context away from 12% of the answerable questions. Those questions are left to the second check, the model answering `NOT_FOUND` when the passages do not contain the answer.

## What we learned about the vector index

- **On our real embeddings the index costs no accuracy.** `make eval-sweep` compares the index with the exact full scan (`ORDER BY distance + 0`) for all 71 questions. The index returned the same 10 chunks as the full scan for every question at `mhnsw_ef_search` 10, 20, 40 and 80, and one different chunk out of 710 at 160. Recall@10 against the ground truth stays 0.950 at every setting. A plain search took 50 to 59 ms with the index against 516 ms for the full scan, about 10 times faster, and `mhnsw_ef_search` did not change the time either, so the default of 20 stays.
- **With a filter, the vector index is not used at all.** `EXPLAIN` on the real data (`make eval-explain`) shows `key = embedding` only for the search without a filter. With a category filter, or with `article_length >= 50000` (about 111 of the 258 articles by the optimizer's estimate), MariaDB starts from the filter's index, reads the chunks of the matching articles and sorts them by distance, and the plan is the same whether the statement could use the vector index or not. So filtered searches are exact: their index recall is always 1.000, and no filtered question returned fewer than 10 rows. On 17,338 generated chunks, the same plan for a filter that kept 70% of the chunks took 485 ms.
- **Run `ANALYZE TABLE` after a bulk load.** Right after loading, the statistics were stale and MariaDB scanned all chunks instead of using the vector index: 0.68 s for 17,338 chunks, against 20 to 36 ms with fresh statistics (generated vectors, [experiment](./docs/database/Vector-Search.md)). The ingest runs `ANALYZE TABLE` at the end.
- **`M` matters more than `mhnsw_ef_search`.** On generated vectors, recall against exact search rose from 0.74 (M=6, MariaDB's default) to 1.00 (M=16), and the build time from 3.8 s to 11.9 s; `mhnsw_ef_search` from 10 to 160 changed nothing for the statement with the join. We ship `M=16`: on the real embeddings it already matches the exact search at the default `mhnsw_ef_search`, and the slower build only matters when the whole index is rebuilt. Whether a smaller `M` does as well on the real embeddings is the next experiment.

## Why MariaDB and not a separate vector store

- **Filters and the vector search are one statement.** The optimizer decides between the vector index and the filter's index. The usual alternative, "fetch the N nearest chunks, then filter", returned only 0 to 2.8 of 10 rows in our generated-vector experiment when the filter was selective and the question was about other articles, even with N = 1000.
- **Joins with the rest of the data.** "Linked from article X" is a join over the links table. A separate vector store would need the links copied into its metadata and kept in sync.
- **One transaction per article.** The ingest replaces an article's metadata, categories, links, chunks and vectors in one transaction ([src/database/repositories/articles.py](./src/database/repositories/articles.py)), so there is no second system to update and no window in which the two disagree.
- **One system** to run, back up and secure.

## Where this approach loses

- **The join costs time.** The same nearest-neighbour search on the chunks table alone took about 1 ms; with the join to `articles` it took 20 to 36 ms (generated vectors). On the real data a plain search takes 35 to 52 ms. A store that only returns the nearest vectors does not pay this.
- **"Linked from" is slow:** 184 to 339 ms per search, several times the other filters. We have not analysed its plan yet.
- **Weak filters scan.** The optimizer chooses the exact plan even when the filter keeps most of the table (485 ms above).
- **Statistics have to be refreshed by hand** after bulk loads, or the index is not used.
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

Done: schema and vector index, ingest of a fixed snapshot, hybrid search, the question-answering API and page, evaluation.

Next:

- repeat the measurements on all 262 articles
- live sync with Wikipedia
- the FAISS baseline on the same vectors
- smaller `M` values on the real embeddings (build time against recall)
- chunk sizes and embedding models compared on the same questions
- measuring how often the language model answers `NOT_FOUND` for the unanswerable questions

## Team

- **Aaryadeep**: database schema, vector column and index, similarity search and filtered SQL queries
- **Zeynalabidin**: data decisions (topic, article list, metadata, cleaning and chunking rules) and the ground-truth question set
- **Egehan**: ingestion and live sync (MediaWiki client, chunking, embeddings, loading into MariaDB), the FAISS comparison baseline, the Docker Compose stack and CI
- **Umid** (team lead): repo structure, RAG pipeline and backend, evaluation, final integration
