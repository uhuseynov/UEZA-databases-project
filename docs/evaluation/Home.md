# Evaluation

"It works well" has to be a number. The evaluation runs the ground-truth questions against the real MariaDB search and reports recall, latency and how well "not found" is detected.

```bash
make eval          # Recall@K, MRR, latency, not-found analysis (EVAL_RUNS=5)
make eval-exact    # the same with exact search (full scan, no vector index)
make eval-sweep    # index recall and latency for several mhnsw_ef_search values
make eval-explain  # EXPLAIN and ANALYZE for the search: index vs exact, with and without filters
uv run python -m src.evaluation m-sweep   # rebuild the index for several M values and measure each
```

Each run writes `eval/results/<timestamp>_<label>.json` (every number and every question) and a `.md` file with the tables for the README; `explain` writes a `.md` file only.

## Ground truth

`data/ground_truth.csv` (Zeynalabidin) has one row per question:

| Column | Example |
|---|---|
| `id` | `40` |
| `question` | `Among NLP articles shorter than 30000 characters, which one covers …` |
| `correct_article` | `Named-entity recognition` (several titles can be separated by `\|`) |
| `needs_filter` | `Y` |
| `filter_description` | `root_category = Natural language processing AND length < 30000` |
| `answerable` | `Y` |

`filter_description` is parsed into the same filters the API uses (`src/evaluation/ground_truth.py`), so a question is evaluated with exactly the SQL a reader would run:

| Clause | Filter |
|---|---|
| `category = X` | `category` |
| `root_category = X` | `root_category` |
| `linked_from = X` (a trailing note in parentheses is ignored) | `linked_from` |
| `length > n`, `>=`, `<`, `<=`, `=` | `min_length` / `max_length` (inclusive) |
| `last_edit < date`, `>=`, `>`, `<=`, `=` | `edited_since` (inclusive) / `edited_before` (exclusive) |

The current set has 71 questions: 43 plain, 17 with filters and 11 without an answer in the corpus. Of those 11, seven are off topic (football and tennis) and four are about AI but not answered by any of the articles; for each of the four, the key term was checked to have no match in `article_chunks`.

## Method

1. Every question is embedded once, before any timing, so the latency is the MariaDB search alone. The embedding time is reported separately.
2. One warm-up pass is run and discarded (cold buffer pool, first connection).
3. Every question is then searched `EVAL_RUNS` times, in the same order, with k = 10.
4. A question is a hit at k when one of its top k chunks belongs to its correct article. Recall is computed from the first timed run; the later runs add latency samples and are checked to return the same chunks.
5. If a question's search fails (for example a filter on a column that does not exist yet), the error is recorded and the question is left out of the metrics.

## Metrics

- **Recall@1, @3, @5, @10**: share of answerable questions with a hit at k, reported for all answerable questions, the plain ones and the filtered ones.
- **MRR**: mean of 1 / rank of the first correct chunk (0 when it is not in the top 10).
- **Latency**: mean, standard deviation, p50 and p95 over all searches, split into plain and filtered queries, plus the spread of the per-run averages (run-to-run variance).
- **Filtered queries with fewer than k results**: a selective filter combined with an approximate index can return fewer chunks than asked for. These questions are listed by id.
- **Not found**: the distance of the closest chunk for answerable and unanswerable questions, the result of the configured `RAG_MAX_DISTANCE` (share of answerable questions that keep their context, share of unanswerable ones that are rejected) and the threshold with the best balanced accuracy on this set.

## Index experiments

`make eval-sweep` first runs every question with exact search: the statement orders by `distance + 0`, which MariaDB cannot answer from the vector index, so it scans all chunks and returns the true nearest neighbours. Then it repeats the questions with the index for each `mhnsw_ef_search` value (default 10, 20, 40, 80, 160) and reports:

- **index recall@10**: the share of the exact top-10 chunks the index also returned, overall, for plain and for filtered queries;
- the task recall and MRR, and the latency (mean, p95, filtered mean).

This shows the cost of the approximation and where a larger `ef_search` stops paying off.

`M` is fixed when the index is created. `python -m src.evaluation m-sweep --m 6 8 16 32 48 64 --ef 20 40 80` drops and adds the index for each `M`, measures the questions without a filter right after the build and again after `docker compose restart db`, and finally puts the original `M` back. It computes the exact answers once and reports the build time, the index recall, Recall@1/@10, MRR and the latency for each `M`, state, statement shape and `ef_search`. `--no-restart` skips the restarts (for a database not run by Docker Compose). Filtered questions are left out, since a filtered search does not use the vector index.

`make eval-exact` gives the same report as `make eval` for the full scan, for a direct latency and recall comparison with the index.

`make eval-explain` prints and saves MariaDB's `EXPLAIN` for the search statement without a filter (both statement shapes), with a length filter, a category filter and a "linked from" filter, each in index and exact mode. Then it runs the slow cases under `ANALYZE FORMAT=JSON`, once with the query vector as text and once as binary, and lists the rows and the time each table took inside MariaDB. It uses a random vector, so it needs neither the embedding model nor the ground truth.

### Statement shape and query format

`run`, `ef-sweep` and `m-sweep` take `--shape join|nearest_first` and `--vector-format text|binary` (`m-sweep` takes `--shapes` with one or both). The defaults are what the application uses: the nearest chunks first and the binary vector. The other two exist to measure the difference ([Vector Search](../database/Vector-Search.md)).

## Comparing configurations

Change one thing at a time and give each run a label:

```bash
uv run python -m src.evaluation run --label chunks-256 --runs 5
uv run python -m src.evaluation run --label ef-80 --ef-search 80
```

Every report stores the MariaDB version, the number of articles and chunks, the embedding model, the vector index's `M` and distance, `mhnsw_ef_search`, `mhnsw_max_cache_size`, the git commit and the machine, so results from different runs and machines can be told apart. The state of the index matters as much as these settings ([Vector Index State](../database/Index-State.md)): measure after a restart, and after `make reindex` when articles were replaced.

## Known limits

- **Edit dates move.** Questions with `last_edit` filters assume the edit dates of the snapshot the ground truth was written against. After a re-ingest or a live sync, an article can move across the date, and the question has to be checked again.
- **Links.** Questions 49–51 (`linked_from`) use the links of the current article, while the text is the snapshot revision, so a link added or removed since the snapshot can change their answer.
- **Recall is chunk-based.** k counts chunks, not articles, because chunks are what the model receives. Two chunks of the same article both use up places in the top k.
