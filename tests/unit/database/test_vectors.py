"""Serialization of vectors for MariaDB (shared by the repository and the retriever)."""

import math
import struct

import pytest

from src.database.vectors import vector_to_bytes, vector_to_hex_literal, vector_to_text


def test_vector_text_never_uses_exponents():
    assert vector_to_text([1e-05, -0.5, 1]) == "[0.00001000,-0.50000000,1.00000000]"


def test_vector_text_rejects_nan():
    with pytest.raises(ValueError):
        vector_to_text([0.1, float("nan")])


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


def test_full_size_vector_is_768_float32_values():
    vector = [i / 1000 for i in range(768)]

    assert len(vector_to_bytes(vector)) == 768 * 4
    assert len(vector_to_hex_literal(vector)) == len("X''") + 768 * 8
    assert vector_to_text(vector).count(",") == 767


def test_retriever_still_uses_the_shared_helpers():
    from src.rag import retriever

    assert retriever.vector_to_hex_literal is vector_to_hex_literal
    assert retriever.vector_to_text is vector_to_text
