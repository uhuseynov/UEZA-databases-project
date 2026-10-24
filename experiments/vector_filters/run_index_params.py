#!/usr/bin/env python3
"""Index parameters: how do M and mhnsw_ef_search trade accuracy against speed?

For each M the vector index is rebuilt (the data stays), then three statement shapes are run
for several mhnsw_ef_search values and compared with the exact answer:
  single : one table, no join (the plain vector search)
  scan   : the statement of src/rag/retriever.py, no filter
  first  : chunks first (STRAIGHT_JOIN) with a weak filter (length >= 50000), where
           MariaDB would otherwise choose the exact full scan
Needs the container of run_experiment.py with data loaded.
"""
import statistics
import time

import run_experiment as base
import run_strategies as strat

M_VALUES = (6, 8, 16)
EF_VALUES = (10, 20, 40, 80, 160)
QUERIES = 20
WEAK = "a.article_length >= 50000"
CASES = [("single", None, "single, no filter"),
         ("scan", None, "retriever.py, no filter"),
         ("first", WEAK, "chunks first, length >= 50000")]


def rebuild(m):
    start = time.perf_counter()
    base.run("ALTER TABLE article_chunks DROP INDEX embedding;")
    base.run(f"ALTER TABLE article_chunks ADD VECTOR INDEX (embedding) M={m} DISTANCE=cosine;")
    seconds = time.perf_counter() - start
    base.run("ANALYZE TABLE articles, article_chunks, article_categories, article_links;")
    return seconds


def index_definition():
    text = base.run("SHOW CREATE TABLE article_chunks;")[0][1]
    return " ".join(p.strip() for p in text.split("\\n") if "VECTOR KEY" in p)


def timed(vector, where, name, ef):
    parts = [f"SET SESSION mhnsw_ef_search = {ef};",
             strat.shape(name, "'R', c.id", vector, where) + ";"]
    for _ in range(base.REPS):
        parts += ["SET @t = NOW(6);",
                  strat.shape(name, "'X', c.id", vector, where) + ";",
                  "SELECT 'MS', TIMESTAMPDIFF(MICROSECOND, @t, NOW(6));"]
    rows = base.run("\n".join(parts))
    ids = [int(r[1]) for r in rows if r[0] == "R"]
    ms = statistics.median(int(r[1]) for r in rows if r[0] == "MS") / 1000
    return ids, ms


def main():
    print("MariaDB:", base.run("SELECT VERSION();")[0][0])
    vectors = [base.query_vector(i) for i in base.sample_chunks(None, True, QUERIES)]
    print(f"{QUERIES} query vectors, k = {base.K}, median of {base.REPS} runs; computing the exact answers...")
    truth = {where: [strat.exact_ids(v, where) for v in vectors] for where in (None, WEAK)}
    print()

    results = {}
    for m in M_VALUES:
        seconds = rebuild(m)
        print(f"== M = {m}: index rebuilt in {seconds:.1f} s; {index_definition()}")
        for name, where, label in CASES:
            uses_index = "key=embedding" in strat.plan(vectors[0], where, name)
            print(f"   {label}: vector index in the plan: {'yes' if uses_index else 'NO'}")
            for ef in EF_VALUES:
                recalls, times, counts = [], [], []
                for vector, exact in zip(vectors, truth[where]):
                    ids, ms = timed(vector, where, name, ef)
                    recalls.append(len(set(ids) & set(exact)) / max(1, len(exact)))
                    times.append(ms)
                    counts.append(len(ids))
                recall, ms = statistics.mean(recalls), statistics.median(times)
                results[(label, ef, m)] = (recall, ms)
                print(f"      ef_search {ef:4}: recall@{base.K} {recall:4.2f}, "
                      f"rows {statistics.mean(counts):4.1f}, {ms:8.2f} ms")
        print()

    print(f"SUMMARY: recall@{base.K} against exact search and median ms, per M")
    header = "".join(f"{'M=' + str(m):>16}" for m in M_VALUES)
    print(f"{'statement':32} {'ef':>4}{header}")
    for _, _, label in CASES:
        for ef in EF_VALUES:
            cells = "".join(f"{results[(label, ef, m)][0]:9.2f}{results[(label, ef, m)][1]:7.1f}ms"
                            for m in M_VALUES)
            print(f"{label:32} {ef:4}{cells}")


if __name__ == "__main__":
    main()
