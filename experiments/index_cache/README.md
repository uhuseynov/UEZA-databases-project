# Vector index cache and statistics experiments

Scripts that test the two causes of the vector index states described in [Vector Index State](../../docs/database/Index-State.md). Each changes one thing and measures with `python -m src.evaluation`, so the results land in `eval/results` like every other run.

| Script | What it changes | What it showed |
| --- | --- | --- |
| `run.py` | replaces every chunk (delete and insert in one transaction), then sets `mhnsw_max_cache_size` to 16 MB, 64 MB and 16 MB again; then rebuilds the index and measures 16 and 64 MB | with deleted vectors in the graph, a plain search took 72 ms with 16 MB and 20 ms with 64 MB |
| `graph_stats.py` | sets `n_rows` of the hidden graph table in `mysql.innodb_table_stats` to 0 (what InnoDB had after a rebuild), to the real count and back to 0, with a restart after each | after a restart, index recall follows that number: about 0.9 with 0, up to 1.00 with the real count |
| `refresh_check.py` | nothing; checks that `make reindex` now leaves correct statistics, then measures the shipped setup | `n_rows` 5,376 after the rebuild and after a restart; index recall@10 0.954 at `mhnsw_ef_search` 40 |

## Run

From the repository root, with the compose database up and all articles loaded:

```bash
uv run python experiments/index_cache/run.py
uv run python experiments/index_cache/graph_stats.py
uv run python experiments/index_cache/refresh_check.py
```

They need `docker compose` and run SQL as root inside the db container, with the container's own `MARIADB_ROOT_PASSWORD`. They restart the db container several times, so do not use the database meanwhile. Each puts back what it changed: `run.py` writes the same rows back and leaves the index rebuilt, `graph_stats.py` restores InnoDB's own statistics, and a restart resets the cache size to the value in `docker-compose.yml`.
