#!/usr/bin/env python3
"""How does MariaDB's vector index behave when SQL filters are added?

Talks to the throwaway container with the `<engine> exec ... mariadb` client, so it needs
nothing but Python and numpy. The search statement has the same shape as
src/rag/retriever.py: VEC_DISTANCE_COSINE in the SELECT list, ORDER BY the alias
(index search) or ORDER BY distance + 0 (exact search, a full scan), LIMIT k.

Environment: CONTAINER_ENGINE (default podman, use docker if you run Docker) and
CONTAINER_NAME (default ueza-exp).
"""
import json
import os
import statistics
import subprocess
import sys

import numpy as np

ENGINE = os.environ.get("CONTAINER_ENGINE", "podman")
CONTAINER = os.environ.get("CONTAINER_NAME", "ueza-exp")
K = 10               # chunks per search
REPS = 3             # timing repetitions per statement (median is reported)
PER_SIDE = 5         # query vectors per filter: 5 inside the filter, 5 outside it
NOISE = 0.6          # noise added to a stored chunk vector to make a "new" query vector
FULL_COLUMNS = "c.id AS chunk_id, a.id AS article_id, a.title, a.url, c.chunk_index, c.chunk_text"

rng = np.random.default_rng(7)


def run(sql):
    process = subprocess.run(
        [ENGINE, "exec", "-i", CONTAINER, "mariadb", "-u", "root", "-ptest",
         "--batch", "--skip-column-names", "--default-character-set=utf8mb4", "ueza_db"],
        input=sql, capture_output=True, text=True,
    )
    if process.returncode != 0:
        sys.exit(f"SQL error:\n{process.stderr}\n--- statement (start) ---\n{sql[:600]}")
    return [line.split("\t") for line in process.stdout.splitlines() if line]


def esc(value):
    return value.replace("\\", "\\\\").replace("'", "''")


def vec_text(values):
    return "[" + ",".join(f"{x:.8f}" for x in values) + "]"


def distance(vector):
    return f"VEC_DISTANCE_COSINE(c.embedding, VEC_FromText('{vector}'))"


def statement(columns, vector, where, exact):
    d = distance(vector)
    order = f"{d} + 0" if exact else "distance"
    where_sql = f"WHERE {where}\n" if where else ""
    return (f"SELECT {columns}, {d} AS distance\n"
            "FROM article_chunks c\nJOIN articles a ON a.id = c.article_id\n"
            f"{where_sql}ORDER BY {order}\nLIMIT {K}")


def query_vector(chunk_id):
    text = run(f"SELECT VEC_ToText(embedding) FROM article_chunks WHERE id = {chunk_id};")[0][0]
    base = np.array(json.loads(text))
    return vec_text(base + rng.normal(size=base.shape) * NOISE)


def sample_chunks(where, inside, n):
    condition = "" if where is None else (f"WHERE ({where})" if inside else f"WHERE NOT ({where})")
    rows = run("SELECT c.id FROM article_chunks c JOIN articles a ON a.id = c.article_id "
               f"{condition} ORDER BY RAND(42) LIMIT {n};")
    return [int(r[0]) for r in rows]


def selectivity(where):
    condition = f"WHERE {where}" if where else ""
    row = run("SELECT COUNT(*), COUNT(DISTINCT a.id) FROM article_chunks c "
              f"JOIN articles a ON a.id = c.article_id {condition};")[0]
    return int(row[0]), int(row[1])


def measure(vector, where):
    parts = [statement("'IDX', c.id", vector, where, False) + ";",
             statement("'EXA', c.id", vector, where, True) + ";"]
    for tag, exact in (("MS_IDX", False), ("MS_EXA", True)):
        for _ in range(REPS):
            parts += ["SET @t = NOW(6);",
                      statement("'X', c.id", vector, where, exact) + ";",
                      f"SELECT '{tag}', TIMESTAMPDIFF(MICROSECOND, @t, NOW(6));"]
    rows = run("\n".join(parts))
    idx_ids = [int(r[1]) for r in rows if r[0] == "IDX"]
    exa_ids = [int(r[1]) for r in rows if r[0] == "EXA"]
    ms_idx = statistics.median(int(r[1]) for r in rows if r[0] == "MS_IDX") / 1000
    ms_exa = statistics.median(int(r[1]) for r in rows if r[0] == "MS_EXA") / 1000
    return idx_ids, exa_ids, ms_idx, ms_exa


