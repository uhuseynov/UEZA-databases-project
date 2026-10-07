# MediaWiki Integration

[← Ingestion](../Home.md) | [Documentation Home](../../Home.md)

The MediaWiki integration retrieves Wikipedia articles and metadata through the MediaWiki API and converts responses into the project's `WikiArticle` representation.

## Responsibilities

The integration handles single and batch retrieval, redirects, article content, revision metadata, categories, outgoing article links, continuation, rate limiting, retries, API/HTTP errors, invalid responses, and optional article-cache lookup/population.

It intentionally does not handle cleaning, chunking, embedding generation, MariaDB persistence, vector indexing, vector search, or RAG.

## Data Flow

```text
Article title
     ↓
MediaWikiClient
     ↓
ArticleCache?
 ┌───┴────┐
 hit     miss
  │        │
  │   MediaWiki API
  │        ↓
  │   response parsing
  │        ↓
  │    WikiArticle
  │        ↓
  │   cache snapshot
  └────┬───┘
       ↓
   WikiArticle
       ↓
remaining ingestion pipeline
```

## Documentation

- [Client](./Client.md)
- [Data Model](./Data-Model.md)
- [Pagination](./Pagination.md)
- [Rate Limiting](./Rate-Limiting.md)
- [Retry Strategy](./Retry-Strategy.md)
- [Testing](./Testing.md)
- [Article Cache](../Cache.md)

## Source Code

```text
src/ingestion/mediawiki/
```

The cache is implemented separately in:

```text
src/ingestion/cache.py
```

Unit tests:

```text
tests/unit/ingestion/mediawiki/
```

Integration tests:

```text
tests/integration/ingestion/mediawiki/
```
