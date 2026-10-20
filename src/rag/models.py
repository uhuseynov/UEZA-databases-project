from dataclasses import dataclass, field, fields
from datetime import datetime


@dataclass(slots=True, frozen=True)
class SearchFilters:
    """Ordinary SQL predicates applied in the same statement as the vector search.

    Every field is optional; ``None`` means "do not filter on this".

    - ``category``: an exact Wikipedia category (``article_categories.category``).
    - ``root_category``: the dataset group an article was collected from, as in
      ``data/articles.csv`` (needs an ``articles.root_category`` column).
    - ``min_length`` / ``max_length``: inclusive bounds on ``articles.article_length``.
    - ``edited_since``: inclusive lower bound on ``articles.last_edit_date``.
    - ``edited_before``: exclusive upper bound on ``articles.last_edit_date``.
    - ``linked_from``: only articles that the article with this title links to.
    """

    category: str | None = None
    root_category: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    edited_since: datetime | None = None
    edited_before: datetime | None = None
    linked_from: str | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))

    def as_dict(self) -> dict[str, str | int]:
        """Only the filters that are set, in a JSON-friendly form."""
        result: dict[str, str | int] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            result[f.name] = value.isoformat() if isinstance(value, datetime) else value
        return result


@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    chunk_id: int
    article_id: int
    title: str
    url: str | None
    chunk_index: int
    text: str
    distance: float


@dataclass(slots=True, frozen=True)
class Source:
    title: str
    url: str | None


@dataclass(slots=True, frozen=True)
class Answer:
    question: str
    text: str
    found: bool
    sources: tuple[Source, ...] = ()
    chunks: tuple[RetrievedChunk, ...] = ()
    timings_ms: dict[str, float] = field(default_factory=dict)
