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
uv run python -m src.ingestion sync --dry-run   # which stored articles changed on Wikipedia
uv run python -m src.ingestion sync             # replace only those, at their latest revision
```

The settings come from `.env`: `ARTICLES_CSV_PATH`, `CHUNK_CONFIG` (A, B or C) and `INGESTION_SNAPSHOT`. The command is `uv run python -m src.ingestion ingest` (or `check`) with `--csv`, `--config`, `--latest` and `--limit`, for machines without `make`.

Each article is processed on its own, and a failure is logged and reported at the end without stopping the others. The command then exits with an error that lists the failed articles. `ANALYZE TABLE` runs at the end in either case, because MariaDB can ignore the vector index with stale statistics (see [Vector Search](../database/Vector-Search.md)). If the run replaced articles that were already stored, the vector index is also dropped and added again, so the graph does not keep the deleted chunks (see [Vector Index State](../database/Index-State.md)).

## Live sync

`sync` ([src/ingestion/sync.py](../../src/ingestion/sync.py)) keeps the stored articles up to date without loading all of them again:

1. It asks MediaWiki for the latest revision of every stored page, 50 pages per request and without the text (`prop=revisions`, `rvprop=ids|timestamp`, `pageids=...`). All 262 articles take 6 requests.
2. It compares each with `articles.revision_id` and lists the changed articles, and the ones that no longer exist.
3. It re-ingests only the changed articles, at their latest revision, through the same pipeline as the ingest: each article's metadata, categories, links, chunks and vectors are replaced in one transaction.
4. It runs `ANALYZE TABLE`, and rebuilds the vector index when the replaced chunks reach 25% of all chunks (`--rebuild-share`).

`--dry-run` stops after step 2 and does not load the embedding model. `--limit N` replaces at most N of the changed articles. Each run writes `eval/results/<timestamp>_sync.json` and `.md` with the changed articles and what was replaced.

Measured on 6 November 2026 ([dry run](../../eval/results/20261106-161320_sync-dry-run.md), [run](../../eval/results/20261106-172309_sync.md)):

- **184 of the 262 articles** had a newer revision than our snapshot, whose edit dates run from August 2025 to 4 October 2026 (half of them after 19 September 2026). Checking all 262 took 2.7 s.
- `sync --limit 5` replaced 5 articles: 300 chunks deleted (4.9% of 6,144), 302 inserted, in 132 s, about 26 s per article for fetching the text, categories and links and embedding the chunks on the CPU. The index was not rebuilt.
- `ingest --limit 5` then put the same 5 articles back to the snapshot (they are the first 5 rows of the CSV) and rebuilt the index (4.8 s), so the evaluation still runs on the snapshot.

**The rebuild threshold.** A replaced chunk leaves a deleted node in the HNSW graph until the next rebuild. Replacing 10%, 25% and 50% of the chunks changed neither the recall nor the speed measurably, and 100% made a search 3 ms slower ([Vector Index State](../database/Index-State.md#replacing-part-of-the-chunks)). A rebuild takes about 5 s. The default of 25% leaves room for the deleted nodes that earlier syncs left below the threshold, which `sync` does not count.

**The ground truth stays on the snapshot.** The questions with an edit-date filter were written for the snapshot dates, and 184 synced articles would move many of them. So the evaluation runs on the snapshot (`make ingest`), and `sync` is for a running service.

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
