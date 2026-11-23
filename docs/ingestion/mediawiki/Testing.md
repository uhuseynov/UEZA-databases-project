# MediaWiki Testing

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

The MediaWiki integration is tested with mocked HTTP only; no test contacts the real Wikipedia.

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

`test_client_cache.py` (cache hit and miss through the client) sits next to them in `tests/unit/ingestion/mediawiki/`.

## Unit Tests

Unit tests do not access the real MediaWiki API. HTTP behavior is simulated with `httpx.MockTransport`.

They cover article retrieval, batch retrieval, parsing, redirects, missing pages, pagination, rate limiting, retries, API errors, invalid responses and the cache.

## Integration Tests

`tests/integration/ingestion/mediawiki/test_mediawiki_api.py` is marked `integration`, but it also runs against `httpx.MockTransport`. It checks the request the client sends (host, path, user agent and every query parameter) and the full article conversion, a redirect and a missing page (`MediaWikiPageNotFoundError`) against realistic response shapes. It needs neither a network nor a database, so it is deterministic in CI.

Nothing in the test suite contacts Wikipedia. A check against the real service is a manual one, for example `make ingest-test` (three articles) or `make ingest-sync-dry-run`.

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

All behaviour is tested deterministically against recorded response shapes, so CI never depends on Wikipedia being reachable or unchanged. The price is that a change in the real API is only noticed by running the ingest.

## Cache Testing

Cache behavior should be tested independently from MediaWiki HTTP parsing.

Important cases include fresh entries, expired entries, malformed cache files, serialization round-trips, and cache hit/miss behavior when integrated with `MediaWikiClient`.
