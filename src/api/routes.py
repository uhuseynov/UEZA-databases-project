import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.api.schemas import AskRequest, AskResponse, ChunkOut, FilterParams, SearchResponse
from src.ingestion.mediawiki import MediaWikiClient, MediaWikiError, WikiArticle
from src.rag.llm import LLMError
from src.rag.service import RAGService

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DATABASE_ERROR = "Database search failed. Is MariaDB running and is the schema loaded?"
# Fixed on purpose: the details of an upstream failure (URL, reply body) go to the log only.
LLM_ERROR = "The language model request failed. Try again later."

router = APIRouter()


async def get_rag_service(request: Request) -> RAGService:
    # The first call loads the embedding model, which takes a few seconds:
    # do it in a worker thread so the event loop keeps serving other requests.
    return await asyncio.to_thread(request.app.state.container.rag_service)


async def get_mediawiki_client(request: Request) -> AsyncGenerator[MediaWikiClient]:
    """One MediaWiki client per request, closed when the request ends (also on errors).

    The container's provider is a Factory: every client has its own HTTP connection pool,
    while the article cache is a shared singleton.
    """
    client = request.app.state.container.mediawiki_client()
    try:
        yield client
    finally:
        client.close()


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/search", response_model=SearchResponse, tags=["rag"])
async def search(
    service: Annotated[RAGService, Depends(get_rag_service)],
    q: Annotated[str, Query(min_length=1, max_length=1000, description="The question")],
    # /search may list more chunks than /ask (at most 20: they all go into the LLM prompt);
    # the retriever's own MAX_K (100) is only a safety cap for programmatic callers.
    k: Annotated[int, Query(ge=1, le=50)] = 5,
    category: str | None = None,
    root_category: str | None = None,
    min_length: Annotated[int | None, Query(ge=0)] = None,
    max_length: Annotated[int | None, Query(ge=0)] = None,
    # `| str` lets an empty form field through (FilterParams turns "" into "no filter") and
    # keeps the error body of a bad date in the same shape as the other filter errors.
    edited_since: date | str | None = None,
    edited_before: date | str | None = None,
    linked_from: str | None = None,
) -> SearchResponse:
    """Vector search over the chunks, optionally constrained by SQL filters."""
    filters = _parse_filters(
        category=category,
        root_category=root_category,
        min_length=min_length,
        max_length=max_length,
        edited_since=edited_since,
        edited_before=edited_before,
        linked_from=linked_from,
    )
    try:
        chunks, timings = await service.search(q, k, filters.to_filters())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Search failed")
        raise HTTPException(status_code=503, detail=DATABASE_ERROR) from exc

    return SearchResponse(
        question=q,
        filters=filters.to_filters().as_dict(),
        results=[ChunkOut.from_chunk(chunk) for chunk in chunks],
        timings_ms=timings,
    )


@router.post("/ask", response_model=AskResponse, tags=["rag"])
async def ask(
    body: AskRequest,
    service: Annotated[RAGService, Depends(get_rag_service)],
) -> AskResponse:
    """Answer a question from the retrieved chunks, with the source articles."""
    filters = body.filters.to_filters()
    try:
        answer = await service.answer(body.question, body.k, filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Search failed")
        raise HTTPException(status_code=503, detail=DATABASE_ERROR) from exc
    except LLMError as exc:
        # The message names the endpoint without credentials and quotes the start of the
        # upstream reply; no traceback, whose chained errors could repeat the raw request.
        logger.error("LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail=LLM_ERROR) from exc

    return AskResponse.from_answer(answer, filters)


@router.get("/articles/{title}")
async def get_wiki_article(
    title: str,
    client: Annotated[MediaWikiClient, Depends(get_mediawiki_client)],
) -> WikiArticle:
    """Fetch a Wikipedia article (the latest revision, through the article cache)."""
    try:
        # The client is synchronous (blocking HTTP, rate-limiter sleeps): keep it off the
        # event loop, as the embedding model is in the RAG service.
        return await asyncio.to_thread(client.get_article, title)
    except MediaWikiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _parse_filters(**values) -> FilterParams:
    try:
        return FilterParams(**values)
    except ValidationError as exc:
        detail = [{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail=detail) from exc
