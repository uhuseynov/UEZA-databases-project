# Scripts and Experiments

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

Everything that is neither the application nor a test: helper scripts, the script that built the article list, and the experiment scripts behind the index measurements.

## Helper scripts (`scripts/`, `.githooks/`)

| File | Run by | Does |
| --- | --- | --- |
| `scripts/entrypoint.sh` | the Docker image (`ENTRYPOINT`) | waits until MariaDB accepts connections (up to 60 s), hands `/app/.cache` to the application user if an older root-run container left it root-owned, drops root, and starts the container's command (`uvicorn`) as `ueza` ([Docker and Compose](./Docker.md#container-user)). It does not touch the schema ([Schema Management](../database/Schema.md)). |
| `scripts/setup-hooks.sh` | `make hooks`, `make setup` | sets `core.hooksPath` to `.githooks` and makes the hooks executable |
| `.githooks/commit-msg` | Git | validates the Conventional Commit subject ([Git Hooks](./Git-Hooks.md)) |
| `.githooks/pre-push` | Git | runs the unit tests before a push |

## Building the article list: `data/build_article_list.py`

The script that produced the committed `data/articles.csv` (selection rules: [Data decisions](../data_decisions.md#selection-262-articles)). It reads six root categories and one level of subcategories from English Wikipedia, drops list pages and the hand-removed off-topic articles (the `REMOVE` list), caps each root, adds the hand-picked core articles, and writes a CSV with the columns `title, pageid, length, last_edit, root_category, category`.

### The committed snapshot and generated lists

| | `data/articles.csv` | `data/articles.generated.csv` |
| --- | --- | --- |
| What it is | the research snapshot: 262 articles whose `last_edit` dates the ingest, the ground-truth questions and every measured result rely on | a new candidate list from a fresh run |
| Written by | nobody: the script refuses to, whatever the options | the script, on request |
| In Git | committed | ignored (`.gitignore`), so a run cannot be committed by accident |

A fresh run reads the *current* category members, article lengths and edit times, so it gives a different list and different `last_edit` dates than the snapshot. The dates matter: the ingest loads each article at its revision on that date, and several evaluation questions filter on edit dates. That is why a generated list is only ever a candidate.

### Running it

```bash
uv run python -m data.build_article_list                       # -> data/articles.generated.csv
uv run python -m data.build_article_list --output my_list.csv  # another file
uv run python -m data.build_article_list --overwrite           # replace an earlier generated file
uv run python -m data.build_article_list --help
```

(`-m`, from the repository root, so that it shares the application's settings.) It sends one request per category it reads and one per 50 article titles, pausing 0.2 s between requests.

Safety rules, all covered by tests with a mocked MediaWiki:

- **The default output is a separate file**, `data/articles.generated.csv`.
- **An existing output file is never replaced unless `--overwrite` is given.** Without it the script stops before sending a request (exit code 2).
- **`data/articles.csv` is never written, with or without `--overwrite`**, and there is no flag for it. The check recognises the file under any spelling of its path: relative, with `..`, through a symbolic link, or a hard link. Replacing the snapshot is a deliberate research decision, described below, not something a script option should do.
- **No half-written output.** All requests finish first; the CSV is then written to a temporary file in the same directory and moved into place (exit code 1 and no file if any request fails, and an existing file is left as it was). Without `--overwrite` the final step refuses to replace a file that appeared in the meantime.
- **Requests use the project's conventions:** `httpx`, the user agent from `MEDIAWIKI_USER_AGENT` ([Configuration](../architecture/Configuration.md)), the timeout from `MEDIAWIKI_TIMEOUT`, and a clear error for HTTP errors, timeouts, API errors and malformed answers.
- **Importing the module does nothing**: no request, no file.

The selection itself (roots, minimum length 3000, cap of 50 per root and 25 for Computer vision, the `REMOVE` and `CORE` lists, the order of the rows, the CSV columns and the latest-revision timestamp as `last_edit`) is unchanged. A test pins the definition by a digest of the original script's rules, and the new code was compared with the original on 20 generated, mocked worlds: the output was identical in every case.

### What a run does not reproduce

- Wikipedia changes: categories gain and lose members, articles grow, so two runs on different days differ, and neither equals the snapshot.
- Like the original, it takes the first 500 members of each category (no continuation) and only one level of subcategories. This is kept on purpose: it is part of how the committed list was defined.
- There are no retries: a transient failure stops the run, and nothing is written. Run it again.

### Safe regeneration

1. Run the script. It writes `data/articles.generated.csv` and leaves the snapshot alone.
2. Compare: `diff data/articles.csv data/articles.generated.csv`.
3. Use the generated file for experiments with `--csv data/articles.generated.csv` (for example `uv run python -m src.ingestion ingest --csv data/articles.generated.csv --limit 3`) against a *disposable* database, never the one with the research data.
4. Only if you intend to start a new research snapshot: replace `data/articles.csv` by hand (`cp`), then re-ingest into a fresh database, review the ground-truth questions (titles, `correct_article`, edit-date filters, "linked from" questions), and re-run the evaluation. Results measured on the earlier snapshot are not comparable with the new ones.

## Experiments (`experiments/`)

Scripts behind the measurements in [Vector Search](../database/Vector-Search.md) and [Vector Index State](../database/Index-State.md). They are run by hand and are not part of the tests or CI.

| Directory | What it measures | Needs |
| --- | --- | --- |
| [`experiments/vector_filters/`](../../experiments/vector_filters/README.md) | how the vector index behaves with SQL filters and index parameters, on generated vectors | Podman or Docker; starts its own throwaway MariaDB container (password `test`), never the project's stack |
| [`experiments/index_cache/`](../../experiments/index_cache/README.md) | the index cache, deleted vectors and the graph statistics, on the real data | the Compose database up with all articles loaded; they restart the `db` container and run SQL as root inside it, so do not use the database meanwhile |

Their output goes to [eval/results](../../eval/results/README.md) (`index_cache`) or `experiments/vector_filters/results/` (the generated-vector runs).

## Evaluation output

`make eval` and `python -m src.evaluation ...` write timestamped JSON and Markdown reports to `eval/results/`; [the index](../../eval/results/README.md) says which reports belong to which experiment.
