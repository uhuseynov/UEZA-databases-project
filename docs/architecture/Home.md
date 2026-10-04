# Architecture

[← Documentation Home](../Home.md)

The application is organized around a small infrastructure layer that provides configuration, logging, dependency injection, database access, and external-source ingestion.

## High-Level Flow

```text
Settings
   │
   ▼
Dependency Injection Container
   ├───────────────┬─────────────────┐
   ▼               ▼                 ▼
AppLogger       Database        ArticleCache
                                   │
                                   ▼
                            MediaWikiClient

FastAPI
   │
   └── application lifecycle
           │
           ├── Database.connect()
           └── Database.disconnect()
```

## Main Components

### Configuration

`src/config.py` defines environment-driven settings and constructs synchronous and asynchronous MariaDB URLs.

[Configuration →](./Configuration.md)

### Dependency Injection

`src/containers.py` owns construction of shared application dependencies.

[Dependency Injection →](./Dependency-Injection.md)

### Logging

`src/logger.py` configures human-readable development logs and JSON production logs.

[Logging →](./Logging.md)

### Database

`src/database/` contains the SQLAlchemy base, asynchronous connection/session management, configured Alembic migration environment, and placeholders for models and repositories.

[Database Documentation →](../database/Home.md)

### Ingestion

`src/ingestion/` contains source retrieval and caching. MediaWiki is currently the implemented external source.

[Ingestion Documentation →](../ingestion/Home.md)

## Application Entry Point

`src/main.py` creates the FastAPI application and owns application startup and shutdown through the FastAPI lifespan mechanism.

At startup the database connection pool is initialized. At shutdown the engine is disposed.

The current article endpoint is a simple integration path for exercising `MediaWikiClient`; API routing can later be separated into dedicated route modules as the application grows.

## Development Infrastructure

The repository also includes a multi-stage Docker build, Docker Compose service health checks, repository-managed Git hooks, and a gated GitHub Actions CI pipeline. These are documented under [Development Workflow](../development/Home.md).
