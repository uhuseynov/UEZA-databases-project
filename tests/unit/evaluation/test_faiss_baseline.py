import contextlib

import numpy as np
import pytest

from src.evaluation.faiss_baseline import Corpus, FaissIndexes, faiss_baseline, normalize
from src.evaluation.ground_truth import Question
from src.evaluation.report import render_faiss
from src.rag.models import RetrievedChunk, SearchFilters

faiss = pytest.importorskip("faiss")

DIMENSION = 16
TITLES = ["Alpha", "Beta", "Gamma", "Delta"]
GROUP = {"Alpha": "Core", "Beta": "Core", "Gamma": "Vision", "Delta": "Vision"}
CHUNKS_PER_ARTICLE = 5


def make_corpus() -> tuple[np.ndarray, list[str], np.ndarray]:
    """Each article is a cluster around its own axis, so the nearest chunks are known."""
    rng = np.random.default_rng(0)
    ids, titles, vectors = [], [], []
    for a, title in enumerate(TITLES):
        for c in range(CHUNKS_PER_ARTICLE):
            vector = rng.normal(0, 0.05, DIMENSION)
            vector[a] += 1.0
            ids.append(100 + a * 10 + c)
            titles.append(title)
            vectors.append(vector)
    return np.array(ids, dtype=np.int64), titles, np.array(vectors, dtype=np.float32)


IDS, CHUNK_TITLES, VECTORS = make_corpus()


def axis(index: int, noise: float = 0.01) -> list[float]:
    vector = [noise] * DIMENSION
    vector[index] = 1.0
    return vector


QUESTIONS = [
    Question("1", "about alpha", ("Alpha",), True),
    Question("2", "about gamma", ("Gamma",), True),
    Question("3", "beta among core", ("Beta",), True, SearchFilters(root_category="Core"), "root_category = Core"),
    # asks for Alpha's direction, but only Vision articles are allowed
    Question("4", "alpha among vision", ("Gamma",), True, SearchFilters(root_category="Vision"), "root_category = Vision"),
    Question("5", "football?", (), False),
]
QUERY = {"about alpha": axis(0), "about gamma": axis(2), "beta among core": axis(1),
         "alpha among vision": axis(0), "football?": axis(DIMENSION - 1)}


class FakeEmbedder:
    def embed(self, texts, kind="passage"):
        return [QUERY[t] for t in texts]


def exact_ids(vector, filters: SearchFilters | None, k: int) -> list[int]:
    query = normalize(np.asarray([vector]))[0]
    vectors = normalize(VECTORS)
    allowed = [i for i, t in enumerate(CHUNK_TITLES)
               if not filters or not filters.root_category or GROUP[t] == filters.root_category]
    order = sorted(allowed, key=lambda i: -float(vectors[i] @ query))
    return [int(IDS[i]) for i in order[:k]]


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = []

    async def retrieve(self, query_vector, k=5, filters=None, *, exact=False, **kwargs):
        self.calls.append(exact)
        title = dict(zip(IDS.tolist(), CHUNK_TITLES, strict=True))
        return [RetrievedChunk(i, 0, title[i], None, 0, "text", 0.0) for i in exact_ids(query_vector, filters, k)]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "HEX(c.embedding)" in sql:
            return FakeResult([(int(i), t, VECTORS[n].astype("<f4").tobytes().hex().upper())
                               for n, (i, t) in enumerate(zip(IDS, CHUNK_TITLES, strict=True))])
        if sql.startswith("SELECT c.id FROM article_chunks"):
            group = params["root_category"]
            return FakeResult([(int(i),) for i, t in zip(IDS, CHUNK_TITLES, strict=True) if GROUP[t] == group])
        if "WHERE c.id IN" in sql:
            title = dict(zip(IDS.tolist(), CHUNK_TITLES, strict=True))
            return FakeResult([(i, title[i], "text") for i in params["ids"]])
        raise AssertionError(f"unexpected SQL: {sql}")


class FakeDatabase:
    @contextlib.asynccontextmanager
    async def get_session(self):
        yield FakeSession()


def test_normalize_gives_unit_rows_and_rejects_zero_vectors():
    rows = normalize(np.array([[3.0, 4.0], [0.0, 2.0]]))

    assert rows.dtype == np.float32
    assert np.allclose(np.linalg.norm(rows, axis=1), 1.0)
    with pytest.raises(ValueError):
        normalize(np.array([[0.0, 0.0]]))


