# Docker and Compose

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

The project uses a multi-stage `Dockerfile` and Docker Compose for the reproducible application stack.

## Application Image

The builder stage uses Python 3.14 and `uv` to create `/app/.venv` from `pyproject.toml` and `uv.lock`. Development dependencies are excluded from the runtime environment.

The runtime stage copies the prepared virtual environment, application source, the article list in `data/`, and `scripts/entrypoint.sh` into a smaller Python runtime image.

## Startup

The application container starts through `scripts/entrypoint.sh`:

```text
container start
     ↓
wait until MariaDB accepts connections
     ↓
exec uvicorn ...
```

The entrypoint only waits for the database; it does not touch the schema. `schema.sql` is loaded by the MariaDB image on the first start of an empty volume ([Schema Management](../database/Schema.md)). Compose additionally waits for the MariaDB health check before starting the application service.

## Compose Services

The current stack contains:

- `db`: MariaDB 12.3.3 with a persistent `mariadb_data` volume and health check.
- `app`: the FastAPI application with a persistent `article_cache` volume and `/health` health check.

The application receives `MARIADB_HOST=db` inside the Compose network. Host-side development should use `MARIADB_HOST=127.0.0.1` when connecting through the published database port.

## Configuration of the app container

The `app` service reads `.env` through `env_file` (optional: without the file, the defaults of `src/config.py` apply, as in CI), so every setting reaches the container, including the language model (`LLM_*`), embeddings (`EMBEDDING_*`), `RAG_MAX_DISTANCE` and the MediaWiki settings. The file is read when the container starts. It is excluded from the image by `.dockerignore`, so no value is baked into a layer.

Four values are set in `docker-compose.yml` and win over `.env`: `MARIADB_HOST=db`, `MARIADB_PORT=3306`, `CACHE_DIR` and `HF_HOME`. Inside the container `localhost` is the container itself, so a language model on your machine (for example Ollama) is reached at `http://host.docker.internal:11434/v1`; `extra_hosts` makes that name work on Linux too.

## Network exposure and credentials

MariaDB is published as `127.0.0.1:${MARIADB_PORT:-3306}`: the host reaches it, other machines do not, and the app container uses `db:3306` internally. The defaults (`ueza` / `ueza_password`, root password `root_password`) are development values for a database on your own machine. Set `MARIADB_PASSWORD` and `MARIADB_ROOT_PASSWORD` in `.env` before running the stack anywhere shared. The password is only used when the database volume is first created; an existing volume keeps its old one. The web app port (`APP_PORT`) is published on all interfaces.

## Model cache

Both caches live in the `article_cache` volume: the MediaWiki articles in `/app/.cache/articles` and the Hugging Face models in `/app/.cache/huggingface` (`HF_HOME`). The embedding model (about 440 MB) is therefore downloaded once, not every time the container is recreated.

## What runs where

| Task | Where | Command |
| --- | --- | --- |
| Web app, `/search`, `/ask` | Docker or host | `make up` / `make run` |
| Ingest, `ingest-check`, `reindex`, live sync | host | `make ingest`, `make ingest-check`, `make reindex`, `make ingest-sync` |
| Evaluation, FAISS baseline, answers | host | `make eval`, `uv run python -m src.evaluation faiss` |
| Tests | host | `make test-unit`, `make test-integration` |
| Experiments | host | `experiments/` |

The image holds the runtime dependencies only: no development group (`faiss-cpu`, `pytest`), no `eval/`, `tests/` or `experiments/`, so the host-only tasks do not run in it. The ingest and the evaluation connect to the database through the published port (`MARIADB_HOST=127.0.0.1`).

## Persistent Data

```text
mariadb_data  → /var/lib/mysql
article_cache → /app/.cache
```

The configured article cache path is `/app/.cache/articles`, so cache files remain inside the mounted `article_cache` volume.

`docker compose down` preserves these volumes. Commands that explicitly include `-v`, such as the destructive cleanup workflow, remove them.
