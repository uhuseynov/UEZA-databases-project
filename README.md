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

Four tables:

- `articles`: one row per Wikipedia article, with the metadata we filter on.
- `article_categories`: the categories of each article, one row per article and category.
- `article_links`: the outgoing links of each article, stored as the title of the linked article.
- `article_chunks`: the text chunks and their vectors.

```sql
CREATE TABLE articles (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    page_id        INT UNSIGNED NOT NULL UNIQUE,      -- MediaWiki page id
    title          VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL UNIQUE,
    url            VARCHAR(500),
    root_category  VARCHAR(100),                      -- dataset group, from data/articles.csv
    article_length INT UNSIGNED NOT NULL,             -- size reported by MediaWiki
    revision_id    BIGINT UNSIGNED NOT NULL,          -- stored revision, compared during sync
    last_edit_date DATETIME NOT NULL,                 -- time of that revision (UTC)
    INDEX idx_articles_root_category (root_category),
    INDEX idx_articles_article_length (article_length),
    INDEX idx_articles_last_edit_date (last_edit_date)
);

CREATE TABLE article_categories (
    article_id INT NOT NULL,
    category   VARCHAR(255) NOT NULL,
    PRIMARY KEY (article_id, category),
    INDEX idx_article_categories_category (category),
    CONSTRAINT fk_categories_article FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE TABLE article_links (
    article_id   INT NOT NULL,                        -- the article that contains the link
    linked_title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    PRIMARY KEY (article_id, linked_title),
    INDEX idx_article_links_linked_title (linked_title),
    CONSTRAINT fk_links_article FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE TABLE article_chunks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    article_id  INT NOT NULL,
    chunk_index INT NOT NULL,                         -- position in the article, from 0
    chunk_text  TEXT NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    UNIQUE KEY uq_chunks_position (article_id, chunk_index),
    CONSTRAINT fk_chunks_article FOREIGN KEY (article_id) REFERENCES articles(id),
    VECTOR INDEX (embedding) M=16 DISTANCE=cosine
);
```

Where the columns come from:

| Column | Filter name in `docs/data_decisions.md` | Source |
| --- | --- | --- |
| `articles.page_id` | | MediaWiki client: `page_id` |
| `articles.title` | | MediaWiki client: `title` |
| `articles.root_category` | | `root_category` column of `data/articles.csv` (not known to MediaWiki) |
| `articles.article_length` | `article_length` | MediaWiki client: `length` |
| `articles.last_edit_date` | `last_edit_date` | MediaWiki client: `last_modified` |
| `articles.revision_id` | | MediaWiki client: `revision_id` (sync compares it to detect changes) |
| `article_categories.category` | `category` | MediaWiki client: `categories` |
| `article_links.linked_title` | `outgoing_links` | MediaWiki client: `links` |

**Why it's built this way:**

- An article has many categories, so they get their own table. Filtering by category is an `EXISTS` check, and an article never appears twice in the results.
- `root_category` is the dataset group an article was collected from, such as "Deep learning". MediaWiki doesn't know it, so the loader copies it from `data/articles.csv`. The search page's "Dataset group" filter uses it.
- The MediaWiki client returns links as article titles, and most of them point outside our dataset. Storing the title lets us ask "linked from article X" with a join on `articles.title`. It also keeps working when articles are loaded in any order. Links that point to a redirect title will not match.
- Titles are compared case-sensitively (`utf8mb4_bin`), because Wikipedia treats `AI` and `Ai` as different articles. This also means the "linked from" filter needs the exact title.
- `revision_id` lets the sync job see whether an article changed since it was loaded.
- `chunk_index` records the order of chunks inside an article. Together with `article_id` it is unique.
- `embedding` is `NOT NULL` because MariaDB only allows a vector index on a column that cannot be empty.
- The index uses `DISTANCE=cosine`. The default is euclidean, and a search with `VEC_DISTANCE_COSINE` cannot use a euclidean index, so it would scan the whole table.
- 768 dimensions fits two of our three candidate embedding models. A vector index is tied to one dimension, and a table can have only one, so a model with a different size needs its own table.
- `article_chunks` is only ever the child side of a foreign key. MariaDB has an open bug (MDEV-35241) about dropping a table with a vector index when other tables reference it, so we avoid that setup.

Example: the 5 closest chunks, only from articles in the category "Machine learning" that are longer than 50,000 and edited in 2026.

```sql
SELECT c.id, c.chunk_text, a.title
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE a.article_length > 50000
  AND a.last_edit_date >= '2026-01-01'
  AND EXISTS (SELECT 1 FROM article_categories ac
              WHERE ac.article_id = a.id AND ac.category = 'Machine learning')
ORDER BY VEC_DISTANCE_COSINE(c.embedding, @query_vector)
LIMIT 5;
```

The application builds the same kind of statement in `src/rag/retriever.py`. See [Retrieval and RAG](./docs/rag/Home.md).

Keep the `ORDER BY` on the bare distance function (or its alias). Wrapping it in an expression makes MariaDB ignore the vector index.

## Asking Questions

Start the app with `make run` (or the whole stack with `make up`) and open <http://localhost:8000>. The page sends the question and the optional SQL filters (category, dataset group, length, edit date, linked from) to the API:

- `GET /search?q=...`: the closest chunks and their cosine distance, no language model needed
- `POST /ask`: an answer written only from the retrieved chunks, with the source articles, or "not found"

Any OpenAI-compatible model works, including a free local one through Ollama. See [Retrieval and RAG](./docs/rag/Home.md) for the search statement, the not-found logic and the configuration.

## Evaluation

```bash
make eval        # Recall@1/3/5/10, MRR, latency over repeated runs, not-found analysis
make eval-sweep  # index recall and latency for several mhnsw_ef_search values vs. exact search
```

Results are saved in `eval/results/` as JSON and Markdown. The method and the metric definitions are in [Evaluation](./docs/evaluation/Home.md).
