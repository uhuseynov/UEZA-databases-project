from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class WikiArticle:
    page_id: int
    title: str
    text: str
    length: int
    revision_id: int
    last_modified: datetime
    categories: tuple[str, ...]
    links: tuple[str, ...]
