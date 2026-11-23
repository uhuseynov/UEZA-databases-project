# Data Model

[← Database](./Home.md) | [Documentation Home](../Home.md)

Four tables, created by [schema.sql](../../schema.sql):

- `articles`: one row per article, with the metadata we filter on (`root_category`, `article_length`, `last_edit_date`) and the `revision_id` the sync compares.
- `article_categories`: one row per article and category.
- `article_links`: one row per article and outgoing link, stored as the linked title.
- `article_chunks`: the text chunks and their vectors:

```sql
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

**Why it's built this way:**

- An article has many categories, so they get their own table. Filtering by category is an `EXISTS` check, and an article never appears twice in the results.
- `root_category` is the dataset group an article was collected from, such as "Deep learning". MediaWiki doesn't know it, so the loader copies it from `data/articles.csv`.
- Links are stored as titles, because most of them point outside our dataset. "Linked from article X" is then a join on `articles.title`, and it works whatever order the articles are loaded in.
- Titles are compared case-sensitively (`utf8mb4_bin`), because Wikipedia treats `AI` and `Ai` as different articles.
- `embedding` is `NOT NULL` because MariaDB only allows a vector index on a column that cannot be empty.
- The index uses `DISTANCE=cosine`. The default is euclidean, and a search with `VEC_DISTANCE_COSINE` cannot use a euclidean index.
- `article_chunks` is only ever the child side of a foreign key. MariaDB has an open bug (MDEV-35241) about dropping a table with a vector index when other tables reference it.

Where each column comes from is listed in [Database](Home.md).
