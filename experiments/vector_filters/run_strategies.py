#!/usr/bin/env python3
"""Which statement shapes let MariaDB use the vector index, and what do filters do to it?

Reuses the helpers of run_experiment.py and the same throwaway container. Every shape is
compared with the exact answer (a full scan, filtered), so "overlap" and "rows" are
measured, not assumed.
"""
import statistics

import run_experiment as base

K = base.K
OVERFETCH = (50, 200, 1000)   # how many nearest chunks the index returns before the filter


def shape(name, columns, vector, where, oversample=None):
    d = base.distance(vector)
    where_sql = f"WHERE {where}\n" if where else ""
    if name == "scan":        # the statement of src/rag/retriever.py (articles joined first)
        return base.statement(columns, vector, where, False)
    if name == "exact":       # same, but ORDER BY distance + 0 (never uses the vector index)
        return base.statement(columns, vector, where, True)
    if name == "single":      # one table, no join, no filter
        return (f"SELECT {columns}, {d} AS distance\nFROM article_chunks c\n"
                f"ORDER BY distance\nLIMIT {K}")
    if name == "first":       # chunks first, then the join and the filter
        return (f"SELECT {columns}, {d} AS distance\nFROM article_chunks c\n"
                f"STRAIGHT_JOIN articles a ON a.id = c.article_id\n{where_sql}"
                f"ORDER BY distance\nLIMIT {K}")
    if name == "overfetch":   # N nearest chunks from the index, then filter, then keep k
        return (f"SELECT {columns}, c.distance AS distance\n"
                f"FROM (SELECT c.id, c.article_id, {d} AS distance FROM article_chunks c "
                f"ORDER BY distance LIMIT {oversample}) c\n"
                f"JOIN articles a ON a.id = c.article_id\n{where_sql}"
                f"ORDER BY c.distance\nLIMIT {K}")
    raise ValueError(name)


def plan(vector, where, name, oversample=None):
    rows = base.run("EXPLAIN " + shape(name, "'X', c.id", vector, where, oversample) + ";")
    return " | ".join(f"{r[2]} {r[3]} key={r[5]} [{r[-1]}]" for r in rows)


def exact_ids(vector, where):
    rows = base.run(shape("exact", "'R', c.id", vector, where) + ";")
    return [int(r[1]) for r in rows if r[0] == "R"]


def timed(vector, where, name, oversample=None):
    parts = [shape(name, "'R', c.id", vector, where, oversample) + ";"]
    for _ in range(base.REPS):
        parts += ["SET @t = NOW(6);",
                  shape(name, "'X', c.id", vector, where, oversample) + ";",
                  "SELECT 'MS', TIMESTAMPDIFF(MICROSECOND, @t, NOW(6));"]
    rows = base.run("\n".join(parts))
    ids = [int(r[1]) for r in rows if r[0] == "R"]
    ms = statistics.median(int(r[1]) for r in rows if r[0] == "MS") / 1000
    return ids, ms


def evaluate(vectors, where, name, oversample=None):
    results = []
    for vector in vectors:
        truth = exact_ids(vector, where)
        ids, ms = timed(vector, where, name, oversample)
        results.append((len(ids), len(set(ids) & set(truth)) / max(1, len(truth)), ms))
    return (statistics.mean(r[0] for r in results),
            statistics.mean(r[1] for r in results),
            statistics.median(r[2] for r in results))


def main():
    print("MariaDB:", base.run("SELECT VERSION();")[0][0])
    total = int(base.run("SELECT COUNT(*) FROM article_chunks;")[0][0])
    print(f"Data: {total} chunks, k = {K}, median of {base.REPS} runs\n")

    first = base.query_vector(base.sample_chunks(None, True, 1)[0])
    print("PLANS WITHOUT A FILTER")
    print("  scan   (retriever.py)   :", plan(first, None, "scan"))
    print("  single (no join)        :", plan(first, None, "single"))
    print("  first  (chunks first)   :", plan(first, None, "first"))
    print("  overfetch 200           :", plan(first, None, "overfetch", 200))
    base.run("ANALYZE TABLE articles, article_chunks, article_categories, article_links;")
    print("AFTER ANALYZE TABLE")
    print("  scan   (retriever.py)   :", plan(first, None, "scan"))
    print("  single (no join)        :", plan(first, None, "single"))
    print("  first  (chunks first)   :", plan(first, None, "first"))
    print("  overfetch 200           :", plan(first, None, "overfetch", 200))
    print()

    print("CONTROL: no filter, 10 query vectors")
    vectors = [base.query_vector(i) for i in base.sample_chunks(None, True, 10)]
    for name in ("scan", "single"):
        rows, overlap, ms = evaluate(vectors, None, name)
        print(f"  {name:7}: rows {rows:4.1f}/{K}, overlap with exact {overlap:4.2f}, {ms:8.2f} ms")
    print()

    common = base.run("SELECT category FROM article_categories GROUP BY category "
                      "ORDER BY COUNT(*) DESC, category LIMIT 1;")
    rare = base.run("SELECT category FROM article_categories GROUP BY category "
                    "HAVING COUNT(*) = 1 ORDER BY category LIMIT 1;")
    filters = [
        ("length >= 50000", "a.article_length >= 50000"),
        ("group = Reinforcement learning", "a.root_category = 'Reinforcement learning'"),
    ]
    if common:
        filters.append((f"category = {common[0][0]} (most common)", base.category_filter(common[0][0])))
    if rare:
        filters.append((f"category = {rare[0][0]} (1 article)", base.category_filter(rare[0][0])))

    strategies = [("scan", None), ("first", None)] + [("overfetch", n) for n in OVERFETCH]
    summary = []
    for label, where in filters:
        chunks, articles = base.selectivity(where)
        if chunks == 0:
            continue
        print(f"== {label}: {chunks} chunks ({100 * chunks / total:.1f}%), {articles} articles")
        samples = {side: base.sample_chunks(where, inside, base.PER_SIDE)
                   for side, inside in (("inside", True), ("outside", False))}
        vectors = {side: [base.query_vector(i) for i in ids] for side, ids in samples.items()}
        probe = vectors["inside"][0]
        for name, n in strategies:
            tag = name if n is None else f"{name} {n}"
            print(f"   plan {tag:15}: {plan(probe, where, name, n)}")
        for side in ("inside", "outside"):
            for name, n in strategies:
                tag = name if n is None else f"{name} {n}"
                rows, overlap, ms = evaluate(vectors[side], where, name, n)
                summary.append((label, side, tag, rows, overlap, ms))
                print(f"   {side:7} {tag:15}: rows {rows:4.1f}/{K}, overlap with exact {overlap:4.2f}, {ms:8.2f} ms")
        print()

    print("SUMMARY (inside = the question is about articles that pass the filter, outside = it is not)")
    print(f"{'filter':44} {'side':8} {'shape':15} {'rows':>5} {'overlap':>7} {'ms':>8}")
    for label, side, tag, rows, overlap, ms in summary:
        print(f"{label:44} {side:8} {tag:15} {rows:5.1f} {overlap:7.2f} {ms:8.2f}")


if __name__ == "__main__":
    main()
