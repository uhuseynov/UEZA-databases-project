-- Vector search in MariaDB, in one file: the technique behind UEZA on ten hand-made chunks.
--
-- Runs in any MariaDB 11.8 or later (developed with 12.3.3). With this repository's database:
--
--   make example
--
-- or, without make (PowerShell or any shell):
--
--   Get-Content examples/vector_search.sql | docker compose exec -T db mariadb --table -vvv -uueza -pueza_password ueza_db
--   docker compose exec -T db mariadb --table -vvv -uueza -pueza_password ueza_db < examples/vector_search.sql
--
-- It creates three tables of its own (example_articles, example_links, example_chunks), runs
-- the queries and drops the tables again, so the project's data is not touched.
--
-- The vectors have 4 dimensions instead of 768, so you can read them. Think of the dimensions
-- as "machine learning", "images", "language" and "games": a chunk about word embeddings is
-- mostly "language", one about AlphaGo mostly "games". The real project computes 768 of them
-- with an embedding model (src/rag/embedder.py), and the SQL is the same.
--
-- tests/integration/test_example_sql.py runs this file and checks its results, so the order of
-- the queries below is part of that test.

DROP TABLE IF EXISTS example_chunks;
DROP TABLE IF EXISTS example_links;
DROP TABLE IF EXISTS example_articles;


-- 1. Tables. The vectors sit next to the article metadata, in an ordinary InnoDB table.

CREATE TABLE example_articles (
    id             INT PRIMARY KEY,
    title          VARCHAR(255) NOT NULL UNIQUE,
    root_category  VARCHAR(100) NOT NULL,
    article_length INT UNSIGNED NOT NULL,
    last_edit_date DATETIME NOT NULL
);

CREATE TABLE example_links (
    article_id   INT NOT NULL,                  -- the article that contains the link
    linked_title VARCHAR(255) NOT NULL,         -- the title it links to
    PRIMARY KEY (article_id, linked_title),
    FOREIGN KEY (article_id) REFERENCES example_articles(id)
);

-- A VECTOR(n) column must be NOT NULL to be indexed. DISTANCE=cosine has to match the
-- function the queries use (VEC_DISTANCE_COSINE), the default is euclidean. M is the number of
-- links per node in the HNSW graph: UEZA uses 16 (docs/database/Choosing-M.md says why).
CREATE TABLE example_chunks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    article_id  INT NOT NULL,
    chunk_index INT NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   VECTOR(4) NOT NULL,
    FOREIGN KEY (article_id) REFERENCES example_articles(id),
    VECTOR INDEX (embedding) M=16 DISTANCE=cosine
);


-- 2. Data. VEC_FromText turns '[x, y, ...]' into the binary value of a VECTOR column.

INSERT INTO example_articles VALUES
    (1, 'Random forest',                'Machine learning',             42000, '2026-05-02'),
    (2, 'Convolutional neural network', 'Computer vision',              98000, '2026-08-14'),
    (3, 'Image segmentation',           'Computer vision',              31000, '2025-11-20'),
    (4, 'Word embedding',               'Natural language processing',  27000, '2026-02-09'),
    (5, 'Large language model',         'Natural language processing', 161000, '2026-09-21'),
    (6, 'AlphaGo',                      'Reinforcement learning',       64000, '2026-06-30');

INSERT INTO example_links VALUES
    (5, 'Word embedding'),
    (5, 'AlphaGo'),
    (6, 'Convolutional neural network');

INSERT INTO example_chunks (article_id, chunk_index, chunk_text, embedding) VALUES
    (1, 0, 'Random forests average many decision trees.',                      VEC_FromText('[0.9, 0.1, 0.1, 0.1]')),
    (1, 1, 'Each tree is trained on a bootstrap sample of the data.',           VEC_FromText('[0.85, 0.05, 0.05, 0.2]')),
    (2, 0, 'Convolutional layers slide small filters over an image.',           VEC_FromText('[0.3, 0.9, 0.1, 0.1]')),
    (2, 1, 'Pooling layers reduce the resolution of the feature maps.',         VEC_FromText('[0.2, 0.85, 0.05, 0.05]')),
    (3, 0, 'Segmentation assigns a class to every pixel of an image.',          VEC_FromText('[0.1, 0.95, 0.1, 0.0]')),
    (4, 0, 'Word embeddings map words to vectors, similar meanings close by.',  VEC_FromText('[0.3, 0.0, 0.9, 0.0]')),
    (5, 0, 'A large language model predicts the next token of a text.',         VEC_FromText('[0.4, 0.1, 0.85, 0.1]')),
    (5, 1, 'Prompt injection hides instructions in the text a model reads.',    VEC_FromText('[0.2, 0.0, 0.8, 0.3]')),
    (6, 0, 'AlphaGo combined a policy network with Monte Carlo tree search.',   VEC_FromText('[0.4, 0.2, 0.0, 0.9]')),
    (6, 1, 'In 2016 AlphaGo defeated Lee Sedol, a top professional Go player.', VEC_FromText('[0.2, 0.1, 0.1, 0.95]'));


