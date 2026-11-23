# Dependency Injection

[← Architecture](./Home.md) | [Documentation Home](../Home.md)

The project uses `dependency-injector` to build and share the application's objects in one place, `src/containers.py`.

## Container

`Container` provides:

| Provider | Kind | Built from | Used by |
| --- | --- | --- | --- |
| `config` | Object | the `settings` instance of `src/config.py` | every other provider |
| `app_logger` | Singleton | `AppLogger(settings)` | `Database`, `MediaWikiClient`, app startup |
| `database` | Singleton | `Database(settings, logger)` | repository, retriever, app lifespan, CLIs |
| `article_repository` | Factory | `ArticleRepository(database, dimension=EMBEDDING_DIMENSION)` | ingestion CLI (`ingest`, `check` preflight, `reindex`, `sync`) |
| `article_cache` | Singleton | `ArticleCache(CACHE_DIR, CACHE_TTL_SECONDS)` | `mediawiki_client` |
| `mediawiki_client` | Factory | MediaWiki settings, logger, cache | `GET /articles/{title}`, ingestion CLI |
| `embedder` | ThreadSafeSingleton | `Embedder(model name, dimension, prefixes)` | RAG service, ingestion CLI |
| `ingestion_pipeline` | Factory | client, embedder, repository | not used: the CLI builds `IngestionPipeline` itself |
| `retriever` | Singleton | `VectorRetriever(database)` | `rag_service` |
| `llm` | Singleton | `ChatLLM(base URL, key, model, temperature, timeout)` | `rag_service` |
| `rag_service` | Singleton | embedder, retriever, llm, `top_k`, `max_distance` | `/search`, `/ask` |

## Lifetimes

- **Singletons** are shared for the lifetime of the container: the logger, the database pool, the article cache, the retriever, the LLM client and the RAG service. `embedder` is thread-safe because the first request loads the model in a worker thread.
- **Factories** build a new object per call. `mediawiki_client` is a factory because each client owns an HTTP connection pool that has to be closed: the `/articles/{title}` route creates one per request and closes it afterwards, and the CLI closes its own. The shared `article_cache` is what is reused between them.

## How code gets its dependencies

There is no wiring and no `@inject` or `Provide[...]` marker anywhere. The container is created in `create_app()` and stored on `app.state.container`; routes read providers from it:

```python
request.app.state.container.rag_service()
```

The CLIs (`python -m src.ingestion`, `python -m src.evaluation`) create their own `Container()` and call the providers they need. Business classes (`RAGService`, `IngestionPipeline`, `VectorRetriever`) take their dependencies as constructor arguments and never import the container, so tests build them directly.

## In tests

Providers are replaced with `override`, for example the unit tests of the API:

```python
app.state.container.rag_service.override(providers.Object(fake_service))
app.state.container.mediawiki_client.override(providers.Factory(make_fake_client))
```
