# Architecture

[← Documentation Home](../Home.md)

UEZA answers questions about 262 English Wikipedia articles. The articles, their metadata and their embedding vectors live in one MariaDB database, and one SQL statement combines the vector search with ordinary filters. This page shows how the pieces fit together; the pages it links to have the details.

## Two data flows

**Ingest** (offline, `python -m src.ingestion`): from the article list to vectors in MariaDB.

```text
data/articles.csv
      │  title, page id, edit date, root category
      ▼
MediaWikiClient ── ArticleCache (latest mode only)        src/ingestion/mediawiki/, cache.py
      │  WikiArticle: text, categories, links, revision
      ▼
clean_wikitext                                            src/ingestion/cleaner.py
      ▼
chunk_article  (config A: 256 tokens, 32 overlap)         src/ingestion/chunker.py
      ▼
Embedder  (bge-base-en-v1.5, kind="passage")              src/rag/embedder.py
      ▼
ArticleRepository.replace_article                         src/database/repositories/articles.py
      │  one transaction per article
      ▼
MariaDB: articles, article_categories, article_links, article_chunks (VECTOR(768) + HNSW index)
```

After the last article, `IngestionPipeline` refreshes the statistics (`ANALYZE TABLE`) and rebuilds the vector index if it replaced stored articles. `sync` runs the same pipeline for the articles that changed on Wikipedia, and `check` verifies the loaded data ([Ingestion](../ingestion/Home.md)).

**Query** (online, the FastAPI app): from a question to an answer.

```text
question  (GET /search, POST /ask)                        src/api/routes.py
      ▼
RAGService.search                                         src/rag/service.py
      │  Embedder (kind="query"), in a worker thread
      ▼
VectorRetriever.retrieve                                  src/rag/retriever.py
      │  one statement: VEC_DISTANCE_COSINE + JOIN articles + filters
      ▼
MariaDB  ──► chunks with cosine distance
      ▼
RAGService.answer  (POST /ask only)
      │  drop chunks above RAG_MAX_DISTANCE; none left → "not found", no LLM call
      ▼
prompt.build_messages ──► ChatLLM (OpenAI-compatible API) ──► reply
      ▼
NOT_FOUND → "not found"; otherwise the answer with the articles it cites
```

`/search` stops after the retriever and needs no language model ([Retrieval and RAG](../rag/Home.md)).

## Modules

| Package | Responsibility | Main files |
| --- | --- | --- |
| `src/config.py`, `src/logger.py` | Settings from environment and `.env`; development and JSON logging | [Configuration](./Configuration.md), [Logging](./Logging.md) |
| `src/containers.py` | Builds and shares the objects of the application | [Dependency Injection](./Dependency-Injection.md) |
| `src/main.py` | FastAPI app factory, lifespan (database pool), `/health` | |
| `src/api/` | Routes, request and response schemas, the web page | `routes.py`, `schemas.py`, `static/index.html` |
| `src/rag/` | Embedder, search statement, RAG service, prompt, LLM client | `embedder.py`, `retriever.py`, `service.py`, `prompt.py`, `llm.py` |
| `src/database/` | Async connection and session, vector serialization, the article repository | `connection.py`, `vectors.py`, `repositories/articles.py` |
| `src/ingestion/` | MediaWiki client, cache, cleaning, chunking, pipeline, sync, consistency check, CLI | [Ingestion](../ingestion/Home.md) |
| `src/evaluation/` | Ground truth, metrics, runner, reports, FAISS baseline, answers, CLI | [Evaluation](../evaluation/Home.md) |
| `schema.sql` | The only schema definition | [Schema Management](../database/Schema.md) |

## Dependencies between packages

```text
api ────────► rag ────────► database ◄──────── ingestion
 │                              │                  │
 └──► ingestion.mediawiki       └► config, logger  └──► rag.embedder, config

evaluation ──► rag, database, config
containers ──► builds every package above
main, ingestion CLI, evaluation CLI ──► containers
```

In words:

- `rag` depends on `database` (the retriever runs its statement through `Database`) and on nothing else of the project.
- `database` knows nothing of `rag`. The vector serialization both need lives in `database/vectors.py`.
- `ingestion` depends on `database` (the repository) and on `rag.embedder`, so chunks and questions go through the same model.
- `api` uses `rag` and, for `GET /articles/{title}`, `ingestion.mediawiki`.
- `evaluation` uses the same retriever (and, for the language model's answers, the same `RAGService`) as the app, so it measures what the application runs.

One wrinkle: `database/repositories/articles.py` imports `WikiArticle` from `ingestion.mediawiki` for its type annotation, so the repository and the MediaWiki data model are coupled by one dataclass. There is no import cycle.

## Application entry points

| Entry point | Started by | Does |
| --- | --- | --- |
| `src.main:app` | `make run`, `make up` | Web page, `/search`, `/ask`, `/articles/{title}`, `/health` |
| `python -m src.ingestion` | `make ingest`, `ingest-check`, `reindex`, `ingest-sync` | `ingest`, `check`, `reindex`, `sync` |
| `python -m src.evaluation` | `make eval` and its variants | `run`, `ef-sweep`, `m-sweep`, `explain`, `faiss`, `answers` |

`GET /articles/{title}` (in `src/api/routes.py`) exercises `MediaWikiClient` and the article cache: it runs the synchronous client in a worker thread, so the event loop keeps serving other requests, and closes the per-request client afterwards. MediaWiki errors are a 400, a blank title a 422.

## Design decisions

- **Everything in MariaDB.** One statement filters and searches, one transaction per article keeps text and vectors consistent. The measurements behind this are in [Findings](../database/Findings.md).
- **Schema as a SQL file.** `schema.sql`, no migration tool and no ORM models ([Schema Management](../database/Schema.md)).
- **Raw SQL with bound parameters.** The retriever builds its statement from fixed fragments; user values are never part of the SQL text ([Retrieval and RAG](../rag/Home.md)).
- **Blocking work off the event loop.** The embedding model and the MediaWiki client are synchronous and run in worker threads.
- **Measured settings.** `M=16`, `mhnsw_ef_search` 40, the 64 MB index cache and the 0.42 distance threshold come from recorded experiments ([Results](../evaluation/Results.md), [eval/results](../../eval/results/README.md)).

## Development infrastructure

Docker image and Compose stack, Git hooks, CI and the helper scripts are described under [Development Workflow](../development/Home.md).
