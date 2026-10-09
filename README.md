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
    article_length INT UNSIGNED NOT NULL,             -- size reported by MediaWiki
    revision_id    BIGINT UNSIGNED NOT NULL,          -- stored revision, compared during sync
    last_edit_date DATETIME NOT NULL,                 -- time of that revision (UTC)
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
    VECTOR INDEX (embedding) DISTANCE=cosine
);
```

Where the columns come from:

| Column | Filter name in `docs/data_decisions.md` | Field from the MediaWiki client |
| --- | --- | --- |
| `articles.page_id` | | `page_id` |
| `articles.title` | | `title` |
| `articles.article_length` | `article_length` | `length` |
| `articles.last_edit_date` | `last_edit_date` | `last_modified` |
| `articles.revision_id` | | `revision_id` (sync compares it to detect changes) |
| `article_categories.category` | `category` | `categories` |
| `article_links.linked_title` | `outgoing_links` | `links` |

**Why it's built this way:**

- An article has many categories, so they get their own table. Filtering by category is an `EXISTS` check, and an article never appears twice in the results.
- The MediaWiki client returns links as article titles, and most of them point outside our dataset. Storing the title lets us ask "linked from article X" with a join on `articles.title`. It also keeps working when articles are loaded in any order. Links that point to a redirect title will not match.
- Titles are compared case-sensitively (`utf8mb4_bin`), because Wikipedia treats `AI` and `Ai` as different articles.
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

Example: the same search, restricted to articles that the article "Machine learning" links to.

```sql
SELECT c.id, c.chunk_text, a.title
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE a.title IN (SELECT l.linked_title
                  FROM article_links l
                  JOIN articles src ON src.id = l.article_id
                  WHERE src.title = 'Machine learning')
ORDER BY VEC_DISTANCE_COSINE(c.embedding, @query_vector)
LIMIT 5;
```

Keep the `ORDER BY` on the bare distance function. Wrapping it in an expression makes MariaDB ignore the vector index.
