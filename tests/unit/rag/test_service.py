import pytest

from src.rag.models import RetrievedChunk, SearchFilters
from src.rag.service import NOT_FOUND_MESSAGE, RAGService

pytestmark = pytest.mark.anyio


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]]:
        self.calls.append((texts, kind))
        return [[0.5, 0.5] for _ in texts]


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[list[float], int, SearchFilters | None]] = []

    async def retrieve(self, query_vector, k=5, filters=None):
        self.calls.append((query_vector, k, filters))
        return self.chunks[:k]


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.reply


def chunk(chunk_id: int, title: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        article_id=chunk_id,
        title=title,
        url=None,
        chunk_index=0,
        text=f"text about {title}",
        distance=distance,
    )


def make_service(chunks, reply="Answer [1].", max_distance=0.5):
    embedder, retriever, llm = FakeEmbedder(), FakeRetriever(chunks), FakeLLM(reply)
    service = RAGService(embedder, retriever, llm, top_k=3, max_distance=max_distance)
    return service, embedder, retriever, llm


async def test_answer_uses_close_chunks_and_cites_sources():
    service, embedder, retriever, llm = make_service(
        [chunk(1, "Overfitting", 0.2), chunk(2, "Dropout", 0.3), chunk(3, "Football", 0.9)],
        reply="Overfitting means ... [1]",
    )
    filters = SearchFilters(min_length=100)

    answer = await service.answer("  What is overfitting?  ", filters=filters)

    assert answer.found
    assert answer.text == "Overfitting means ... [1]"
    assert [s.title for s in answer.sources] == ["Overfitting"]
    assert [c.title for c in answer.chunks] == ["Overfitting", "Dropout"]
    assert embedder.calls == [(["What is overfitting?"], "query")]
    assert retriever.calls[0][1:] == (3, filters)
    assert "Football" not in llm.calls[0][1]["content"]
    assert set(answer.timings_ms) == {"embed_ms", "retrieve_ms", "llm_ms", "total_ms"}


async def test_no_close_chunk_means_not_found_without_calling_the_llm():
    service, _, _, llm = make_service([chunk(1, "Football", 0.8)])

    answer = await service.answer("How does the offside rule work?")

    assert not answer.found
    assert answer.text == NOT_FOUND_MESSAGE
    assert answer.sources == ()
    assert llm.calls == []
    assert answer.timings_ms["llm_ms"] == 0.0


async def test_llm_not_found_reply_is_reported_as_not_found():
    service, _, _, llm = make_service([chunk(1, "Overfitting", 0.2)], reply="NOT_FOUND")

    answer = await service.answer("Who won the 2022 World Cup?")

    assert not answer.found
    assert answer.text == NOT_FOUND_MESSAGE
    assert len(llm.calls) == 1


async def test_k_overrides_the_default():
    service, _, retriever, _ = make_service([chunk(i, f"A{i}", 0.1) for i in range(10)])

    chunks, timings = await service.search("question", k=7)

    assert len(chunks) == 7
    assert retriever.calls[0][1] == 7
    assert set(timings) == {"embed_ms", "retrieve_ms"}


async def test_empty_question_is_rejected():
    service, *_ = make_service([])

    with pytest.raises(ValueError):
        await service.answer("   ")
