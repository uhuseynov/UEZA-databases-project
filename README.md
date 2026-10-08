A project for area 4, "Vector search and RAG, natively" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

# UEZA Databases Project

Native vector search and RAG evaluation using MariaDB.

## What This Project Is

We are building a question-answering system over Wikipedia articles. Instead of using a separate vector database, the article text, its metadata and the search vectors all live inside MariaDB, using its native `VECTOR` type.

The stages are:

1. Collect Wikipedia articles and split them into chunks.
2. Turn each chunk into a vector with an embedding model.
3. Store the chunks and vectors in MariaDB.
4. Answer questions by finding the closest chunks with a vector search, optionally filtered with normal SQL.
5. Give those chunks to an LLM, and measure how good the retrieval is.

Which stages are finished is tracked in [docs/Home.md](./docs/Home.md).

## Team

- **Aaryadeep**: database schema, vector column and index, similarity search and filtered SQL queries
- **Zeynalabidin**: data decisions (topic, article list, metadata, cleaning and chunking rules) and the ground-truth question set
- **Egehan**: ingestion and live sync (MediaWiki client, chunking, embeddings, loading into MariaDB), the FAISS comparison baseline, the Docker Compose stack and CI
- **Umid** (team lead): repo structure, RAG pipeline and backend, evaluation, final integration

## Setup

```bash
make setup
```

See [docs/Home.md](./docs/Home.md) for architecture, database, ingestion, Docker, Git workflow, and CI documentation.

The database is MariaDB 12.3.3, started through `docker-compose.yml`. If you use Podman on Windows instead of Docker, see [Installing Podman on Windows](./docs/database/podman.md).

## Database Schema

The schema lives in [schema.sql](./schema.sql). MariaDB runs it automatically the first time the database container starts with an empty data volume.

Two tables: one for articles, one for the text chunks and their vectors.

```sql
CREATE TABLE articles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255),
    category VARCHAR(100),
    url VARCHAR(500),
    edited_at DATE
);

CREATE TABLE article_chunks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    article_id INT,
    chunk_text TEXT,
    embedding VECTOR(768) NOT NULL,
    FOREIGN KEY (article_id) REFERENCES articles(id),
    VECTOR INDEX (embedding) DISTANCE=cosine
);
```

**Why it's split this way:** `articles` holds the basic facts about each article, so results can be filtered by things like category or date using normal SQL. `article_chunks` holds the actual text pieces and their vectors, linked back to the article they came from through `article_id`. This split is what makes it possible to combine a normal SQL filter and a vector search in a single query.

**Why the vector column and index look like this:**

- `embedding` is `NOT NULL` because MariaDB only allows a vector index on a column that cannot be empty.
- The index uses `DISTANCE=cosine`. The default is euclidean, and a search with `VEC_DISTANCE_COSINE` cannot use a euclidean index, so it would scan the whole table.
- 768 dimensions is a placeholder until the embedding model is chosen. It must match the model's output size exactly.
- A table can have only one vector index.

Example query: the 5 closest chunks to a given vector, filtered by category and date with ordinary SQL.

```sql
SELECT c.id, c.chunk_text, a.title
FROM article_chunks c
JOIN articles a ON c.article_id = a.id
WHERE a.category = 'physics' AND a.edited_at > '2024-01-01'
ORDER BY VEC_DISTANCE_COSINE(c.embedding, @query_vector)
LIMIT 5;
```

Keep the `ORDER BY` on the bare distance function. Wrapping it in an expression makes MariaDB ignore the vector index.
