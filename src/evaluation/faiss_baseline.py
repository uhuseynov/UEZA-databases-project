"""FAISS on the same vectors: the baseline for MariaDB's vector search.

Every chunk vector is read from MariaDB once and indexed by FAISS in memory:

- ``IndexFlatIP``: exact search. It must agree with MariaDB's full scan, which checks that
  both compare the same vectors the same way.
- ``IndexHNSWFlat`` with the same ``M`` as MariaDB's index, for several ``efSearch`` values.

The vectors are normalised and compared by inner product, so ``1 - score`` is MariaDB's
``VEC_DISTANCE_COSINE``. FAISS knows nothing about the articles, so a filtered question needs
the ids of the matching chunks from MariaDB first (the same SQL predicates the search uses).
Filtered questions are then answered three ways: exact search over those ids, HNSW with the
ids as a selector, and "search N, keep the allowed ones" (post-filter).

Every question is searched one at a time, like the application does, and FAISS runs on one
thread, like one MariaDB statement. Next to the FAISS numbers, the same command times
MariaDB's own statement and the two-system path an application with FAISS would need:
FAISS for the ids, then MariaDB for the text.
"""

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import bindparam, text

from src.evaluation.ground_truth import Question
from src.evaluation.metrics import (
    first_hit_rank,
    latency_stats,
    mean_reciprocal_rank,
    overlap_at_k,
    recall_at_k,
)
from src.evaluation.runner import EmbedderLike, RetrieverLike, embed_questions
from src.rag.retriever import build_chunk_ids_query

type Search = Callable[[int], Awaitable[list[int]]]


def import_faiss() -> Any:
    try:
        import faiss
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "faiss-cpu is not installed. It is in the dev dependency group: run `uv sync`."
        ) from exc
    return faiss


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Unit-length float32 rows, so inner product is cosine similarity."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("a vector has length 0")
    return np.ascontiguousarray(vectors / norms, dtype=np.float32)


@dataclass(slots=True)
class Corpus:
    """Every chunk: its id, the title of its article and its unit-length vector."""

    ids: np.ndarray  # int64, sorted
    titles: list[str]
    vectors: np.ndarray  # float32, (chunks, dimension)

    def __post_init__(self) -> None:
        if len(self.ids) != len(self.titles) or len(self.ids) != len(self.vectors):
            raise ValueError("ids, titles and vectors must have the same length")
        if np.any(np.diff(self.ids) <= 0):
            raise ValueError("chunk ids must be sorted and unique")

    @property
    def title_by_id(self) -> dict[int, str]:
        return {int(i): t for i, t in zip(self.ids, self.titles, strict=True)}

    def positions(self, chunk_ids: Sequence[int]) -> np.ndarray:
        """Row numbers in the index of the given chunk ids (all must exist)."""
        wanted = np.asarray(chunk_ids, dtype=np.int64)
        positions = np.searchsorted(self.ids, wanted)
        inside = positions < len(self.ids)
        if not np.all(inside) or np.any(self.ids[positions[inside]] != wanted[inside]):
            raise ValueError("unknown chunk id")
        return positions.astype(np.int64)


async def load_corpus(database) -> tuple[Corpus, float]:
    """Read every chunk vector from MariaDB. Returns the corpus and the seconds it took.

    The vector is read as HEX(): the driver decodes unknown column types as text, which
    would break on the binary value of a VECTOR column.
    """
    start = time.perf_counter()
    async with database.get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.id, a.title, HEX(c.embedding) FROM article_chunks c "
                    "JOIN articles a ON a.id = c.article_id ORDER BY c.id"
                )
            )
        ).all()
    if not rows:
        raise ValueError("article_chunks is empty: load the articles first (make ingest)")
    raw = b"".join(bytes.fromhex(row[2]) for row in rows)
    vectors = np.frombuffer(raw, dtype="<f4").reshape(len(rows), -1)
    corpus = Corpus(
        ids=np.array([row[0] for row in rows], dtype=np.int64),
        titles=[row[1] for row in rows],
        vectors=normalize(vectors),
    )
    return corpus, time.perf_counter() - start


