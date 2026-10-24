# Database

[← Documentation Home](../Home.md)

The database layer provides infrastructure for connecting the application to MariaDB and managing schema migrations.

## Current Structure

```text
src/database/
├── base.py
├── connection.py
├── migrations/
│   ├── env.py
│   └── script.py.mako
├── models/
├── repositories/
└── service/
```

`models`, `repositories`, and `service` are currently structural placeholders. Database entities and vector-search behavior should be documented when those implementations are added.

## Connection Model

```text
SQLAlchemy AsyncEngine
        ↓
     aiomysql
        ↓
     MariaDB
```

[Connection and Sessions →](./Connection.md)

## Migration Model

```text
Alembic
   ↓
SQLAlchemy synchronous connection
   ↓
PyMySQL
   ↓
MariaDB
```

[Migrations →](./Migrations.md)

## Schema and Vector Search

The schema lives in [`schema.sql`](../../schema.sql): four tables for articles, their categories, their links and the text chunks with their vectors. MariaDB creates it automatically on the first start of an empty database volume. The vector index, its parameters and the way MariaDB plans a search with SQL filters are described in [Vector Search and Index Parameters](./Vector-Search.md).
