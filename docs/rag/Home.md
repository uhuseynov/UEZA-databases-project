# Retrieval and RAG

This part turns a question into an answer: embed the question, find the closest chunks in MariaDB (optionally constrained by SQL filters), and let a language model answer from those chunks only, with the source articles.

```text
question
  │  Embedder (bge-base-en-v1.5, query prefix)          src/rag/embedder.py
  ▼
768-dim vector
  │  VectorRetriever: one SQL statement                  src/rag/retriever.py
  │    VEC_DISTANCE_COSINE + JOIN articles + filters
  ▼
top-k chunks with cosine distance
  │  RAGService: drop chunks further than                src/rag/service.py
  │    RAG_MAX_DISTANCE; none left → "not found"
  ▼
numbered passages
  │  ChatLLM: OpenAI-compatible chat API                 src/rag/llm.py
  │    prompt: answer only from passages, cite [n]       src/rag/prompt.py
  ▼
answer + cited source articles + timings
```

## The search statement

`VectorRetriever.retrieve()` builds a single statement. With every filter set it looks like this (values are always bound parameters, never part of the SQL text):

```sql
SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, c.chunk_index, c.chunk_text,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText(:query_vector)) AS distance
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE EXISTS (SELECT 1 FROM article_categories ac
              WHERE ac.article_id = a.id AND ac.category = :category)
  AND a.root_category = :root_category
  AND a.article_length >= :min_length
  AND a.article_length <= :max_length
  AND a.last_edit_date >= :edited_since
  AND a.last_edit_date < :edited_before
  AND EXISTS (SELECT 1 FROM article_links al
              JOIN articles src ON src.id = al.article_id
              WHERE src.title = :linked_from AND al.linked_title = a.title)
ORDER BY distance
LIMIT :k
```

| Filter | Meaning | Column |
|---|---|---|
| `category` | the article is in this Wikipedia category | `article_categories.category` |
| `root_category` | the dataset group it was collected from (`data/articles.csv`) | `articles.root_category` |
| `min_length`, `max_length` | inclusive bounds on the article size | `articles.article_length` |
| `edited_since` | last edit on or after this time | `articles.last_edit_date` |
| `edited_before` | last edit before this time | `articles.last_edit_date` |
| `linked_from` | the article with this title links to it | `article_links.linked_title` |

Why it is written this way:

- **One statement.** The semantic search and the relational filters run together, inside the database, consistent with the rows they read. A separate vector store would have to over-fetch and filter afterwards, or keep its own copy of the metadata in sync.
- **`EXISTS` for categories and links.** An article has many categories and links. A plain `JOIN` would return the same chunk once per matching category.
- **`ORDER BY distance`.** MariaDB uses the HNSW vector index only when the `ORDER BY` is the plain `VEC_DISTANCE_*` call (or its alias) with a `LIMIT`. The index uses `DISTANCE=cosine`, the same function as the query.
- **Exact search for measurements.** `retrieve(..., exact=True)` orders by `distance + 0`. The optimizer cannot use the index for an expression, so MariaDB scans every chunk and returns the true nearest neighbours. The evaluation uses this as the reference for the index recall. `retriever.explain()` returns the query plan, to confirm which of the two plans MariaDB chose.
- **`ef_search`.** `retrieve(..., ef_search=80)` sets `mhnsw_ef_search` (how many candidates the index examines) for that one query and resets it afterwards, because database connections are pooled and shared.

## Not found

The model is never asked when nothing relevant was found:

1. Chunks with a cosine distance above `RAG_MAX_DISTANCE` (default 0.5; 0 = identical, 2 = opposite) are dropped.
2. If no chunk is left, the answer is "not found" and the LLM is not called.
3. Otherwise the model is told to reply `NOT_FOUND` when the passages do not contain the answer, and that reply is reported as "not found" as well.

The threshold is a measured value, not a guess: `make eval` reports the closest-chunk distance for answerable and unanswerable questions and the cut-off that separates them best.

## The prompt

The system prompt tells the model to use only the numbered passages, to cite them as `[1]`, `[2]`, and to reply `NOT_FOUND` when they do not contain the answer. Each passage is introduced with its article title and part number. The sources returned with an answer are the articles of the cited passages, one entry per article.

## Language model

`ChatLLM` talks to any OpenAI-compatible `/chat/completions` endpoint. The default in `.env.example` is the OpenAI API. For a free local model, run [Ollama](https://ollama.com) and set:

```dotenv
LLM_API_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama
```

Search (`/search`) does not need a language model at all.

## API

Run the app with `make run` (or `make up` for the full Docker stack) and open <http://localhost:8000> for the web UI. The interactive API docs are at <http://localhost:8000/docs>.

**`GET /search`**: the closest chunks, no language model.

```bash
curl "http://localhost:8000/search?q=Which+method+averages+many+decision+trees&k=5&root_category=Core"
```

**`POST /ask`**: answer, sources, the chunks used and timings.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which model generates images by removing noise?", "k": 5,
       "filters": {"edited_since": "2026-01-01"}}'
```

Errors: invalid input → 422, database not reachable or schema missing → 503, language model failed → 502.

The embedding model is loaded on the first request (a few seconds, once). It loads in a worker thread, so the health check keeps answering.

## Configuration

| Variable | Default | Used for |
|---|---|---|
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-base-en-v1.5` | embedding model (must match the ingest) |
| `EMBEDDING_DIMENSION` | `768` | must match `VECTOR(768)` in `schema.sql` |
| `VECTOR_SEARCH_TOP_K` | `5` | default number of chunks |
| `RAG_MAX_DISTANCE` | `0.5` | not-found threshold |
| `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_TIMEOUT_SECONDS` | OpenAI | language model |

## Requirements on the schema

The retriever targets the four-table schema (`articles`, `article_categories`, `article_links`, `article_chunks`). The `root_category` filter also needs an `articles.root_category` column filled from `data/articles.csv`. Without it, only that filter fails; the others work.

## Tests

- `tests/unit/rag/`: query building (every filter is a bound parameter, an injection attempt never reaches the SQL text), the `ef_search` set/reset, the prompt, citations, the not-found paths and the LLM client against a mocked HTTP server.
- `tests/unit/api/`: the endpoints with a fake service, including the error codes.
- `tests/integration/rag/`: the real statement against MariaDB with a few inserted test articles (ordering, exact vs index, every filter). It is skipped when the database or the schema is not available.
