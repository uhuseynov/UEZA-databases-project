# MediaWiki Client

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

## Purpose

`MediaWikiClient` provides the boundary between the ingestion system and the MediaWiki API. It converts MediaWiki responses into project-level `WikiArticle` objects.

## Responsibilities

The client is responsible for sending requests, retrieving content and metadata, resolving redirects, batch retrieval, continuation handling, transient failure handling, rate limiting, response parsing, and domain-object construction.

It is not responsible for cleaning, chunking, embeddings, MariaDB persistence, vector search, or RAG.

## API Endpoint

```text
https://en.wikipedia.org/w/api.php
```

Requests use the MediaWiki `query` API and retrieve properties such as `info`, `revisions`, `categories`, and `links`.

## Article Retrieval

```python
article = client.get_article("Machine learning")
```

See [Data Model →](./Data-Model.md).

## Batch Retrieval

The client supports retrieving multiple articles. Batch retrieval reduces requests where MediaWiki can return information for several pages in one query. Metadata requiring continuation may still require additional requests.

## Redirects

Redirect resolution is enabled. The title stored in `WikiArticle` is the canonical title returned by MediaWiki.

## Separation from Processing

The client returns raw source content. Cleaning rules and decisions about useful categories or links belong to later ingestion stages.

## Error Handling

Project-specific exceptions isolate higher layers from `httpx` exceptions and MediaWiki response structures. Transient failures may be retried before an exception reaches the caller.

See [Retry Strategy →](./Retry-Strategy.md).

## Related Documentation

- [Data Model](./Data-Model.md)
- [Pagination](./Pagination.md)
- [Rate Limiting](./Rate-Limiting.md)
- [Retry Strategy](./Retry-Strategy.md)
- [Testing](./Testing.md)

## Caching

When an `ArticleCache` is supplied, the client checks it before making a MediaWiki request.

Successful API results are written back to the cache. Batch retrieval similarly separates cached titles from titles that still need to be fetched.

Caching remains a separate ingestion concern rather than part of HTTP response parsing.

See [Article Cache →](../Cache.md).
