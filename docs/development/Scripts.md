# Scripts and Experiments

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

Everything that is neither the application nor a test: helper scripts, the script that built the article list, and the experiment scripts behind the index measurements.

## Helper scripts (`scripts/`, `.githooks/`)

| File | Run by | Does |
| --- | --- | --- |
| `scripts/entrypoint.sh` | the Docker image (`ENTRYPOINT`) | waits until MariaDB accepts connections (up to 60 s), then starts the container's command (`uvicorn`). It does not touch the schema ([Schema Management](../database/Schema.md)). |
| `scripts/setup-hooks.sh` | `make hooks`, `make setup` | sets `core.hooksPath` to `.githooks` and makes the hooks executable |
| `.githooks/commit-msg` | Git | validates the Conventional Commit subject ([Git Hooks](./Git-Hooks.md)) |
| `.githooks/pre-push` | Git | runs the unit tests before a push |

## Building the article list: `data/build_article_list.py`

The script that produced `data/articles.csv` (see [Data decisions](../data_decisions.md#selection-262-articles)): it reads six root categories and one level of subcategories from Wikipedia, drops list pages and the hand-removed off-topic articles (the `remove` list), caps each root, adds the hand-picked core articles, and writes the CSV.

```bash
uv run python data/build_article_list.py   # do not run it casually, see below
```

**It is a record of how the list was made, not a safe way to regenerate it.** Checked by reading the script and the environment (it was not run, because it queries Wikipedia and rewrites the file):

- **It overwrites `data/articles.csv`** directly. The ingest, `make ingest-check`, the sync and the ground truth all depend on that file, and a new run would not reproduce it: it reads the *current* category members, lengths and edit times, so the list, the `last_edit` snapshot dates and with them the questions with edit-date filters would change.
- **`requests` is not a declared dependency.** `import requests` works today only because the package is installed transitively (`langchain-text-splitters` → `langsmith` → `requests`; `uv run python -c "import requests"` succeeds). If that chain changes, the script stops working while the rest of the project does not.
- **Its user agent differs from the project's** (`UZA-databases-project (…@constructor.university)` against `MEDIAWIKI_USER_AGENT`, [Configuration](../architecture/Configuration.md)). Both name a contact, which is what Wikimedia asks for, so this is an inconsistency, not a failure.
- It sends requests without a timeout or status check and runs on import (no `main` guard).

The data page and the CSV are consistent with each other; the script is not unusable, but running it needs care. The smallest corrections would be to write to another file (for example `data/articles.generated.csv`), to use `httpx` (already a dependency) instead of `requests`, and to reuse the project's user agent. None of this has been changed.

## Experiments (`experiments/`)

Scripts behind the measurements in [Vector Search](../database/Vector-Search.md) and [Vector Index State](../database/Index-State.md). They are run by hand and are not part of the tests or CI.

| Directory | What it measures | Needs |
| --- | --- | --- |
| [`experiments/vector_filters/`](../../experiments/vector_filters/README.md) | how the vector index behaves with SQL filters and index parameters, on generated vectors | Podman or Docker; starts its own throwaway MariaDB container (password `test`), never the project's stack |
| [`experiments/index_cache/`](../../experiments/index_cache/README.md) | the index cache, deleted vectors and the graph statistics, on the real data | the Compose database up with all articles loaded; they restart the `db` container and run SQL as root inside it, so do not use the database meanwhile |

Their output goes to [eval/results](../../eval/results/README.md) (`index_cache`) or `experiments/vector_filters/results/` (the generated-vector runs).

## Evaluation output

`make eval` and `python -m src.evaluation ...` write timestamped JSON and Markdown reports to `eval/results/`; [the index](../../eval/results/README.md) says which reports belong to which experiment.
