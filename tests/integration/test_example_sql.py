"""examples/vector_search.sql against a real MariaDB: does the worked example still work?

The file is run statement by statement, as the mariadb client would run it, and the result of
every SELECT is checked against what its comments promise. Skipped when MariaDB is not
reachable (CI fails on a skip). The example creates and drops tables of its own
(example_articles, example_links, example_chunks); the project's tables are not touched.
"""

from pathlib import Path

import pymysql
import pytest

from src.config import settings

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "vector_search.sql"
TABLES = ("example_chunks", "example_links", "example_articles")


def statements(sql: str) -> list[str]:
    """The statements of the file: comment lines dropped, split at a ``;`` that ends a line."""
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    parts = "\n".join(lines).split(";\n")
    return [part.strip().rstrip(";") for part in parts if part.strip()]


@pytest.fixture
def connection():
    try:
        conn = pymysql.connect(
            host=settings.mariadb_host,
            port=settings.mariadb_port,
            user=settings.mariadb_user,
            password=settings.mariadb_password,
            database=settings.mariadb_database,
            autocommit=True,
        )
    except pymysql.MySQLError as exc:
        pytest.skip(f"MariaDB not reachable: {exc}")
    try:
        yield conn
    finally:
        with conn.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
        conn.close()


def run(conn, sql: str) -> list[tuple]:
    """Every statement in order; returns the rows of each SELECT, in order."""
    results = []
    with conn.cursor() as cursor:
        for statement in statements(sql):
            cursor.execute(statement)
            if statement.lstrip().upper().startswith("SELECT"):
                results.append(cursor.fetchall())
    return results


def titles(rows) -> list[tuple[str, int]]:
    return [(row[0], row[-2]) for row in rows]


def test_the_statement_splitter_keeps_every_statement():
    found = statements(EXAMPLE.read_text(encoding="utf-8"))

    assert sum(s.upper().startswith("SELECT") for s in found) == 9
    assert found[0] == "DROP TABLE IF EXISTS example_chunks"
    assert found[-1] == "DROP TABLE example_articles"


def test_the_worked_example_returns_what_its_comments_say(connection):
    results = run(connection, EXAMPLE.read_text(encoding="utf-8"))

    language = [("Word embedding", 0), ("Large language model", 0), ("Large language model", 1)]
    nearest, binary, nearest_first, images, long_images, linked, exact, inside, after = results

    # 3. the nearest chunks to a question about language
    assert titles(nearest) == language
    assert [round(row[-1], 4) for row in nearest] == [0.0077, 0.0401, 0.0613]

    # 4. the binary form of the query vector, and the nearest-first statement with it
    assert binary == (("CDCC4C3E000000000000803F00000000",),)
    assert titles(nearest_first) == language
    assert [row[-1] for row in nearest_first] == pytest.approx([row[-1] for row in nearest])

    # 5. a question about images, without and with the length filter
    assert [row[0] for row in images] == [
        "Image segmentation",
        "Convolutional neural network",
        "Convolutional neural network",
    ]
    assert [row[0] for row in long_images] == [
        "Convolutional neural network",
        "Convolutional neural network",
        "AlphaGo",
    ]
    assert all(row[1] > 50000 for row in long_images)

    # 6. only articles that "Large language model" links to
    assert titles(linked) == [("AlphaGo", 1), ("AlphaGo", 0), ("Word embedding", 0)]

    # 7. the exact search agrees with the index
    assert titles(exact) == language

    # 8. a chunk inserted in a transaction is found inside it and gone after ROLLBACK
    assert titles(inside) == [("Transformer (deep learning)", 0)]
    assert titles(after) == [("Word embedding", 0)]

    # 9. the example cleans up after itself
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name LIKE 'example\\_%'"
        )
        assert cursor.fetchone() == (0,)
