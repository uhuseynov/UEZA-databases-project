"""Serialization of embedding vectors for MariaDB.

Shared by the repository (inserting chunks) and the retriever (searching), so neither
layer has to import the other.
"""

import math
import struct
from collections.abc import Sequence


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
