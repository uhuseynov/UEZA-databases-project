import json
import math
import struct
from datetime import datetime

import pytest

from src.rag.models import SearchFilters
from src.rag.retriever import (
    MAX_K,
    VectorRetriever,
    build_search_query,
    vector_to_bytes,
    vector_to_hex_literal,
    vector_to_text,
)
from tests.unit.rag.fakes import FakeDatabase, chunk_row

VECTOR = [0.1, 0.2, 0.3]


def test_defaults_are_nearest_first_with_a_binary_vector():
    query = build_search_query(VECTOR, k=5)

    assert "FROM (SELECT id, VEC_DISTANCE_COSINE(embedding, X'" in query.sql
    assert "VEC_FromText" not in query.sql


def test_query_without_filters_orders_by_distance_alias_so_the_index_can_be_used():
    query = build_search_query(VECTOR, k=5, shape="join", vector_format="text")

    assert "WHERE" not in query.sql
    assert "ORDER BY distance\n" in query.sql
    assert query.sql.endswith("LIMIT :k")
    assert query.params == {"query_vector": "[0.10000000,0.20000000,0.30000000]", "k": 5}


def test_exact_query_orders_by_an_expression_to_force_a_full_scan():
    query = build_search_query(VECTOR, k=5, exact=True, shape="join", vector_format="text")

    assert "ORDER BY VEC_DISTANCE_COSINE(c.embedding, VEC_FromText(:query_vector)) + 0" in query.sql
    assert "ORDER BY distance\n" not in query.sql


def test_every_filter_becomes_a_bound_parameter():
    filters = SearchFilters(
        category="Deepfakes",
        root_category="Computer vision",
        min_length=1000,
        max_length=50000,
        edited_since=datetime(2026, 1, 1),
        edited_before=datetime(2026, 10, 1),
        linked_from="Artificial intelligence",
    )

    query = build_search_query(VECTOR, k=3, filters=filters)

    for name in (
        ":category",
        ":root_category",
        ":min_length",
        ":max_length",
        ":edited_since",
        ":edited_before",
        ":linked_from",
    ):
        assert name in query.sql
    assert query.sql.count(" AND ") >= 6
    assert query.params["category"] == "Deepfakes"
    assert query.params["linked_from"] == "Artificial intelligence"
    assert query.params["edited_before"] == datetime(2026, 10, 1)


def test_filter_values_never_appear_in_the_sql_text():
    malicious = "x'; DROP TABLE articles; --"

    query = build_search_query(VECTOR, k=3, filters=SearchFilters(category=malicious))

    assert malicious not in query.sql
    assert query.params["category"] == malicious


def test_category_filter_uses_exists_so_an_article_is_not_duplicated():
    query = build_search_query(VECTOR, k=3, filters=SearchFilters(category="Machine learning"))

    assert "EXISTS (SELECT 1 FROM article_categories" in query.sql


@pytest.mark.parametrize("k", [0, -1, MAX_K + 1])
def test_rejects_invalid_k(k):
    with pytest.raises(ValueError):
        build_search_query(VECTOR, k=k)


def test_rejects_empty_vector():
    with pytest.raises(ValueError):
        build_search_query([], k=5)


@pytest.mark.anyio
async def test_retrieve_maps_rows_to_chunks():
    database = FakeDatabase([chunk_row(7, "Overfitting", 0.12), chunk_row(9, "Bias", 0.3)])
    retriever = VectorRetriever(database)

    chunks = await retriever.retrieve(VECTOR, k=2)

    assert [c.chunk_id for c in chunks] == [7, 9]
    assert chunks[0].title == "Overfitting"
    assert chunks[0].distance == pytest.approx(0.12)
    assert len(database.session.statements) == 1


@pytest.mark.anyio
async def test_ef_search_is_set_and_reset_around_the_query():
    database = FakeDatabase([chunk_row(1, "A", 0.1)])
    retriever = VectorRetriever(database)

    await retriever.retrieve(VECTOR, k=1, ef_search=80)

    statements = [sql for sql, _ in database.session.statements]
    assert statements[0] == "SET SESSION mhnsw_ef_search = :ef_search"
    assert database.session.statements[0][1] == {"ef_search": 80}
    assert statements[-1] == "SET SESSION mhnsw_ef_search = DEFAULT"


@pytest.mark.anyio
@pytest.mark.parametrize("ef_search", [0, 10_001])
async def test_rejects_invalid_ef_search(ef_search):
    retriever = VectorRetriever(FakeDatabase())

    with pytest.raises(ValueError):
        await retriever.retrieve(VECTOR, k=1, ef_search=ef_search)


