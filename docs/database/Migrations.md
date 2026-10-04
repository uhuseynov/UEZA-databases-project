# Database Migrations

[← Database](./Home.md) | [Documentation Home](../Home.md)

Alembic migration scaffolding is located under:

```text
src/database/migrations/
```

The project also contains `alembic.ini` at the repository root.

## Intended Configuration

Application traffic uses the asynchronous `database_url`, while migration tooling should use the synchronous `sync_database_url` backed by PyMySQL.

The migration environment should use the same SQLAlchemy metadata as the application:

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

The Alembic scaffolding exists, but the migration environment still needs to be connected to the project's `Settings.sync_database_url` and `Base.metadata` before autogeneration is considered ready.

Model modules must also be imported before autogeneration so their tables are registered in `Base.metadata`.

## Typical Workflow

After the migration environment is wired:

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
