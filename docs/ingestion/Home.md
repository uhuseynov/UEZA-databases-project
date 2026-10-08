# Ingestion

[← Documentation Home](../Home.md)

The ingestion layer retrieves external source data and will eventually transform it into data suitable for storage and retrieval in MariaDB.

## Intended Pipeline

```text
MediaWiki
    ↓
Article Cache
    ↓
Raw WikiArticle
    ↓
Cleaning
    ↓
Chunking
    ↓
Embedding
    ↓
MariaDB
```

## Implemented Components

### MediaWiki

Retrieves Wikipedia articles and metadata through the MediaWiki API.

[MediaWiki Documentation →](./mediawiki/Home.md)

### Article Cache

Stores fetched `WikiArticle` snapshots on disk with a configurable TTL to avoid unnecessary repeated API requests.

[Article Cache →](./Cache.md)

## Planned Stages

Cleaning, chunking, embedding, and MariaDB persistence are planned stages. They are intentionally not documented as completed implementations until their code exists.

## Separation of Responsibilities

The MediaWiki adapter retrieves source data. The cache avoids redundant source requests. Neither component decides how text should be cleaned, chunked, embedded, or persisted.

This separation allows later chunking and embedding experiments without rewriting the source integration.
