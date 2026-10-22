from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator

from src.rag.models import Answer, RetrievedChunk, SearchFilters


class FilterParams(BaseModel):
    """SQL filters as they arrive from the API. Empty strings mean "no filter"."""

    category: str | None = Field(default=None, max_length=255)
    root_category: str | None = Field(default=None, max_length=100)
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    edited_since: date | None = None
    edited_before: date | None = None
    linked_from: str | None = Field(default=None, max_length=255)

    @field_validator("*", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    def to_filters(self) -> SearchFilters:
        return SearchFilters(
            category=self.category,
            root_category=self.root_category,
            min_length=self.min_length,
            max_length=self.max_length,
            edited_since=_midnight(self.edited_since),
            edited_before=_midnight(self.edited_before),
            linked_from=self.linked_from,
        )


def _midnight(day: date | None) -> datetime | None:
    return datetime.combine(day, time.min) if day else None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    filters: FilterParams = Field(default_factory=FilterParams)


class ChunkOut(BaseModel):
    chunk_id: int
    title: str
    url: str | None
    chunk_index: int
    text: str
    distance: float

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> ChunkOut:
        return cls(
            chunk_id=chunk.chunk_id,
            title=chunk.title,
            url=chunk.url,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            distance=round(chunk.distance, 4),
        )


class SourceOut(BaseModel):
    title: str
    url: str | None


class SearchResponse(BaseModel):
    question: str
    filters: dict[str, str | int]
    results: list[ChunkOut]
    timings_ms: dict[str, float]


class AskResponse(BaseModel):
    question: str
    answer: str
    found: bool
    filters: dict[str, str | int]
    sources: list[SourceOut]
    chunks: list[ChunkOut]
    timings_ms: dict[str, float]

    @classmethod
    def from_answer(cls, answer: Answer, filters: SearchFilters) -> AskResponse:
        return cls(
            question=answer.question,
            answer=answer.text,
            found=answer.found,
            filters=filters.as_dict(),
            sources=[SourceOut(title=s.title, url=s.url) for s in answer.sources],
            chunks=[ChunkOut.from_chunk(c) for c in answer.chunks],
            timings_ms=answer.timings_ms,
        )
