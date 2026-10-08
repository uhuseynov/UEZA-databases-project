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

## Vector Search

The project is intended to use MariaDB-native vector functionality. Vector columns, vector indexes, distance functions, and their migrations should be documented once the schema is implemented rather than being described as completed behavior before that point.
