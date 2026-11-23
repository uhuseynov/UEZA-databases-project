# Article Cache

[← Ingestion](./Home.md) | [Documentation Home](../Home.md)

`src/ingestion/cache.py` implements a disk-backed cache for `WikiArticle` objects.

Its purpose is to reduce redundant MediaWiki API requests during development and ingestion runs.

## Configuration

The cache uses `CACHE_DIR` and `CACHE_TTL_SECONDS`. The dependency injection container supplies these values to a shared `ArticleCache`.

## Storage

Each article is stored as a JSON file under the configured cache directory.

The file name is the SHA-256 hash of the title exactly as the client was asked for it (`<hash>.json`), so any title gives a safe, collision-resistant name. A request is a cache hit only when it uses the same spelling that was stored: the entry is stored under the canonical title MediaWiki returned.

The serialized data contains the page ID, canonical title, raw text, length, revision ID, last-modified timestamp, categories, and outgoing links.

The timestamp is stored in ISO format and reconstructed when read.

## TTL

Freshness is based on the cache file's modification time.

```text
current UTC timestamp
        -
file modification time
        ↓
      age
```

If the age exceeds `CACHE_TTL_SECONDS`, the entry is treated as a cache miss. Expired files are currently left on disk.

## MediaWiki Integration

```text
get_article(title)
      ↓
cache lookup
  ┌───┴────┐
 hit      miss
  │         │
return    MediaWiki API
            ↓
         cache result
            ↓
          return
```

Batch retrieval checks cached titles first and sends only missing titles to the API.

## Failure Behavior

Unreadable, malformed, or incomplete cache files are treated as cache misses instead of breaking article retrieval.

## Scope

The cache is an ingestion optimization, not the source of truth for synchronization. The [live sync](./Home.md#live-sync) detects changes without the cache: it compares revision ids from MediaWiki with the stored `articles.revision_id`. Every fetch of the *latest* revision goes through the cache (`make ingest-latest`, the re-ingest of changed articles in `sync`, and `GET /articles/{title}`), so a cached copy younger than `CACHE_TTL_SECONDS` is served instead of asking MediaWiki again. This was read from the code, not measured. The default snapshot ingest asks for a historical revision and bypasses the cache.
