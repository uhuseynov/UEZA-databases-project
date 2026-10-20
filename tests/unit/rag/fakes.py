"""Small stand-ins for the database session, used by the RAG unit tests."""

import contextlib
from typing import Any


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement, params: dict[str, Any] | None = None) -> FakeResult:
        sql = str(statement)
        self.statements.append((sql, params))
        if sql.startswith("SET"):
            return FakeResult([])
        return FakeResult(self.rows)


class FakeDatabase:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.session = FakeSession(rows or [])

    @contextlib.asynccontextmanager
    async def get_session(self):
        yield self.session


def chunk_row(
    chunk_id: int,
    title: str,
    distance: float,
    *,
    article_id: int | None = None,
    chunk_index: int = 0,
    text: str = "some text",
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "article_id": article_id if article_id is not None else chunk_id,
        "title": title,
        "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
        "chunk_index": chunk_index,
        "chunk_text": text,
        "distance": distance,
    }
