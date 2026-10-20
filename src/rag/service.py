import asyncio
import time
from typing import Protocol

from src.rag.models import Answer, RetrievedChunk, SearchFilters
from src.rag.prompt import build_messages, is_not_found, sources_for

NOT_FOUND_MESSAGE = "The articles in our corpus do not answer this question."


class EmbedderLike(Protocol):
    def embed(self, texts: list[str], kind: str = "passage") -> list[list[float]]: ...


class RetrieverLike(Protocol):
    async def retrieve(
        self, query_vector: list[float], k: int = 5, filters: SearchFilters | None = None
    ) -> list[RetrievedChunk]: ...


class LLMLike(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class RAGService:
    """Question in, grounded answer with sources out.

    1. Embed the question (same model as the chunks, query prefix).
    2. Retrieve the closest chunks from MariaDB, with optional SQL filters.
    3. Keep only chunks closer than ``max_distance``. If none are left, answer
       "not found" without calling the LLM.
    4. Ask the LLM to answer from the numbered chunks only and to cite them.
    """

    def __init__(
        self,
        embedder: EmbedderLike,
        retriever: RetrieverLike,
        llm: LLMLike,
        top_k: int = 5,
        max_distance: float = 0.5,
    ) -> None:
        self.embedder = embedder
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.max_distance = max_distance

    async def embed_question(self, question: str) -> list[float]:
        # The model runs on the CPU; keep it off the event loop.
        vectors = await asyncio.to_thread(self.embedder.embed, [question], "query")
        return vectors[0]

    async def search(
        self,
        question: str,
        k: int | None = None,
        filters: SearchFilters | None = None,
    ) -> tuple[list[RetrievedChunk], dict[str, float]]:
        question = _clean(question)

        start = time.perf_counter()
        vector = await self.embed_question(question)
        embed_ms = _elapsed_ms(start)

        start = time.perf_counter()
        chunks = await self.retriever.retrieve(vector, k or self.top_k, filters)
        retrieve_ms = _elapsed_ms(start)

        return chunks, {"embed_ms": embed_ms, "retrieve_ms": retrieve_ms}

    async def answer(
        self,
        question: str,
        k: int | None = None,
        filters: SearchFilters | None = None,
    ) -> Answer:
        question = _clean(question)
        total_start = time.perf_counter()

        chunks, timings = await self.search(question, k, filters)
        context = [chunk for chunk in chunks if chunk.distance <= self.max_distance]

        if not context:
            timings |= {"llm_ms": 0.0, "total_ms": _elapsed_ms(total_start)}
            return Answer(
                question=question,
                text=NOT_FOUND_MESSAGE,
                found=False,
                chunks=tuple(chunks),
                timings_ms=timings,
            )

        start = time.perf_counter()
        reply = await self.llm.complete(build_messages(question, context))
        timings |= {"llm_ms": _elapsed_ms(start), "total_ms": _elapsed_ms(total_start)}

        if is_not_found(reply):
            return Answer(
                question=question,
                text=NOT_FOUND_MESSAGE,
                found=False,
                chunks=tuple(context),
                timings_ms=timings,
            )

        return Answer(
            question=question,
            text=reply,
            found=True,
            sources=sources_for(reply, context),
            chunks=tuple(context),
            timings_ms=timings,
        )


def _clean(question: str) -> str:
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    return question