-- 3. The nearest chunks to a question about language. The query vector stands in for the
--    embedding of the question. The vector index is used for ORDER BY <bare distance> LIMIT n.
--    Expected: Word embedding, then the two Large language model chunks.

SELECT a.title, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.2, 0.0, 1.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
ORDER BY distance
LIMIT 3;


-- 4. The same search, the way UEZA writes it: the 10 nearest chunks first in a derived table,
--    so the vector index works on article_chunks alone, then the join. With the join in the
--    same SELECT, MariaDB searched far more of the graph than needed on the real data
--    (docs/database/Vector-Search.md). The query vector is also written in its binary form:
--    MariaDB evaluates VEC_FromText('...') again for every row it compares, a hex literal
--    only once. HEX(VEC_FromText(...)) prints that literal: 4 little-endian float32 values.

SELECT HEX(VEC_FromText('[0.2, 0.0, 1.0, 0.0]')) AS binary_value;

SELECT a.title, n.chunk_index, n.distance
FROM (
    SELECT article_id, chunk_index,
           VEC_DISTANCE_COSINE(embedding, X'CDCC4C3E000000000000803F00000000') AS distance
    FROM example_chunks
    ORDER BY distance
    LIMIT 3
) AS n
JOIN example_articles a ON a.id = n.article_id
ORDER BY n.distance;


-- 5. Semantic search and ordinary SQL in one statement. A question about images, first over
--    every article, then only over articles longer than 50,000 characters: Image segmentation
--    (31,000) drops out. On the real data, MariaDB planned filtered searches from the filter
--    and computed the distance for the matching rows only, so they were exact
--    (docs/database/Vector-Search.md).

SELECT a.title, a.article_length, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.1, 1.0, 0.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
ORDER BY distance
LIMIT 3;

SELECT a.title, a.article_length, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.1, 1.0, 0.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
WHERE a.article_length > 50000
ORDER BY distance
LIMIT 3;


-- 6. A filter that is a join: only articles that "Large language model" links to. A
--    separate vector store would need the links copied into its metadata and kept in sync.
--    Expected: the two AlphaGo chunks, then Word embedding.

SELECT a.title, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.0, 0.0, 0.0, 1.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
WHERE EXISTS (
    SELECT 1
    FROM example_links l
    JOIN example_articles linking ON linking.id = l.article_id
    WHERE linking.title = 'Large language model' AND l.linked_title = a.title
)
ORDER BY distance
LIMIT 3;


-- 7. Exact search, for comparison. Any expression around the distance (here + 0) keeps
--    MariaDB from using the vector index, so every row is compared: the baseline UEZA measures
--    the index against. On ten rows both give the same answer as query 3.

SELECT a.title, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.2, 0.0, 1.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
ORDER BY distance + 0
LIMIT 3;


-- 8. The vectors are transactional, like every other column. Inside the transaction the new
--    chunk is the nearest one. After ROLLBACK it is gone from the index too.

START TRANSACTION;

INSERT INTO example_articles VALUES
    (7, 'Transformer (deep learning)', 'Natural language processing', 120000, '2026-10-01');

INSERT INTO example_chunks (article_id, chunk_index, chunk_text, embedding) VALUES
    (7, 0, 'A transformer relates every token of a text to every other token.',
     VEC_FromText('[0.25, 0.0, 1.0, 0.0]'));

SELECT a.title, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.2, 0.0, 1.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
ORDER BY distance
LIMIT 1;

ROLLBACK;

SELECT a.title, c.chunk_index,
       VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('[0.2, 0.0, 1.0, 0.0]')) AS distance
FROM example_chunks c
JOIN example_articles a ON a.id = c.article_id
ORDER BY distance
LIMIT 1;


-- 9. Clean up. example_chunks goes first: it holds the vector index, and MariaDB has an open
--    bug (MDEV-35241) about dropping a table with a vector index that other tables reference.

DROP TABLE example_chunks;
DROP TABLE example_links;
DROP TABLE example_articles;
