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

MariaDB is published as `127.0.0.1:${MARIADB_PORT:-3306}` and the web app as `127.0.0.1:${APP_PORT:-8000}`: the host reaches them, other machines do not, and the app container uses `db:3306` internally. The defaults (`ueza` / `ueza_password`, root password `root_password`) are development values for a database on your own machine. Set `MARIADB_PASSWORD` and `MARIADB_ROOT_PASSWORD` in `.env` before running the stack anywhere shared. The password is only used when the database volume is first created; an existing volume keeps its old one.

## Exposing the app

The API has **no authentication and no rate limiting**, which is why Compose publishes it on the loopback interface only. Setting `APP_BIND_ADDRESS=0.0.0.0` in `.env` (or `APP_BIND_ADDRESS=<an interface address>`) publishes it on every network interface of the machine; Compose then lists `0.0.0.0:<port>`. Do it only on a network you trust, or behind a reverse proxy or firewall that authenticates callers. What anyone who can reach the port can do:

- **`POST /ask`** sends their questions to your language model: it spends your API credit (or keeps a local model busy) and returns text retrieved from the database.
- **`GET /articles/{title}`** makes the server fetch any Wikipedia article and write it to the article cache, so it can be used to generate outbound requests and fill the cache volume.
- **`GET /search`** runs vector searches against the database.
- **`/docs`, `/redoc` and `/openapi.json`** describe the whole API.
- Errors do not reveal internals: a failed language model call returns the fixed message "The language model request failed. Try again later." and a database failure a generic message; the details are in the application log.

The app started on the host is local by default too: `make run` and `python -m src.main` bind `APP_HOST`, which defaults to `127.0.0.1`. To expose it deliberately, set `APP_HOST=0.0.0.0` in `.env` or run `make run APP_HOST=0.0.0.0` (a value in `.env` takes precedence over a plain environment variable; the command-line form always wins). The same risks apply as above. A `.env` copied from an older `.env.example` still contains `APP_HOST=0.0.0.0`: change it if you do not want that. Inside the container, uvicorn always listens on `0.0.0.0` (the published port needs it); only `APP_BIND_ADDRESS` decides who can reach it from outside.

## Container user

The application runs as the unprivileged user `ueza` (uid and gid 10001), not as root. The image's code and virtual environment belong to root and are read-only to the application; only `/app/.cache` (the article cache and the Hugging Face model cache) is writable by it.

The container starts as root for a moment so `scripts/entrypoint.sh` can repair file ownership, then drops privileges with `setpriv` before it starts `uvicorn`, which is process 1. This is what keeps existing installations working: a `article_cache` volume created by an earlier version of the image holds root-owned files, and on the next start the entrypoint hands `/app/.cache` to `ueza` once (it only looks first, so nothing is changed or walked when the ownership is already right). A new volume is created with the right owner. If you start the container as another user (`docker run --user`, or `user:` in Compose), the entrypoint runs the command as that user and does not touch ownership.

`docker compose exec app ...` opens a shell as root (the image's default user); add `--user ueza` to run a command as the application does, for example `docker compose exec --user ueza app python -m src.ingestion ingest --limit 3`.

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
