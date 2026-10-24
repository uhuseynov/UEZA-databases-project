# Vector filter experiments

Scripts that measure how MariaDB's vector index behaves with SQL filters and with different index parameters. The results and conclusions are in [Vector Search and Index Parameters](../../docs/database/Vector-Search.md).

The data is generated: real article metadata (title, length, edit date, dataset group, category) from `data/articles.csv`, and generated 768-dimensional vectors. Everything runs in a throwaway MariaDB container with password `test`. Nothing touches the project's compose stack.

## Requirements

- Python 3 with numpy
- Podman or Docker (use `CONTAINER_ENGINE=docker` for Docker, and replace `podman` in the commands below)
- this repository (`schema.sql` and `data/articles.csv`)

## Run

From the repository root:

```bash
mkdir -p ~/ueza-exp
python3 experiments/vector_filters/generate_data.py data/articles.csv ~/ueza-exp

podman rm -f ueza-exp
podman run -d --name ueza-exp \
  -e MARIADB_ROOT_PASSWORD=test -e MARIADB_DATABASE=ueza_db \
  -v "$PWD/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro,Z" \
  -v "$HOME/ueza-exp:/work:ro,Z" \
  docker.io/library/mariadb:12.3.3 --secure-file-priv=

# wait until the log shows "ready for connections" twice
podman logs ueza-exp 2>&1 | grep -c "ready for connections"

cat > ~/ueza-exp/load-chunks.sql << 'SQL'
LOAD DATA INFILE '/work/chunks.tsv' INTO TABLE article_chunks
  FIELDS TERMINATED BY '\t' LINES TERMINATED BY '\n'
  (article_id, chunk_index, chunk_text, @vec)
  SET embedding = VEC_FromText(@vec);
SQL

podman exec -i ueza-exp mariadb -u root -ptest --default-character-set=utf8mb4 ueza_db < ~/ueza-exp/load-meta.sql
podman exec -i ueza-exp mariadb -u root -ptest ueza_db < ~/ueza-exp/load-chunks.sql

python3 experiments/vector_filters/run_experiment.py
python3 experiments/vector_filters/run_strategies.py
python3 experiments/vector_filters/run_index_params.py
```

Remove the container afterwards with `podman rm -f ueza-exp`.

## Scripts

| Script | What it does |
| --- | --- |
| `generate_data.py` | writes the articles, categories, links and chunk vectors to load |
| `run_experiment.py` | plans and timings of the retriever statement with filters (run it right after loading to see the stale-statistics plans) |
| `run_strategies.py` | compares statement shapes (retriever statement, single table, chunks first, nearest-N-then-filter) and runs `ANALYZE TABLE` |
| `run_index_params.py` | rebuilds the index for `M` = 6, 8 and 16 and sweeps `mhnsw_ef_search`; it leaves the index at `M=16` |

## Results

The raw output of the three runs is in `results/`. The first run was taken before `ANALYZE TABLE`, which is why its plans scan the whole table.
