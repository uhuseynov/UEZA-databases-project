import json
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text

from src.database import Database
from src.rag.models import RetrievedChunk, SearchFilters

MAX_K = 100
MAX_EF_SEARCH = 10_000

# How an unfiltered search is written (a filtered search always uses "join"):
#   join          - article_chunks joined with articles, ORDER BY distance LIMIT k
#   nearest_first - the k nearest chunks from article_chunks alone, then the join
# With the join, MariaDB searched the HNSW graph far beyond k, so mhnsw_ef_search had no
# effect; the derived table gives the index its own LIMIT k (docs/database/Vector-Search.md).
type SearchShape = Literal["join", "nearest_first"]
# How the query vector is sent: as text for VEC_FromText, or as a hex literal of its binary
# value (little-endian float32, the format MariaDB stores in a VECTOR column). MariaDB
# evaluates VEC_FromText again for every row it compares, which made a full scan 25 times
# slower. The hex literal is written into the statement because aiomysql cannot bind bytes
# with the PyMySQL version we use (2.2); it only ever contains the characters 0-9 and a-f,
# produced from the validated floats.
type VectorFormat = Literal["text", "binary"]

SHAPES: tuple[SearchShape, ...] = ("join", "nearest_first")
VECTOR_FORMATS: tuple[VectorFormat, ...] = ("text", "binary")
DEFAULT_SHAPE: SearchShape = "nearest_first"
DEFAULT_VECTOR_FORMAT: VectorFormat = "binary"

# Every predicate is a fixed SQL fragment; user input only ever travels as a bound
# parameter. The fragments are listed in the order they are added to the WHERE clause.
_FILTER_SQL: dict[str, str] = {
    "category": (
        "EXISTS (SELECT 1 FROM article_categories ac "
        "WHERE ac.article_id = a.id AND ac.category = :category)"
    ),
    "root_category": "a.root_category = :root_category",
    "min_length": "a.article_length >= :min_length",
    "max_length": "a.article_length <= :max_length",
    "edited_since": "a.last_edit_date >= :edited_since",
    "edited_before": "a.last_edit_date < :edited_before",
    "linked_from": (
        "EXISTS (SELECT 1 FROM article_links al "
        "JOIN articles src ON src.id = al.article_id "
        "WHERE src.title = :linked_from AND al.linked_title = a.title)"
    ),
}


def _finite(vector: Sequence[float]) -> list[float]:
    values = [float(x) for x in vector]
    if not all(math.isfinite(x) for x in values):
        raise ValueError("vector contains NaN or infinity")
    return values


def vector_to_text(vector: Sequence[float]) -> str:
    """Format a vector for VEC_FromText: ``[0.01234567,-0.50000000,...]``.

    Fixed-point notation, so no value is ever written with an exponent (``1e-05``).
    """
    return "[" + ",".join(f"{x:.8f}" for x in _finite(vector)) + "]"


def vector_to_bytes(vector: Sequence[float]) -> bytes:
    """The binary value of a VECTOR column: one little-endian float32 per dimension."""
    values = _finite(vector)
    return struct.pack(f"<{len(values)}f", *values)


def vector_to_hex_literal(vector: Sequence[float]) -> str:
    """``X'...'``: the binary value of the vector as an SQL hex literal."""
    return f"X'{vector_to_bytes(vector).hex()}'"


def _distance(column: str, query: str) -> str:
    return f"VEC_DISTANCE_COSINE({column}, {query})"


@dataclass(slots=True, frozen=True)
class SearchQuery:
    sql: str
    params: dict[str, Any]


