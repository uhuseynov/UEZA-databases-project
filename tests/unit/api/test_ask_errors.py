"""``POST /ask`` when the language model fails: the client sees a fixed message, the log the cause.

The real ``ChatLLM`` and ``RAGService`` run over a mocked HTTP transport, so every upstream
failure goes through the same code as in production.
"""

import logging

import httpx
import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from src.main import create_app
from src.rag.llm import ChatLLM
from src.rag.models import RetrievedChunk
from src.rag.service import RAGService

GENERIC = {"detail": "The language model request failed. Try again later."}
BASE_URL = "https://alice:hunter2@llm.internal.example:8443/v1?token=query-secret"
API_KEY = "sk-live-0123456789"
UPSTREAM_BODY = "internal stack: db-host-7 failed, key echo sk-live-0123456789"

CHUNK = RetrievedChunk(
    chunk_id=1,
    article_id=1,
    title="Random forest",
    url=None,
    chunk_index=0,
    text="Random forests average many decision trees.",
    distance=0.1,
)


class FakeEmbedder:
    def embed(self, texts, kind="passage"):
        return [[0.1, 0.2] for _ in texts]


class FakeRetriever:
    async def retrieve(self, query_vector, k=5, filters=None):
        return [CHUNK]


class LogCapture(logging.Handler):
    """Collects the records of ``src.api.routes``.

    ``create_app()`` resets the root handlers, which removes pytest's ``caplog`` handler, so
    the handler is attached to the logger itself, after the app was created.
    """

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logs():
    handler = LogCapture()
    logger = logging.getLogger("src.api.routes")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


def make_client(handler) -> TestClient:
    llm = ChatLLM(
        base_url=BASE_URL,
        api_key=API_KEY,
        model="m",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    service = RAGService(FakeEmbedder(), FakeRetriever(), llm, top_k=3, max_distance=0.5)
    app = create_app()
    app.state.container.rag_service.override(providers.Object(service))
    return TestClient(app)


def raise_error(error_type, message):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(f"{message} {request.url}", request=request)

    return handler


FAILURES = {
    "http 401": lambda request: httpx.Response(401, text=UPSTREAM_BODY),
    "http 500": lambda request: httpx.Response(500, text=UPSTREAM_BODY),
    "http 429": lambda request: httpx.Response(429, text=UPSTREAM_BODY),
    "malformed json": lambda request: httpx.Response(200, text="<html>" + UPSTREAM_BODY),
    "missing choices": lambda request: httpx.Response(200, json={"error": UPSTREAM_BODY}),
    "content is not text": lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": None}}]}
    ),
    "connection refused": raise_error(httpx.ConnectError, "connection refused"),
    "timeout": raise_error(httpx.ReadTimeout, "timed out"),
}


@pytest.mark.parametrize("failure", FAILURES)
def test_the_client_gets_a_fixed_message(failure):
    response = make_client(FAILURES[failure]).post("/ask", json={"question": "What is a forest?"})

    assert response.status_code == 502
    assert response.json() == GENERIC
    body = response.text
    for detail in ("llm.internal.example", "8443", "alice", "hunter2", "query-secret", API_KEY):
        assert detail not in body
    for detail in ("db-host-7", "internal stack", "401", "500", "html"):
        assert detail not in body


@pytest.mark.parametrize("failure", FAILURES)
def test_the_log_keeps_the_cause_without_secrets(failure, logs):
    make_client(FAILURES[failure]).post("/ask", json={"question": "What is a forest?"})

    (record,) = logs.records
    logged = record.getMessage()
    assert logged.startswith("LLM call failed: ")
    assert "llm.internal.example:8443/v1" in logged  # which endpoint failed
    assert record.exc_info is None  # no traceback with chained raw errors
    for secret in ("alice", "hunter2", "query-secret", API_KEY):
        assert secret not in logged


def test_upstream_status_and_failure_kind_are_in_the_log(logs):
    make_client(FAILURES["http 429"]).post("/ask", json={"question": "x"})
    make_client(FAILURES["timeout"]).post("/ask", json={"question": "x"})

    messages = [r.getMessage() for r in logs.records]
    assert any("HTTP 429" in m for m in messages)
    assert any("ReadTimeout" in m for m in messages)


def test_search_does_not_need_the_language_model():
    def must_not_be_called(request):
        raise AssertionError("/search must not call the language model")

    response = make_client(must_not_be_called).get("/search", params={"q": "forest"})

    assert response.status_code == 200
