# Configuration

[← Architecture](./Home.md) | [Documentation Home](../Home.md)

Application configuration is defined in `src/config.py` with Pydantic Settings. Every setting is an environment variable; during local development they come from `.env` (copy [`.env.example`](../../.env.example); `make quickstart` does it for you).

```python
model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

Precedence, highest first: real environment variables, then `.env`, then the defaults in `src/config.py`. Unknown variables are ignored. Invalid values (a bad port, a `CHUNK_CONFIG` other than A, B or C, a `LOG_LEVEL` that does not exist) stop the application at startup with a validation error.

## Settings

| Variable | Default | Used for |
| --- | --- | --- |
| `APP_ENV` | `development` | `development` or `production`; production switches the logs to JSON ([Logging](./Logging.md)) |
| `LOG_LEVEL` | `INFO` | `DEBUG` to `CRITICAL`; `DEBUG` also echoes SQL |
| `APP_HOST`, `APP_PORT` | `0.0.0.0`, `8000` | only `python -m src.main`; `make run` and the Docker image pass their own host and port |
| `MARIADB_HOST`, `MARIADB_PORT` | `db`, `3306` | the database; `127.0.0.1` when the app runs on your machine ([below](#docker-and-local-development)) |
| `MARIADB_USER`, `MARIADB_PASSWORD`, `MARIADB_DATABASE` | `ueza`, `ueza_password`, `ueza_db` | database credentials; development defaults |
| `MARIADB_POOL_RECYCLE`, `MARIADB_POOL_PRE_PING` | `3600`, `true` | connection pool |
| `CACHE_DIR`, `CACHE_TTL_SECONDS` | `.cache/articles`, `86400` | the [article cache](../ingestion/Cache.md) |
| `MEDIAWIKI_USER_AGENT` | project name, repository URL, contact address | identifies the project to Wikimedia; override it when you run under another identity |
| `MEDIAWIKI_REQUESTS_PER_SECOND`, `MEDIAWIKI_MAX_RETRIES`, `MEDIAWIKI_BATCH_SIZE`, `MEDIAWIKI_TIMEOUT`, `MEDIAWIKI_MAXLAG` | `2.0`, `3`, `20`, `10.0`, `5` | [MediaWiki client](../ingestion/mediawiki/Home.md) |
| `ARTICLES_CSV_PATH` | `data/articles.csv` | the article list (the default of `--csv`) |
| `CHUNK_CONFIG` | `A` | chunking: A (256 tokens, 32 overlap), B (512, 64) or C (one paragraph, at most 512) |
| `INGESTION_SNAPSHOT` | `true` | `true`: each article at its revision on the CSV's `last_edit` date; `false`: the latest revisions (`make ingest-latest`) |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-base-en-v1.5` | embedding model; chunks and questions must use the same one |
| `EMBEDDING_DIMENSION` | `768` | must match the model and the `VECTOR(768)` column ([below](#embedding-dimension)) |
| `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_PASSAGE_PREFIX` | bge's query instruction, empty | prefixes the model expects for questions and passages; not in `.env.example` because the defaults suit bge |
| `VECTOR_SEARCH_TOP_K` | `5` | default number of chunks for a question |
| `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | OpenAI, empty, `gpt-4o-mini` | any OpenAI-compatible endpoint ([Retrieval and RAG](../rag/Home.md#language-model)) |
| `LLM_TEMPERATURE`, `LLM_TIMEOUT_SECONDS` | `0.2`, `60` | generation; a local model on a CPU needs a longer timeout |
| `RAG_MAX_DISTANCE` | `0.42` | chunks further than this cosine distance are dropped; none left means "not found" without calling the model |
| `GROUND_TRUTH_PATH`, `EVAL_RESULTS_DIR` | `data/ground_truth.csv`, `eval/results` | the [evaluation](../evaluation/Home.md) |

Variables read by Docker Compose and the Makefile rather than by `src/config.py`: `MARIADB_ROOT_PASSWORD` (the database container), `MARIADB_PORT` and `APP_PORT` (the ports published on the host), and the Makefile's own `EVAL_RUNS`, `INGEST_CONFIG`, `INGEST_CSV`, `INGEST_LIMIT`, `M` and `ARGS` ([Development Workflow](../development/Home.md)).

## Database URL

`database_url` is `mysql+aiomysql://` with the `utf8mb4` charset. The application, the ingest and the evaluation all use it through SQLAlchemy's async engine. There is no synchronous URL: no tool in the project needs one.

## Embedding dimension

`EMBEDDING_DIMENSION` (default 768) must match the model and the `VECTOR(768)` column in `schema.sql`. The `Embedder` checks it against the model, the `ArticleRepository` checks every vector it stores against it, and `ingest` and `sync` check the table's column against it before they start. Nothing changes the column automatically ([Schema Management](../database/Schema.md)).

## Docker and local development

The default `MARIADB_HOST` is `db`, the name of the database service inside the Compose network. When the Python application runs on your machine and MariaDB is the container's published port, `.env` sets `MARIADB_HOST=127.0.0.1` (this is what `.env.example` contains). The Compose `app` service reads `.env` too but overrides `MARIADB_HOST=db`, `MARIADB_PORT`, `CACHE_DIR` and `HF_HOME` ([Docker and Compose](../development/Docker.md)).

Secrets such as database passwords and API keys belong in `.env`, which is git-ignored and excluded from the Docker image. The defaults for the database user and password are for a database on your own machine only.
