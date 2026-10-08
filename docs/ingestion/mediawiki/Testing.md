# MediaWiki Testing

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

The MediaWiki integration uses both unit and integration tests.

## Test Structure

```text
tests/
├── unit/
│   └── ingestion/
│       └── mediawiki/
│           ├── test_batch.py
│           ├── test_client.py
│           ├── test_pagination.py
│           ├── test_parsing.py
│           ├── test_rate_limiter.py
│           └── test_retry.py
└── integration/
    └── ingestion/
        └── mediawiki/
            └── test_mediawiki_api.py
```

## Unit Tests

Unit tests do not access the real MediaWiki API. HTTP behavior is simulated with `httpx.MockTransport`.

They cover article retrieval, batch retrieval, parsing, redirects, missing pages, pagination, rate limiting, retries, API errors, and invalid responses.

## Integration Tests

Integration tests communicate with the real MediaWiki API. Their purpose is to verify that assumptions tested with mocks still hold against the external service.

### Stable Assertions

Wikipedia changes continuously, so integration tests avoid exact revision IDs, article lengths, category counts, and link counts. They instead assert stable invariants such as positive IDs, non-empty content, and available metadata.

### Redirect and Missing Page Tests

A real redirect verifies canonical article handling. A deliberately nonexistent page verifies `MediaWikiPageNotFoundError`.

## Running Tests

Unit tests:

```bash
make test
```

or:

```bash
make test-unit
```

Integration tests:

```bash
make test-integration
```

All tests:

```bash
make test-all
```

## Testing Philosophy

Most detailed behavior belongs in deterministic unit tests. A small integration suite verifies the boundary with the real MediaWiki service.

## Cache Testing

Cache behavior should be tested independently from MediaWiki HTTP parsing.

Important cases include fresh entries, expired entries, malformed cache files, serialization round-trips, and cache hit/miss behavior when integrated with `MediaWikiClient`.
