# Schema Management

[← Database](./Home.md) | [Documentation Home](../Home.md)

[`schema.sql`](../../schema.sql) is the only definition of the database schema: four tables (`articles`, `article_categories`, `article_links`, `article_chunks`) and the `VECTOR(768)` column with its HNSW index (`M=16`, `DISTANCE=cosine`). The vector DDL stays in plain SQL on purpose, so that every option of the native MariaDB vector index is visible. There is no migration tool and no ORM model layer; the application talks to the tables with SQL.

## How the schema is created

`docker-compose.yml` mounts `schema.sql` into the MariaDB image's `docker-entrypoint-initdb.d`. The image runs it **once, when the database volume is empty**. Nothing in the application (including the Docker entrypoint) creates or alters tables.

CI does the same: `docker compose up -d db --wait` starts an empty database, which loads `schema.sql`, before the integration tests run.

## Changing the schema

1. Edit `schema.sql`. This is what every new database gets.
2. An **existing** database does not see the change, because the init script only runs on an empty volume. Apply the same change to it by hand, with `ALTER TABLE` in `make db-shell`, or recreate it.
3. Recreating it is `make db-reset`, which deletes the volume **and all ingested data**. Loading the 262 articles again takes about an hour on a laptop CPU (`make ingest`), so prefer an `ALTER TABLE` for anything but a throwaway database.

## Limitations of this approach

- **No version tracking.** The database does not record which version of `schema.sql` it was created from. Compare with `SHOW CREATE TABLE article_chunks` (or `make ingest-check` for the data) when in doubt.
- **No automatic upgrades.** After pulling a change to `schema.sql`, existing databases must be altered by hand.
- **The vector index can drift from the file.** `make reindex M=32` rebuilds the index with another `M` in the running database only; `schema.sql` still says `M=16`. A new database gets the file's value, and `make reindex` (without `M`) keeps the current one.
- **The dimension is fixed in the table.** `VECTOR(768)` belongs to `BAAI/bge-base-en-v1.5`. Another model with another dimension needs a table created for it. The application never alters the column; `ingest` and `sync` stop with a clear message if `EMBEDDING_DIMENSION` and the column differ (see [Configuration](../architecture/Configuration.md#embedding-dimension)).
- **One vector index per table.** Comparing two models means two tables or two databases.

## Related code

- [`src/database/vectors.py`](../../src/database/vectors.py): the text, binary and hex forms of a vector, used by both the repository (inserts) and the retriever (searches).
- [`src/database/repositories/articles.py`](../../src/database/repositories/articles.py): `vector_index_definition`, `vector_column_dimension`, `check_dimension` and the index rebuild.