def category_filter(category):
    return ("EXISTS (SELECT 1 FROM article_categories ac "
            f"WHERE ac.article_id = a.id AND ac.category = '{esc(category)}')")


def main():
    print("MariaDB:", run("SELECT VERSION();")[0][0])
    for name, value in run("SHOW VARIABLES LIKE 'mhnsw%';"):
        print(f"  {name} = {value}")
    total_chunks = int(run("SELECT COUNT(*) FROM article_chunks;")[0][0])
    total_articles = int(run("SELECT COUNT(*) FROM articles;")[0][0])
    print(f"Data: {total_articles} articles, {total_chunks} chunks, k = {K}, "
          f"{REPS} timing repetitions (median), {PER_SIDE}+{PER_SIDE} query vectors per filter\n")

    common = run("SELECT category FROM article_categories GROUP BY category "
                 "ORDER BY COUNT(*) DESC, category LIMIT 1;")
    rare = run("SELECT category FROM article_categories GROUP BY category "
               "HAVING COUNT(*) = 1 ORDER BY category LIMIT 1;")
    filters = [
        ("no filter", None),
        ("length >= 50000", "a.article_length >= 50000"),
        ("group = Reinforcement learning", "a.root_category = 'Reinforcement learning'"),
    ]
    if common:
        filters.append((f"category = {common[0][0]} (most common)", category_filter(common[0][0])))
    if rare:
        filters.append((f"category = {rare[0][0]} (1 article)", category_filter(rare[0][0])))

    summary = []
    for label, where in filters:
        chunks, articles = selectivity(where)
        if chunks == 0:
            print(f"== {label}: no chunk passes this filter, skipped\n")
            continue
        sides = [("inside", True)] if where is None else [("inside", True), ("outside", False)]
        samples = {side: sample_chunks(where, inside, PER_SIDE if where else 2 * PER_SIDE)
                   for side, inside in sides}
        vectors = {side: [query_vector(i) for i in ids] for side, ids in samples.items()}

        print(f"== {label}: {chunks} chunks ({100 * chunks / total_chunks:.1f}%), {articles} articles")
        first_vector = next(v for vs in vectors.values() for v in vs)
        for mode, exact in (("index", False), ("exact", True)):
            plan = run("EXPLAIN " + statement(FULL_COLUMNS, first_vector, where, exact) + ";")
            for row in plan:
                print(f"   EXPLAIN {mode:5}: table={row[2]} type={row[3]} key={row[5]} "
                      f"rows={row[8]} extra={row[-1]}")

        for side, _ in sides:
            results = [measure(v, where) for v in vectors[side]]
            rows_returned = statistics.mean(len(r[0]) for r in results)
            recall = statistics.mean(len(set(r[0]) & set(r[1])) / max(1, len(r[1])) for r in results)
            ms_idx = statistics.median(r[2] for r in results)
            ms_exa = statistics.median(r[3] for r in results)
            summary.append((label, side, chunks, rows_returned, recall, ms_idx, ms_exa))
            print(f"   query vectors {side:7}: index returns {rows_returned:4.1f}/{K} rows, "
                  f"overlap with exact top {K} = {recall:4.2f}, "
                  f"index {ms_idx:7.2f} ms, exact {ms_exa:7.2f} ms")
        print()

    print("SUMMARY (inside = the query is about articles that pass the filter, outside = it is not)")
    print(f"{'filter':44} {'side':8} {'chunks':>7} {'rows':>5} {'recall':>6} {'idx ms':>8} {'exact ms':>9}")
    for label, side, chunks, rows_returned, recall, ms_idx, ms_exa in summary:
        print(f"{label:44} {side:8} {chunks:7d} {rows_returned:5.1f} {recall:6.2f} {ms_idx:8.2f} {ms_exa:9.2f}")


if __name__ == "__main__":
    main()