class FaissIndexes:
    """A flat (exact) and an HNSW index over the corpus, searched one query at a time."""

    def __init__(self, faiss: Any, corpus: Corpus, *, m: int, ef_construction: int) -> None:
        self.faiss = faiss
        self.corpus = corpus
        dimension = corpus.vectors.shape[1]

        start = time.perf_counter()
        self.flat = faiss.IndexFlatIP(dimension)
        self.flat.add(corpus.vectors)
        self.flat_seconds = time.perf_counter() - start

        start = time.perf_counter()
        self.hnsw = faiss.IndexHNSWFlat(dimension, m, faiss.METRIC_INNER_PRODUCT)
        self.hnsw.hnsw.efConstruction = ef_construction
        self.hnsw.add(corpus.vectors)
        self.hnsw_seconds = time.perf_counter() - start

    def _selector(self, allowed: np.ndarray | None) -> Any:
        if allowed is None:
            return None
        bitmap = np.zeros(len(self.corpus.ids), dtype=bool)
        bitmap[allowed] = True
        packed = np.packbits(bitmap, bitorder="little")
        selector = self.faiss.IDSelectorBitmap(packed)
        selector.packed = packed  # the selector only points at the array: keep it alive
        return selector

    def _ids(self, labels: np.ndarray) -> list[int]:
        return [int(self.corpus.ids[label]) for label in labels if label >= 0]

    def search_flat(
        self, query: np.ndarray, k: int, allowed: np.ndarray | None = None
    ) -> list[int]:
        params = None
        if allowed is not None:
            params = self.faiss.SearchParameters(sel=self._selector(allowed))
        _, labels = self.flat.search(query, k, params=params)
        return self._ids(labels[0])

    def search_hnsw(
        self, query: np.ndarray, k: int, ef: int, allowed: np.ndarray | None = None
    ) -> list[int]:
        params = self.faiss.SearchParametersHNSW(efSearch=ef, sel=self._selector(allowed))
        _, labels = self.hnsw.search(query, k, params=params)
        return self._ids(labels[0])

    def search_hnsw_post_filter(
        self, query: np.ndarray, k: int, fetch: int, ef: int, allowed: np.ndarray
    ) -> list[int]:
        """Search the ``fetch`` nearest chunks, then keep the first ``k`` allowed ones."""
        params = self.faiss.SearchParametersHNSW(efSearch=max(ef, fetch))
        _, labels = self.hnsw.search(query, fetch, params=params)
        keep = set(allowed.tolist())
        return self._ids([label for label in labels[0] if label in keep][:k])

    def sizes(self) -> dict[str, int]:
        return {
            "flat_bytes": int(self.faiss.serialize_index(self.flat).nbytes),
            "hnsw_bytes": int(self.faiss.serialize_index(self.hnsw).nbytes),
        }

    def update_costs(self, chunk_ids: Sequence[int]) -> dict[str, Any]:
        """What replacing one article's chunks costs: delete its vectors, add them again."""
        positions = self.corpus.positions(chunk_ids)
        costs: dict[str, Any] = {"chunks": len(positions)}
        try:
            self.hnsw.remove_ids(positions)
            costs["hnsw_remove"] = "supported"
        except RuntimeError as exc:  # FAISS: "Error in ... at Index.cpp:57: remove_ids not ..."
            costs["hnsw_remove"] = str(exc).strip().splitlines()[-1].split(": ")[-1][:200]

        flat = self.faiss.IndexFlatIP(self.corpus.vectors.shape[1])
        flat.add(self.corpus.vectors)
        start = time.perf_counter()
        removed = flat.remove_ids(positions)
        costs["flat_remove_ms"] = round((time.perf_counter() - start) * 1000, 3)
        start = time.perf_counter()
        flat.add(self.corpus.vectors[positions])
        costs["flat_add_ms"] = round((time.perf_counter() - start) * 1000, 3)
        costs["flat_removed"] = int(removed)
        return costs


