# Evaluation results

Every run of `python -m src.evaluation` (and `make eval` and its variants) and every `sync` writes its report here. Nothing is deleted: the intermediate runs are the evidence for how the index behaves in different states ([Vector Index State](../../docs/database/Index-State.md)), and the final ones are the numbers quoted in the [README](../../README.md) and in [Results](../../docs/evaluation/Results.md). The method is in [Evaluation](../../docs/evaluation/Home.md).

## File names

`<UTC date>-<UTC time>_<label>.json` and `.md`:

- the **JSON** file holds every number and every question's result;
- the **Markdown** file holds the tables of the same run;
- the **label** is what the person running it passed as `--label` (or the kind of run: `faiss`, `sync`, `answers`, `explain`).

`explain` runs have no JSON file, so there are 102 files for 50 runs and 2 query-plan reports. The undated `explain.md` is an earlier, shorter query-plan report from before the file names carried a timestamp; the dated one is the report the documentation cites.

Each report records its environment (MariaDB version, number of articles and chunks, embedding model, and from 30 October also the index's `M` and `mhnsw_max_cache_size`), so runs can be told apart. A `kind` field in the JSON says what produced it: `evaluation` (22 runs), `ef_search_sweep` (21), `m_sweep` (2), `faiss_baseline` (2), `sync` (2), `answers` (1).

## Which runs support which statement

### The reported results

| Run | Supports |
| --- | --- |
| [`20261030-204715_final`](./20261030-204715_final.md) | the retrieval and latency tables of the README and [Results](../../docs/evaluation/Results.md) (after a restart, 64 MB cache, nearest-first statement, binary vector) |
| [`20261030-204644_final-ef-sweep`](./20261030-204644_final-ef-sweep.md) | index recall and latency against `mhnsw_ef_search`; the choice of 40 |
| [`20261030-203723_m-sweep`](./20261030-203723_m-sweep.md) | the choice of `M=16` (second sweep, binary vector) |
| [`20261030-195010_explain`](./20261030-195010_explain.md) | the query plans, with and without filters, index and exact, text and binary |
| [`20261106-172053_faiss`](./20261106-172053_faiss.md) | the FAISS comparison ([FAISS Baseline](../../docs/database/FAISS-Baseline.md)) |
| [`20261106-172309_sync`](./20261106-172309_sync.md), [`20261106-161320_sync-dry-run`](./20261106-161320_sync-dry-run.md) | the live sync: 184 of 262 articles changed, 5 replaced |
| [`20261106-183004_answers`](./20261106-183004_answers.md) | the language model's answers and `NOT_FOUND` handling |

### How the index changed with its state (26 to 28 October)

These were taken with the statement and query format of that time (the join, the vector as text, `mhnsw_ef_search` 20, the default 16 MB cache). The first three runs are on 258 articles and 5,992 chunks; from `all262-…` on, the corpus is complete (262 articles, 6,144 chunks). The reports of this period do not record `M` or the cache size.

| Runs | State ([Index State, "The states of 28 October"](../../docs/database/Index-State.md#the-states-of-28-october)) | Plain search, mean |
| --- | --- | --- |
| `20261026-000612_default`, `20261028-154934_run-2`, `20261028-155403_ef-sweep` | first runs, before the corpus was complete | not part of the table |
| `20261028-172117_all262-run1`, `20261028-172154_all262-run2` | A: chunks replaced by a second `make ingest` | 70.1 and 69.5 ms |
| `20261028-173117_all262-optimized-run1`, `20261028-173156_all262-optimized-run2` | B: A, then `OPTIMIZE TABLE` | 71.9 and 70.2 ms |
| `20261028-173353_all262-reindexed` | C: B, then the index dropped and added again | 36.2 ms |
| `20261028-173442_all262-restarted`, `20261028-173930_all262-restarted-run2` | D: C, then the server restarted | 9.2 and 9.1 ms (the numbers the README showed until 28 October) |
| `20261028-174938_rewrite-before-restart` | E: D, then all chunks deleted and inserted again | 69.1 ms |
| `20261028-175032_rewrite-after-restart` | F: E, then the server restarted | 68.9 ms |
| `20261028-175947_rebuilt-after-rewrite` | the index rebuilt after F | 9.2 ms |
| `20261028-172536_ef-sweep`, `20261028-173907_ef-sweep`, `20261028-174225_ef-sweep` | `mhnsw_ef_search` sweeps taken between these steps | |

The plain-search means are read from the reports' latency tables. The assignment of the three late `ef-sweep` files to a state follows their time stamps and is not recorded in the documentation.

### Experiments of 30 October

| Runs | Experiment | Documented in |
| --- | --- | --- |
| `20261030-195106_text`, `…195151_binary`, `…195501_exact-text`, `…195546_exact-binary` | the query vector as text against binary, index and exact search: same chunks for all 71 questions | [Vector Search](../../docs/database/Vector-Search.md) |
| `20261030-201017_m-sweep` | first `M` sweep (vector as text); the second sweep is `…203723_m-sweep` above | [Vector Search](../../docs/database/Vector-Search.md) |
| `20261030-201351_replaced-16mb`, `…201429_replaced-64mb`, `…201517_replaced-16mb-again` | all chunks deleted and inserted again, 16 MB and 64 MB cache | [Index State, cause 1](../../docs/database/Index-State.md) |
| `20261030-201605_rebuilt-16mb`, `…201640_rebuilt-64mb` | the same, after rebuilding the index | [Index State, cause 1](../../docs/database/Index-State.md) |
| `20261030-202650_stats-as-is-join` and `…-nearest_first`; `…202905_stats-corrected-…`; `…203042_stats-restored-…` | the graph table's row-count statistic as it was, set to the real count, and set back; both statement shapes | [Index State, cause 2](../../docs/database/Index-State.md) |

### Experiments of 6 November

| Runs | Experiment | Documented in |
| --- | --- | --- |
| `20261106-161313_faiss` | the first FAISS run, right after the integration tests rebuilt the index (no restart); the dated `…172053_faiss` is the one reported | [FAISS Baseline](../../docs/database/FAISS-Baseline.md) |
| `20261106-1620…` to `20261106-1626…`, labelled `partial-<0\|10\|25\|50\|100>pct-<64mb\|16mb>` | replacing 0, 10, 25, 50 and 100% of the chunks, at 64 MB and 16 MB cache | [Index State, replacing part of the chunks](../../docs/database/Index-State.md#replacing-part-of-the-chunks) |

## Reproducing a run

Each report records the settings it was taken with and, when git was available, the commit. To repeat one, load the corpus (`make ingest`), restart the database so the index is in the state a running service is in, and run the command that produced it, for example `make eval` or `uv run python -m src.evaluation ef-sweep`; the options are listed in [Evaluation](../../docs/evaluation/Home.md). The scripts behind the `replaced-`, `rebuilt-`, `stats-` and `partial-` runs are in [experiments/index_cache](../../experiments/index_cache/README.md); the other runs come straight from the commands in [Evaluation](../../docs/evaluation/Home.md).