def test_corpus_maps_chunk_ids_to_rows():
    corpus = Corpus(IDS, CHUNK_TITLES, normalize(VECTORS))

    assert corpus.positions([100, 131]).tolist() == [0, 16]
    with pytest.raises(ValueError):
        corpus.positions([999])
    with pytest.raises(ValueError):
        Corpus(IDS[::-1].copy(), CHUNK_TITLES, normalize(VECTORS))


def test_indexes_search_filter_and_report_update_costs():
    corpus = Corpus(IDS, CHUNK_TITLES, normalize(VECTORS))
    indexes = FaissIndexes(faiss, corpus, m=8, ef_construction=40)
    query = normalize(np.asarray([axis(0)]))
    vision = corpus.positions([i for i, t in zip(IDS, CHUNK_TITLES, strict=True) if GROUP[t] == "Vision"])

    assert indexes.search_flat(query, 5) == exact_ids(axis(0), None, 5)
    assert set(indexes.search_hnsw(query, 5, ef=40)) == set(exact_ids(axis(0), None, 5))
    filtered = indexes.search_flat(query, 3, vision)
    assert filtered == exact_ids(axis(0), SearchFilters(root_category="Vision"), 3)
    assert set(indexes.search_hnsw(query, 3, 40, vision)) <= {int(IDS[p]) for p in vision}
    # the 10 nearest chunks are all Alpha's and Beta's: nothing survives the filter
    assert indexes.search_hnsw_post_filter(query, 3, 5, 40, vision) == []

    costs = indexes.update_costs([100, 101])
    assert costs["chunks"] == 2
    assert costs["hnsw_remove"] != "supported"
    assert costs["flat_removed"] == 2
    assert indexes.sizes()["hnsw_bytes"] > indexes.sizes()["flat_bytes"]


@pytest.mark.anyio
async def test_baseline_compares_faiss_with_mariadb_on_every_question():
    retriever = FakeRetriever()

    report = await faiss_baseline(
        QUESTIONS, FakeEmbedder(), retriever, FakeDatabase(),
        m=8, ef_values=[10, 40], fetch_values=[5, 20], runs=1, warmup_runs=0, k=3, faiss=faiss,
    )

    assert report["corpus"] == {"chunks": 20, "dimension": DIMENSION, "load_seconds": report["corpus"]["load_seconds"]}
    assert report["exact_agreement"] == {"plain": 3, "plain_questions": 3, "filtered": 2, "filtered_questions": 2}
    plain = {(row["method"], row["ef"]): row for row in report["plain"]}
    assert plain[("FAISS flat (exact)", None)]["index_recall@3"] == 1.0
    assert plain[("FAISS flat (exact)", None)]["recall@1"] == 1.0
    assert plain[("MariaDB statement", None)]["index_recall@3"] == 1.0
    assert ("FAISS HNSW", 40) in plain
    filtered = {(row["method"], row["ef"]): row for row in report["filtered"]}
    assert filtered[("FAISS flat over the allowed ids (exact)", None)]["index_recall@3"] == 1.0
    # question 4 looks for Alpha, but only Vision chunks are allowed: 5 nearest are all Alpha's
    post = filtered[("FAISS HNSW, 5 nearest, then filter", 40)]
    assert post["fewer_than_k"] == 1
    assert report["filter_ids_sql"]["allowed_chunks"] == [10, 10]
    assert report["update"]["chunks"] == CHUNKS_PER_ARTICLE

    markdown = render_faiss(report)
    assert "## Questions with a filter" in markdown
    assert "| FAISS HNSW | 40 |" in markdown
    assert "3 of 3 questions without a filter" in markdown


class AnalyzingRetriever(FakeRetriever):
    async def analyze(self, query_vector, k=5, filters=None, **kwargs):
        return {"query_block": {"r_total_time_ms": 0.5 if filters is None or filters.is_empty() else 2.0}}


@pytest.mark.anyio
async def test_baseline_reports_mariadb_time_inside_the_server():
    report = await faiss_baseline(
        QUESTIONS, FakeEmbedder(), AnalyzingRetriever(), FakeDatabase(),
        m=8, ef_values=[40], fetch_values=[20], runs=1, warmup_runs=0, k=3, faiss=faiss,
    )

    assert report["mariadb_server_ms"]["plain"]["mean_ms"] == 0.5
    assert report["mariadb_server_ms"]["filtered"]["mean_ms"] == 2.0
    assert report["update"]["hnsw_remove"] == "remove_ids not implemented for this type of index"
    assert "Inside MariaDB (`ANALYZE`" in render_faiss(report)
