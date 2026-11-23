# Article Cache

[← Ingestion](./Home.md) | [Documentation Home](../Home.md)

`src/ingestion/cache.py` implements a disk-backed cache for `WikiArticle` objects.

Its purpose is to reduce redundant MediaWiki API requests during development and ingestion runs.

## Configuration

The cache uses `CACHE_DIR` and `CACHE_TTL_SECONDS`. The dependency injection container supplies these values to a shared `ArticleCache`.

## Cache keys

The key is the SHA-256 of the *normalized* title (`normalize_title` in `src/ingestion/cache.py`), which merges only spellings that MediaWiki treats as the same page title on English Wikipedia:

- Unicode is normalized to NFC (`Café` typed with a combining accent is the same title);
- underscores are spaces, runs of spaces and underscores are one space, and leading and trailing spaces are dropped (`Python_(programming_language)` is `Python (programming language)`);
- the first letter is capitalized (`machine learning` is `Machine learning`), unless its capital letter would be longer than one character.

Everything else is left alone, so distinct pages are never merged: `IPhone` and `Iphone`, `AI` and `Ai`, `Machine learning` and `Machine Learning`, `Café` and `Cafe`, `Foo+Bar` and `Foo Bar`. Percent-encoding belongs to the URL: a request such as `/articles/Foo%20Bar` arrives decoded, and a title that contains a literal `%20` (`/articles/Foo%2520Bar`) stays different from `Foo Bar`. Titles are never lowercased as a whole.

**Compatibility.** Entries written before the normalization were stored under the title MediaWiki returned, which is already normalized, so they are found under the same file name as before. A lookup also tries the title exactly as given, for an entry stored under another spelling. Nothing is rewritten or deleted: a lookup never writes, and old files simply expire by TTL.

**Redirects.** What a redirect points to cannot be known from the spelling. The first request for an alias (`ML`) goes to MediaWiki, which resolves it; the cache then stores the article under its canonical title and a small alias entry (`{"alias_of": ...}`) under the alias, so later requests for the alias are served locally. The alias entry expires on its own TTL, so a changed redirect is noticed, it points at the target's entry (it is a miss once that is gone or expired), and aliases do not chain. An alias nobody has fetched yet is a cache miss.

## Storage

Each article is stored as a JSON file under the configured cache directory.

The file name is `<sha256 of the normalized title>.json` (see [Cache keys](#cache-keys)), so any title gives a safe, collision-resistant name.

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

The cache is an ingestion optimization, not the source of truth for synchronization. The [live sync](./Home.md#live-sync) detects changes without the cache: it compares revision ids from MediaWiki with the stored `articles.revision_id`. Fetches of the *latest* revision go through the cache (`make ingest-latest`, `sync` and `GET /articles/{title}`): a cached copy younger than `CACHE_TTL_SECONDS` is served instead of asking MediaWiki again, so `ingest-latest` and the API can show an article up to that old.

**The sync never reuses an older revision.** It knows the revision it just read from MediaWiki and passes it as `min_revision`; a cached copy with an older revision is ignored and replaced by the fresh fetch. Without this, a copy cached within the last day could be stored again and the next sync would find the same article changed once more. **The snapshot ingest never touches the cache**: it asks for the revision at the CSV date, and neither reads nor writes cache entries, so a loaded snapshot does not depend on what the cache holds.
