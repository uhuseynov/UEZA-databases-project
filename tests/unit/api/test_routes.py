from datetime import datetime

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from src.main import create_app
from src.rag.llm import LLMError
from src.rag.models import Answer, RetrievedChunk, SearchFilters, Source

CHUNK = RetrievedChunk(
    chunk_id=11,
    article_id=3,
    title="Random forest",
    url="https://en.wikipedia.org/wiki/Random_forest",
    chunk_index=0,
    text="Random forests average many decision trees.",
    distance=0.123456,
)


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, int | None, SearchFilters | None]] = []

    async def search(self, question, k=None, filters=None):
        self.calls.append(("search", question, k, filters))
        if self.error:
            raise self.error
        return [CHUNK], {"embed_ms": 1.0, "retrieve_ms": 2.0}

    async def answer(self, question, k=None, filters=None):
        self.calls.append(("answer", question, k, filters))
        if self.error:
            raise self.error
        return Answer(
            question=question,
            text="Random forest [1].",
            found=True,
            sources=(Source(title=CHUNK.title, url=CHUNK.url),),
            chunks=(CHUNK,),
            timings_ms={"embed_ms": 1.0, "retrieve_ms": 2.0, "llm_ms": 3.0, "total_ms": 6.0},
        )


@pytest.fixture
def service():
    return FakeService()


@pytest.fixture
def client(service):
    app = create_app()
    app.state.container.rag_service.override(providers.Object(service))
    return TestClient(app)


def test_index_serves_the_web_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "UEZA Wikipedia RAG" in response.text


def test_search_returns_chunks_and_passes_filters(client, service):
    response = client.get(
        "/search",
        params={
            "q": "Which method averages trees?",
            "k": 3,
            "category": "Machine learning",
            "min_length": 5000,
            "edited_since": "2026-01-01",
            "linked_from": "",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["title"] == "Random forest"
    assert body["results"][0]["distance"] == 0.1235
    assert body["filters"] == {
        "category": "Machine learning",
        "min_length": 5000,
        "edited_since": "2026-01-01T00:00:00",
    }
    _, question, k, filters = service.calls[0]
    assert (question, k) == ("Which method averages trees?", 3)
    assert filters == SearchFilters(
        category="Machine learning", min_length=5000, edited_since=datetime(2026, 1, 1)
    )


def test_search_requires_a_question(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_search_rejects_a_bad_date(client):
    response = client.get("/search", params={"q": "x", "edited_since": "yesterday"})

    assert response.status_code == 422


def test_ask_returns_answer_with_sources(client, service):
    response = client.post(
        "/ask",
        json={"question": "Which method averages trees?", "k": 5, "filters": {"root_category": "Core"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["answer"] == "Random forest [1]."
    assert body["sources"] == [{"title": CHUNK.title, "url": CHUNK.url}]
    assert body["filters"] == {"root_category": "Core"}
    assert service.calls[0][3] == SearchFilters(root_category="Core")


def test_ask_validates_k(client):
    response = client.post("/ask", json={"question": "x", "k": 0})

    assert response.status_code == 422


def test_llm_failure_is_a_502():
    app = create_app()
    app.state.container.rag_service.override(providers.Object(FakeService(LLMError("down"))))

    response = TestClient(app).post("/ask", json={"question": "x"})

    assert response.status_code == 502
    assert "down" in response.json()["detail"]


def test_database_failure_is_a_503_without_internal_details():
    error = OperationalError("SELECT secret", {}, Exception("connection refused"))
    app = create_app()
    app.state.container.rag_service.override(providers.Object(FakeService(error)))

    response = TestClient(app).get("/search", params={"q": "x"})

    assert response.status_code == 503
    assert "secret" not in response.json()["detail"]
