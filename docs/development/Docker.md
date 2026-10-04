# Docker and Compose

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

The project uses a multi-stage `Dockerfile` and Docker Compose for the reproducible application stack.

## Application Image

The builder stage uses Python 3.14 and `uv` to create `/app/.venv` from `pyproject.toml` and `uv.lock`. Development dependencies are excluded from the runtime environment.

The runtime stage copies the prepared virtual environment, application source, Alembic configuration, and `scripts/entrypoint.sh` into a smaller Python runtime image.

## Startup

The application container starts through `scripts/entrypoint.sh`:

```text
container start
     ↓
alembic upgrade head
     ↓
exec uvicorn ...
```

Database schema migration is therefore part of application startup. Compose additionally waits for the MariaDB health check before starting the application service.

## Compose Services

The current stack contains:

- `db`: MariaDB 12.3.3 with a persistent `mariadb_data` volume and health check.
- `app`: the FastAPI application with a persistent `article_cache` volume and `/health` health check.

The application receives `MARIADB_HOST=db` inside the Compose network. Host-side development should use `MARIADB_HOST=localhost` when connecting through the published database port.

## Persistent Data

```text
mariadb_data  → /var/lib/mysql
article_cache → /app/.cache
```

The configured article cache path is `/app/.cache/articles`, so cache files remain inside the mounted `article_cache` volume.

`docker compose down` preserves these volumes. Commands that explicitly include `-v`, such as the destructive cleanup workflow, remove them.