def build_search_query(
    query_vector: Sequence[float],
    k: int,
    filters: SearchFilters | None = None,
    *,
    exact: bool = False,
    shape: SearchShape = DEFAULT_SHAPE,
    vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
) -> SearchQuery:
    """Build the hybrid search statement: vector distance plus SQL filters.

    With ``exact=False`` the statement orders by the distance alias, which is what lets
    MariaDB answer it from the HNSW vector index. MariaDB only uses the index when the
    ORDER BY is the plain ``VEC_DISTANCE_*`` call (or its alias) with a LIMIT, so
    ``exact=True`` orders by ``distance + 0`` instead. That forces a full scan, which
    gives the exact nearest neighbours used as ground truth for the index recall.

    ``shape="nearest_first"`` only changes searches without a filter: the k nearest
    chunks come from ``article_chunks`` alone (a derived table with its own LIMIT), and
    only those k rows are joined with ``articles``. Filtered searches keep the join, so
    MariaDB can still start from the filter's index.
    """
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}, got {k}")
    if not query_vector:
        raise ValueError("query_vector must not be empty")
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}, got {shape!r}")
    if vector_format not in VECTOR_FORMATS:
        raise ValueError(f"vector_format must be one of {VECTOR_FORMATS}, got {vector_format!r}")

    filters = filters or SearchFilters()
    params: dict[str, Any] = {"k": k}
    if vector_format == "text":
        params["query_vector"] = vector_to_text(query_vector)
        query_sql = "VEC_FromText(:query_vector)"
    else:
        query_sql = vector_to_hex_literal(query_vector)
    conditions: list[str] = []
    for name, fragment in _FILTER_SQL.items():
        value = getattr(filters, name)
        if value is not None:
            conditions.append(fragment)
            params[name] = value

    if shape == "nearest_first" and not conditions:
        distance = _distance("embedding", query_sql)
        order_by = f"{distance} + 0" if exact else "distance"
        sql = (
            "SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, "
            "c.chunk_index, c.chunk_text, n.distance\n"
            f"FROM (SELECT id, {distance} AS distance FROM article_chunks "
            f"ORDER BY {order_by} LIMIT :k) n\n"
            "JOIN article_chunks c ON c.id = n.id\n"
            "JOIN articles a ON a.id = c.article_id\n"
            "ORDER BY n.distance"
        )
        return SearchQuery(sql=sql, params=params)

    distance = _distance("c.embedding", query_sql)
    where = f"WHERE {' AND '.join(conditions)}\n" if conditions else ""
    order_by = f"{distance} + 0" if exact else "distance"

    sql = (
        "SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, "
        "c.chunk_index, c.chunk_text, "
        f"{distance} AS distance\n"
        "FROM article_chunks c\n"
        "JOIN articles a ON a.id = c.article_id\n"
        f"{where}"
        f"ORDER BY {order_by}\n"
        "LIMIT :k"
    )
    return SearchQuery(sql=sql, params=params)


class VectorRetriever:
    """Runs hybrid vector + SQL searches against MariaDB."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def retrieve(
        self,
        query_vector: Sequence[float],
        k: int = 5,
        filters: SearchFilters | None = None,
        *,
        exact: bool = False,
        ef_search: int | None = None,
        shape: SearchShape = DEFAULT_SHAPE,
        vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
    ) -> list[RetrievedChunk]:
        """Return the ``k`` chunks closest to ``query_vector`` that pass ``filters``.

        ``ef_search`` overrides MariaDB's ``mhnsw_ef_search`` for this query only
        (more candidates examined: better recall, slower search).
        """
        query = build_search_query(
            query_vector, k, filters, exact=exact, shape=shape, vector_format=vector_format
        )

        async with self.database.get_session() as session:
            if ef_search is not None:
                await session.execute(
                    text("SET SESSION mhnsw_ef_search = :ef_search"),
                    {"ef_search": _validate_ef_search(ef_search)},
                )
            try:
                result = await session.execute(text(query.sql), query.params)
                rows = result.mappings().all()
            finally:
                if ef_search is not None:
                    # Connections are pooled: do not leak the setting to later queries.
                    await session.execute(text("SET SESSION mhnsw_ef_search = DEFAULT"))

        return [
            RetrievedChunk(
                chunk_id=int(row["chunk_id"]),
                article_id=int(row["article_id"]),
                title=row["title"],
                url=row["url"],
                chunk_index=int(row["chunk_index"]),
                text=row["chunk_text"],
                distance=float(row["distance"]),
            )
            for row in rows
        ]

    async def explain(
        self,
        query_vector: Sequence[float],
        k: int = 5,
        filters: SearchFilters | None = None,
        *,
        exact: bool = False,
        shape: SearchShape = DEFAULT_SHAPE,
        vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
    ) -> list[dict[str, Any]]:
        """Return MariaDB's EXPLAIN rows, to check whether the vector index is used."""
        query = build_search_query(
            query_vector, k, filters, exact=exact, shape=shape, vector_format=vector_format
        )
        async with self.database.get_session() as session:
            result = await session.execute(text(f"EXPLAIN {query.sql}"), query.params)
            return [dict(row) for row in result.mappings().all()]

    async def analyze(
        self,
        query_vector: Sequence[float],
        k: int = 5,
        filters: SearchFilters | None = None,
        *,
        exact: bool = False,
        shape: SearchShape = DEFAULT_SHAPE,
        vector_format: VectorFormat = DEFAULT_VECTOR_FORMAT,
    ) -> dict[str, Any]:
        """Run the search under ``ANALYZE FORMAT=JSON``: the plan with rows and times measured."""
        query = build_search_query(
            query_vector, k, filters, exact=exact, shape=shape, vector_format=vector_format
        )
        async with self.database.get_session() as session:
            result = await session.execute(text(f"ANALYZE FORMAT=JSON {query.sql}"), query.params)
            return json.loads(result.scalar_one())


def _validate_ef_search(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("ef_search must be an integer")
    if not 1 <= value <= MAX_EF_SEARCH:
        raise ValueError(f"ef_search must be between 1 and {MAX_EF_SEARCH}, got {value}")
    return value
