# Database Migrations

[← Database](./Home.md) | [Documentation Home](../Home.md)

Alembic migration infrastructure is located under:

```text
src/database/migrations/
```

The project also contains `alembic.ini` at the repository root.

## Configuration

Application traffic uses the asynchronous `database_url`, while migration tooling should use the synchronous `sync_database_url` backed by PyMySQL.

The migration environment uses the same SQLAlchemy metadata as the application:

```text
Database models
      ↓
Base.metadata
      ↓
Alembic autogenerate
      ↓
migration revision
```

## Current Status

`src/database/migrations/env.py` is wired to `settings.sync_database_url` and `Base.metadata`. The synchronous URL is installed into the Alembic configuration for online migrations, while offline migrations use the same settings URL directly. `compare_type=True` is enabled in both modes.

There are no persistence models yet. Once model modules are added, they must be imported before autogeneration so their tables are registered in `Base.metadata`.

The Docker application entrypoint runs `alembic upgrade head` before starting Uvicorn, so container startup applies pending migrations automatically after MariaDB is healthy.

## Typical Workflow

Once persistence models exist:

```bash
uv run alembic revision --autogenerate -m "create initial schema"
uv run alembic upgrade head
```

Inspection and rollback:

```bash
uv run alembic current
uv run alembic history
uv run alembic downgrade -1
```

## MariaDB-Specific Migrations

Autogeneration output must be reviewed before it is committed.

MariaDB-specific vector columns, vector indexes, index options, or SQL features may require explicit migration operations or raw SQL. Keeping those details visible is desirable because native MariaDB vector behavior is a core part of the project.
