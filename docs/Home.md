# UZA Databases Project

Technical documentation for the UZA Databases Project.

The project explores native vector search and retrieval-augmented generation using MariaDB. The documentation follows the implementation: completed infrastructure is documented as current behavior, while unfinished ingestion and RAG stages are marked as planned.

## Documentation

### Architecture

- [Architecture Overview](./architecture/Home.md)
- [Configuration](./architecture/Configuration.md)
- [Dependency Injection](./architecture/Dependency-Injection.md)
- [Logging](./architecture/Logging.md)

### Database

- [Database Overview](./database/Home.md)
- [Connection and Sessions](./database/Connection.md)
- [Migrations](./database/Migrations.md)

### Ingestion

- [Ingestion Overview](./ingestion/Home.md)
- [Article Cache](./ingestion/Cache.md)
- [MediaWiki Integration](./ingestion/mediawiki/Home.md)

## Current Application Structure

```text
src/
├── config.py
├── containers.py
├── logger.py
├── main.py
├── database/
│   ├── base.py
│   ├── connection.py
│   ├── migrations/
│   ├── models/
│   ├── repositories/
│   └── service/
└── ingestion/
    ├── cache.py
    └── mediawiki/
```

## Current Foundation

The repository currently contains:

- Pydantic-based application configuration
- Dependency injection using `dependency-injector`
- FastAPI application bootstrap and lifecycle management
- Async SQLAlchemy database connection management for MariaDB
- A synchronous MariaDB URL intended for Alembic
- Alembic migration scaffolding
- Application logging
- Disk-backed MediaWiki article caching
- MediaWiki retrieval, pagination, rate limiting, retry handling, and tests

Cleaning, chunking, embedding, persistence models, vector search, and RAG are later stages and are not documented as completed implementations yet.