@pytest.mark.anyio
async def test_explain_prefixes_the_search_statement():
    database = FakeDatabase([{"id": 1, "table": "c", "key": "embedding"}])
    retriever = VectorRetriever(database)

    plan = await retriever.explain(VECTOR, k=3)

    assert database.session.statements[0][0].startswith("EXPLAIN SELECT")
    assert plan == [{"id": 1, "table": "c", "key": "embedding"}]


def test_filters_as_dict_skips_unset_values_and_formats_dates():
    filters = SearchFilters(min_length=10, edited_since=datetime(2026, 1, 1))

    assert filters.as_dict() == {"min_length": 10, "edited_since": "2026-01-01T00:00:00"}
    assert not filters.is_empty()
    assert SearchFilters().is_empty()


def test_vector_text_never_uses_exponents():
    assert vector_to_text([1e-05, -0.5, 1]) == "[0.00001000,-0.50000000,1.00000000]"


def test_vector_text_rejects_nan():
    with pytest.raises(ValueError):
        vector_to_text([0.1, float("nan")])


def test_nearest_first_takes_the_k_nearest_chunks_before_the_join():
    query = build_search_query(VECTOR, k=5, shape="nearest_first", vector_format="text")

    assert (
        "FROM (SELECT id, VEC_DISTANCE_COSINE(embedding, VEC_FromText(:query_vector)) AS distance "
        "FROM article_chunks ORDER BY distance LIMIT :k) n"
    ) in query.sql
    assert "JOIN article_chunks c ON c.id = n.id" in query.sql
    assert query.sql.endswith("ORDER BY n.distance")
    assert query.sql.count("LIMIT") == 1


def test_nearest_first_exact_orders_the_inner_query_by_an_expression():
    query = build_search_query(VECTOR, k=5, shape="nearest_first", exact=True,
                               vector_format="text")

    assert "ORDER BY VEC_DISTANCE_COSINE(embedding, VEC_FromText(:query_vector)) + 0 LIMIT :k" in query.sql


def test_nearest_first_keeps_the_join_when_there_is_a_filter():
    filters = SearchFilters(category="Deepfakes")

    nearest = build_search_query(VECTOR, k=5, filters=filters, shape="nearest_first")
    joined = build_search_query(VECTOR, k=5, filters=filters)

    assert nearest == joined


def test_binary_vector_is_written_as_a_hex_literal_of_float32_values():
    query = build_search_query(VECTOR, k=5, shape="join", vector_format="binary")
    literal = "X'" + struct.pack("<3f", 0.1, 0.2, 0.3).hex() + "'"

    assert "VEC_FromText" not in query.sql
    assert f"VEC_DISTANCE_COSINE(c.embedding, {literal}) AS distance" in query.sql
    assert query.params == {"k": 5}


def test_hex_literal_contains_only_hex_digits():
    literal = vector_to_hex_literal([1.0, -0.5])

    assert literal == "X'0000803f000000bf'"


def test_binary_vector_round_trips():
    data = vector_to_bytes([1.0, -0.5, 1e-05])

    assert len(data) == 12
    assert struct.unpack("<3f", data) == pytest.approx((1.0, -0.5, 1e-05))


def test_binary_vector_rejects_infinity():
    with pytest.raises(ValueError):
        vector_to_bytes([0.1, math.inf])


@pytest.mark.parametrize("option", [{"shape": "chunks"}, {"vector_format": "hex"}])
def test_rejects_unknown_shape_or_vector_format(option):
    with pytest.raises(ValueError):
        build_search_query(VECTOR, k=5, **option)


@pytest.mark.anyio
async def test_retrieve_passes_shape_and_vector_format_through():
    database = FakeDatabase([chunk_row(1, "A", 0.1)])
    retriever = VectorRetriever(database)

    await retriever.retrieve(VECTOR, k=1, shape="nearest_first", vector_format="binary")

    sql, params = database.session.statements[0]
    assert "FROM (SELECT id, VEC_DISTANCE_COSINE(embedding, X'" in sql
    assert params == {"k": 1}


@pytest.mark.anyio
async def test_analyze_runs_the_statement_under_analyze_format_json():
    plan = {"query_block": {"r_total_time_ms": 1.5}}
    database = FakeDatabase([{"ANALYZE": json.dumps(plan)}])
    retriever = VectorRetriever(database)

    result = await retriever.analyze(VECTOR, k=3, vector_format="binary")

    assert database.session.statements[0][0].startswith("ANALYZE FORMAT=JSON SELECT")
    assert result == plan

