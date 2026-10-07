# Dependency Injection

[← Architecture](./Home.md) | [Documentation Home](../Home.md)

The project uses `dependency-injector` to centralize object construction in `src/containers.py`.

## Container

`Container` currently provides:

```text
Settings
   │
   ├── AppLogger (Singleton)
   ├── Database (Singleton)
   ├── ArticleCache (Singleton)
   └── MediaWikiClient (Factory)
```

## Lifetimes

`AppLogger`, `Database`, and `ArticleCache` are shared singleton components. `MediaWikiClient` is provided as a factory and receives the shared logger and cache plus the configured MediaWiki settings.

## Why Centralize Construction?

The container prevents infrastructure configuration from being duplicated across routes, services, and ingestion code.

```text
route/service
    ↓
Container
    ↓
configured dependency
```

As repository, search, embedding, and RAG services are implemented, their dependencies can be added to this graph without moving construction logic into business code.

## FastAPI Integration

The application creates the container in `create_app()` and stores it on `app.state`.

The current code accesses providers through that container. Dedicated FastAPI dependency wrappers can be introduced later if route-level injection becomes useful.
