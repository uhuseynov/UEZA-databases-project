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

`src/database/` contains asynchronous connection/session management, the article repository and the vector serialization helpers. The schema is `schema.sql`; there are no ORM models.

[Database Documentation →](../database/Home.md)

### Ingestion

`src/ingestion/` contains source retrieval and caching. MediaWiki is currently the implemented external source.

[Ingestion Documentation →](../ingestion/Home.md)

## Application Entry Point

`src/main.py` creates the FastAPI application and owns application startup and shutdown through the FastAPI lifespan mechanism.

At startup the database connection pool is initialized. At shutdown the engine is disposed.

`GET /articles/{title}` (in `src/api/routes.py`) exercises `MediaWikiClient` and the article cache: it runs the synchronous client in a worker thread, so the event loop keeps serving other requests, and closes the per-request client afterwards. MediaWiki errors are a 400, a blank title a 422.

## Development Infrastructure

The repository also includes a multi-stage Docker build, Docker Compose service health checks, repository-managed Git hooks, and a gated GitHub Actions CI pipeline. These are documented under [Development Workflow](../development/Home.md).