async def fetch_chunks(database, chunk_ids: Sequence[int]) -> list[tuple[int, str, str]]:
    """The text of the given chunks, in the given order: the second half of a two-system search."""
    if not chunk_ids:
        return []
    statement = text(
        "SELECT c.id, a.title, c.chunk_text FROM article_chunks c "
        "JOIN articles a ON a.id = c.article_id WHERE c.id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    async with database.get_session() as session:
        result = await session.execute(statement, {"ids": list(chunk_ids)})
        rows = {row[0]: (row[0], row[1], row[2]) for row in result}
    return [rows[i] for i in chunk_ids if i in rows]


async def server_times(
    retriever: Any, vectors: Sequence[Sequence[float]], questions: Sequence[Question],
    indices: Sequence[int], k: int,
) -> list[float]:
    """MariaDB's own time for each statement, from ANALYZE (one run per question)."""
    if not hasattr(retriever, "analyze"):
        return []
    times = []
    for i in indices:
        plan = await retriever.analyze(vectors[i], k, questions[i].filters)
        total = plan.get("query_block", {}).get("r_total_time_ms")
        if isinstance(total, int | float):
            times.append(float(total))
    return times


async def allowed_chunk_ids(database, question: Question) -> list[int]:
    query = build_chunk_ids_query(question.filters)
    async with database.get_session() as session:
        return [int(row[0]) for row in await session.execute(text(query.sql), query.params)]


async def measure(
    name: str,
    questions: Sequence[Question],
    search: Search,
    exact_ids: Sequence[list[int]],
    title_by_id: dict[int, str],
    *,
    k: int,
    runs: int,
    warmup_runs: int,
    ef: int | None = None,
) -> dict[str, Any]:
    """Search every question ``warmup_runs + runs`` times; quality from the first timed run."""
    found: list[list[int]] = [[] for _ in questions]
    latencies: list[float] = []
    for _ in range(warmup_runs):
        for index in range(len(questions)):
            await search(index)
    for run in range(runs):
        for index in range(len(questions)):
            start = time.perf_counter()
            ids = await search(index)
            latencies.append((time.perf_counter() - start) * 1000)
            if run == 0:
                found[index] = ids

    overlaps = [
        overlap_at_k(ids, exact, k) for ids, exact in zip(found, exact_ids, strict=True) if exact
    ]
    ranks = [
        first_hit_rank([title_by_id[i] for i in ids], q.correct_articles)
        for ids, q in zip(found, questions, strict=True)
        if q.answerable
    ]
    return {
        "method": name,
        "ef": ef,
        "questions": len(questions),
        f"index_recall@{k}": _round(sum(overlaps) / len(overlaps)) if overlaps else None,
        "recall@1": _round(recall_at_k(ranks, 1)),
        f"recall@{k}": _round(recall_at_k(ranks, k)),
        "mrr": _round(mean_reciprocal_rank(ranks)),
        "returned_mean": _round(sum(len(ids) for ids in found) / len(found)) if found else None,
        "fewer_than_k": sum(1 for ids in found if len(ids) < k),
        "latency": latency_stats(latencies).as_dict(),
    }


async def faiss_baseline(
    questions: Sequence[Question],
    embedder: EmbedderLike,
    retriever: RetrieverLike,
    database,
    *,
    m: int = 16,
    ef_construction: int = 40,
    ef_values: Sequence[int] = (10, 20, 40, 80, 160),
    fetch_values: Sequence[int] = (10, 100, 1000),
    ef_two_systems: int = 40,
    runs: int = 3,
    warmup_runs: int = 1,
    k: int = 10,
    threads: int = 1,
    environment: dict[str, Any] | None = None,
    faiss: Any = None,
) -> dict[str, Any]:
    faiss = faiss or import_faiss()
    faiss.omp_set_num_threads(threads)

    corpus, load_seconds = await load_corpus(database)
    indexes = FaissIndexes(faiss, corpus, m=m, ef_construction=ef_construction)
    title_by_id = corpus.title_by_id

    raw_vectors, _ = await embed_questions(embedder, questions)
    query_vectors = [normalize(np.asarray([v])) for v in raw_vectors]
    plain = [i for i, q in enumerate(questions) if not q.filtered]
    filtered = [i for i, q in enumerate(questions) if q.filtered]

    allowed_ids: dict[int, list[int]] = {}
    sql_ms: list[float] = []
    for i in filtered:
        start = time.perf_counter()
        allowed_ids[i] = await allowed_chunk_ids(database, questions[i])
        sql_ms.append((time.perf_counter() - start) * 1000)
    allowed = {i: corpus.positions(ids) for i, ids in allowed_ids.items()}

    # The exact answers, from FAISS, and whether MariaDB's full scan agrees with them.
    exact: dict[int, list[int]] = {}
    for i in plain:
        exact[i] = indexes.search_flat(query_vectors[i], k)
    for i in filtered:
        exact[i] = indexes.search_flat(query_vectors[i], k, allowed[i]) if len(allowed[i]) else []
    agree = {"plain": 0, "filtered": 0}
    for i, question in enumerate(questions):
        chunks = await retriever.retrieve(raw_vectors[i], k, question.filters, exact=True)
        if [c.chunk_id for c in chunks] == exact[i]:
            agree["filtered" if question.filtered else "plain"] += 1

    def subset(indices: list[int]) -> tuple[list[Question], list[list[int]]]:
        return [questions[i] for i in indices], [exact[i] for i in indices]

    async def run(name: str, indices: list[int], search_one, ef: int | None = None) -> dict[str, Any]:
        async def search(position: int) -> list[int]:
            return await search_one(indices[position])

        subset_questions, subset_exact = subset(indices)
        return await measure(name, subset_questions, search, subset_exact, title_by_id,
                             k=k, runs=runs, warmup_runs=warmup_runs, ef=ef)

    # Questions without a filter
    async def flat_plain(i: int) -> list[int]:
        return indexes.search_flat(query_vectors[i], k)

    async def mariadb(i: int) -> list[int]:
        chunks = await retriever.retrieve(raw_vectors[i], k, questions[i].filters)
        return [c.chunk_id for c in chunks]

    async def two_systems_plain(i: int) -> list[int]:
        ids = indexes.search_hnsw(query_vectors[i], k, ef_two_systems)
        return [row[0] for row in await fetch_chunks(database, ids)]

    plain_rows = [await run("FAISS flat (exact)", plain, flat_plain)]
    for ef in ef_values:
        async def hnsw_plain(i: int, ef: int = ef) -> list[int]:
            return indexes.search_hnsw(query_vectors[i], k, ef)

        plain_rows.append(await run("FAISS HNSW", plain, hnsw_plain, ef))
    plain_rows.append(await run("MariaDB statement", plain, mariadb))
    plain_rows.append(await run("FAISS HNSW, then MariaDB for the text", plain, two_systems_plain,
                                ef_two_systems))

    # Questions with a filter
    async def flat_filtered(i: int) -> list[int]:
        return indexes.search_flat(query_vectors[i], k, allowed[i])

    async def two_systems_filtered(i: int) -> list[int]:
        ids = await allowed_chunk_ids(database, questions[i])
        found = indexes.search_hnsw(query_vectors[i], k, ef_two_systems, corpus.positions(ids))
        return [row[0] for row in await fetch_chunks(database, found)]

    filtered_rows = [await run("FAISS flat over the allowed ids (exact)", filtered, flat_filtered)]
    for ef in ef_values:
        async def hnsw_selector(i: int, ef: int = ef) -> list[int]:
            return indexes.search_hnsw(query_vectors[i], k, ef, allowed[i])

        filtered_rows.append(await run("FAISS HNSW with the allowed ids as selector", filtered,
                                       hnsw_selector, ef))
    for fetch in fetch_values:
        async def post_filter(i: int, fetch: int = fetch) -> list[int]:
            return indexes.search_hnsw_post_filter(query_vectors[i], k, fetch, ef_two_systems,
                                                   allowed[i])

        filtered_rows.append(await run(f"FAISS HNSW, {fetch} nearest, then filter", filtered,
                                       post_filter, max(ef_two_systems, fetch)))
    filtered_rows.append(await run("MariaDB statement", filtered, mariadb))
    filtered_rows.append(await run("MariaDB ids, FAISS HNSW with selector, MariaDB text",
                                   filtered, two_systems_filtered, ef_two_systems))

    server_ms = {
        "plain": latency_stats(await server_times(retriever, raw_vectors, questions, plain, k)).as_dict(),
        "filtered": latency_stats(
            await server_times(retriever, raw_vectors, questions, filtered, k)
        ).as_dict(),
    }
    article_chunks = _largest_article(corpus)
    return {
        "kind": "faiss_baseline",
        "label": "faiss",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {"m": m, "ef_construction": ef_construction, "ef_values": list(ef_values),
                   "fetch_values": list(fetch_values), "ef_two_systems": ef_two_systems,
                   "runs": runs, "warmup_runs": warmup_runs, "k": k, "threads": threads},
        "environment": {**(environment or {}), "faiss_version": faiss.__version__},
        "corpus": {
            "chunks": len(corpus.ids),
            "dimension": int(corpus.vectors.shape[1]),
            "load_seconds": round(load_seconds, 3),
        },
        "build": {
            "flat_seconds": round(indexes.flat_seconds, 3),
            "hnsw_seconds": round(indexes.hnsw_seconds, 3),
            **indexes.sizes(),
        },
        "update": indexes.update_costs(article_chunks),
        "exact_agreement": {"plain": agree["plain"], "plain_questions": len(plain),
                            "filtered": agree["filtered"], "filtered_questions": len(filtered)},
        "filter_ids_sql": {
            "latency": latency_stats(sql_ms).as_dict(),
            "allowed_chunks": sorted(len(ids) for ids in allowed_ids.values()),
        },
        "mariadb_server_ms": server_ms,
        "plain": plain_rows,
        "filtered": filtered_rows,
    }


def _largest_article(corpus: Corpus) -> list[int]:
    """The chunk ids of the article with the most chunks, as an example of an update."""
    by_title: dict[str, list[int]] = {}
    for chunk_id, title in zip(corpus.ids, corpus.titles, strict=True):
        by_title.setdefault(title, []).append(int(chunk_id))
    return max(by_title.values(), key=len)


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits) if value == value else value
