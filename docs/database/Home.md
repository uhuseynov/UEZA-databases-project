# Database

[← Documentation Home](../Home.md)

MariaDB 12.3.3 holds the articles, their metadata, the text chunks and the embedding vectors. This section describes the schema, the code that talks to it, and what we measured about its vector index.

| Page | What it covers |
| --- | --- |
| [Data Model](./Data-Model.md) | the four tables and why they look the way they do |
| [Schema Management](./Schema.md) | `schema.sql` as the only schema definition, how to change it, the limits of that |
| [Connection and Sessions](./Connection.md) | the async engine and the transactional session |
| [Vector Search and Index Parameters](./Vector-Search.md) | the vector index, how MariaDB plans a search with filters, `M` and `mhnsw_ef_search` |
| [Vector Index State](./Index-State.md) | how the index's speed and recall depend on its history: the cache, deleted vectors, the graph statistics |
| [FAISS Baseline](./FAISS-Baseline.md) | the same vectors and questions in FAISS |
| [Findings](./Findings.md) | what we learned, why MariaDB, where it loses |
| [Podman on Windows](./podman.md) | running the database container with Podman instead of Docker |

## Code

```text
schema.sql                              the schema, loaded on the first start of an empty volume
src/database/
├── connection.py                       Database: async engine, pool, transactional get_session()
├── vectors.py                          text, binary and hex forms of a vector
└── repositories/
    └── articles.py                     ArticleRepository: replace_article, statistics, index rebuild
```

There are no ORM models: the repository and the retriever write their SQL directly. `ArticleRepository` stores an article's metadata, categories, links, chunks and vectors in one transaction, refreshes the statistics (`ANALYZE TABLE`), and rebuilds the vector index with its current `M` and distance; `src/rag/retriever.py` runs the search statement ([Retrieval and RAG](../rag/Home.md)).

## Connection model

```text
SQLAlchemy AsyncEngine ──► aiomysql ──► MariaDB
```

## Where the columns come from

| Column | Filter name in `docs/data_decisions.md` | Source |
| --- | --- | --- |
| `articles.page_id` | | MediaWiki client: `page_id` |
| `articles.title` | | `title` column of `data/articles.csv` (the ground truth uses these titles) |
| `articles.root_category` | | `root_category` column of `data/articles.csv` (not known to MediaWiki) |
| `articles.article_length` | `article_length` | MediaWiki client: `length` |
| `articles.last_edit_date` | `last_edit_date` | MediaWiki client: `last_modified` |
| `articles.revision_id` | | MediaWiki client: `revision_id` (sync compares it to detect changes) |
| `article_categories.category` | `category` | MediaWiki client: `categories` |
| `article_links.linked_title` | `outgoing_links` | MediaWiki client: `links` |

## Settings that matter

`docker-compose.yml` starts MariaDB with `mhnsw_ef_search=40` and a 64 MB index cache because of the measurements in [Vector Search](./Vector-Search.md) and [Vector Index State](./Index-State.md). The database is published on `127.0.0.1` only ([Docker and Compose](../development/Docker.md)).
