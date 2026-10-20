import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from src.database import Database
from src.rag.models import RetrievedChunk, SearchFilters

MAX_K = 100
MAX_EF_SEARCH = 10_000

_DISTANCE = "VEC_DISTANCE_COSINE(c.embedding, VEC_FromText(:query_vector))"

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
) -> SearchQuery:
    """Build the hybrid search statement: vector distance plus SQL filters.

    With ``exact=False`` the statement orders by the distance alias, which is what lets
    MariaDB answer it from the HNSW vector index. MariaDB only uses the index when the
    ORDER BY is the plain ``VEC_DISTANCE_*`` call (or its alias) with a LIMIT, so
    ``exact=True`` orders by ``distance + 0`` instead. That forces a full scan, which
    gives the exact nearest neighbours used as ground truth for the index recall.
    """
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be between 1 and {MAX_K}, got {k}")
    if not query_vector:
        raise ValueError("query_vector must not be empty")

    filters = filters or SearchFilters()
    params: dict[str, Any] = {
        "query_vector": json.dumps([float(x) for x in query_vector]),
        "k": k,
    }
    conditions: list[str] = []
    for name, fragment in _FILTER_SQL.items():
        value = getattr(filters, name)
        if value is not None:
            conditions.append(fragment)
            params[name] = value

    where = f"WHERE {' AND '.join(conditions)}\n" if conditions else ""
    order_by = f"{_DISTANCE} + 0" if exact else "distance"

    sql = (
        "SELECT c.id AS chunk_id, a.id AS article_id, a.title, a.url, "
        "c.chunk_index, c.chunk_text, "
        f"{_DISTANCE} AS distance\n"
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
    ) -> list[RetrievedChunk]:
        """Return the ``k`` chunks closest to ``query_vector`` that pass ``filters``.

        ``ef_search`` overrides MariaDB's ``mhnsw_ef_search`` for this query only
        (more candidates examined: better recall, slower search).
        """
        query = build_search_query(query_vector, k, filters, exact=exact)

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
    ) -> list[dict[str, Any]]:
        """Return MariaDB's EXPLAIN rows, to check whether the vector index is used."""
        query = build_search_query(query_vector, k, filters, exact=exact)
        async with self.database.get_session() as session:
            result = await session.execute(text(f"EXPLAIN {query.sql}"), query.params)
            return [dict(row) for row in result.mappings().all()]


def _validate_ef_search(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("ef_search must be an integer")
    if not 1 <= value <= MAX_EF_SEARCH:
        raise ValueError(f"ef_search must be between 1 and {MAX_EF_SEARCH}, got {value}")
    return value
