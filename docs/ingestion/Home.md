# Ingestion

[← Documentation Home](../Home.md)

The ingestion layer loads the 262 articles of `data/articles.csv` from Wikipedia, turns them into chunks and vectors and stores them in MariaDB.

## Pipeline

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

## Running it

```bash
make ingest-test     # the first 3 articles of the CSV
make ingest          # all articles
make ingest-latest   # the latest revisions instead of the snapshot
make ingest-check    # every article present, chunks complete, no orphan rows
make reindex         # rebuild the vector index with the same M and distance
```

The settings come from `.env`: `ARTICLES_CSV_PATH`, `CHUNK_CONFIG` (A, B or C) and `INGESTION_SNAPSHOT`. The command is `uv run python -m src.ingestion ingest` (or `check`) with `--csv`, `--config`, `--latest` and `--limit`, for machines without `make`.

Each article is processed on its own, and a failure is logged and reported at the end without stopping the others. The command then exits with an error that lists the failed articles. `ANALYZE TABLE` runs at the end in either case, because MariaDB can ignore the vector index with stale statistics (see [Vector Search](../database/Vector-Search.md)). If the run replaced articles that were already stored, the vector index is also dropped and added again: after its chunks were deleted and inserted, searches were twice as slow until a rebuild (see [Vector Index State](../database/Index-State.md)).

## The stages

### 1. Fetch (`src/ingestion/mediawiki/`)

The MediaWiki client fetches the wikitext of one revision, then the article's categories and links. It handles rate limits, retries and pagination.

- **Snapshot (default).** For each article the client asks for the revision that was current at the `last_edit` time in the CSV (`rvstart` with `rvdir=older` and `rvlimit=1`). Every machine therefore loads the same text, and the questions in the ground truth that filter on edit dates keep their answers. `article_length` is the size of that revision.
- **Latest** (`make ingest-latest`) takes the current revision. Only this mode uses the [article cache](./Cache.md).
- Categories and links always describe the current page, because the API returns them only for the latest revision. Hidden maintenance categories ("Articles with short description" and the like) are skipped.
- The stored title is the one from the CSV, because the ground truth uses those titles. If MediaWiki returns another page ID for it, the article is rejected.

[MediaWiki client →](./mediawiki/Home.md)

### 2. Clean (`src/ingestion/cleaner.py`)

The rules come from [Data decisions](../data_decisions.md). With `mwparserfromhell` the cleaner removes templates and infoboxes, tables, `<ref>`, `<math>` and similar tags, file and image links, comments and leftover HTML, and drops the sections References, External links, See also, Further reading, Notes, Bibliography, Sources, Footnotes and Citations. Section headings stay as plain lines, and links keep their visible text.

### 3. Chunk (`src/ingestion/chunker.py`)

Chunks are counted in tokens of the embedding model's own tokenizer, so a chunk never exceeds what the model reads. Every chunk starts with `Title: <article title>`, and the splitter prefers paragraph, line and sentence boundaries.

| Config | Size | Overlap |
| --- | --- | --- |
| A (default) | 256 tokens | 32 |
| B | 512 tokens | 64 |
| C | one paragraph, at most 512 tokens | 0 |

In C a section heading is its own paragraph, so it becomes a very short chunk of its own.

### 4. Embed

`src.rag.embedder.Embedder` with `kind="passage"`, the same class the search uses with `kind="query"`, so questions and chunks always go through the same model (`BAAI/bge-base-en-v1.5`, 768 dimensions, normalised vectors).

### 5. Store (`src/database/repositories/articles.py`)

One transaction per article: the old chunks, categories and links are deleted (the schema has no `ON DELETE CASCADE`), the article row is inserted or updated, and the new rows are written, the vectors through `VEC_FromText`. Running the ingest again replaces articles instead of duplicating them.

## Separation of responsibilities

The MediaWiki client only retrieves source data and the cache only avoids repeated requests. Cleaning, chunking, embedding and storage are separate modules, so chunking and embedding experiments do not touch the source integration.
