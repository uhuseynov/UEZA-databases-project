import re
from collections.abc import Sequence

from src.rag.models import RetrievedChunk, Source

NOT_FOUND = "NOT_FOUND"

SYSTEM_PROMPT = (
    "You answer questions using only the numbered Wikipedia passages you are given.\n"
    "Rules:\n"
    "1. Use only facts stated in the passages. Do not add outside knowledge.\n"
    "2. After each sentence, cite the passages it is based on by number, like [1] or [2][3].\n"
    f"3. If the passages do not contain the answer, reply with exactly {NOT_FOUND} "
    "and nothing else.\n"
    "4. Keep the answer short: at most a few sentences."
)

_CITATION = re.compile(r"\[(\d+)\]")


def format_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Number the passages so the model can cite them as [1], [2], ..."""
    return "\n\n".join(
        f"[{number}] {chunk.title} (part {chunk.chunk_index + 1})\n{chunk.text.strip()}"
        for number, chunk in enumerate(chunks, start=1)
    )


def build_messages(question: str, chunks: Sequence[RetrievedChunk]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Passages:\n\n{format_context(chunks)}\n\nQuestion: {question}",
        },
    ]


def is_not_found(reply: str) -> bool:
    return reply.strip().strip(".").upper() == NOT_FOUND


def cited_passages(reply: str, passage_count: int) -> list[int]:
    """Passage numbers cited in the reply, in order of first mention, without duplicates."""
    seen: list[int] = []
    for match in _CITATION.finditer(reply):
        number = int(match.group(1))
        if 1 <= number <= passage_count and number not in seen:
            seen.append(number)
    return seen


def sources_for(reply: str, chunks: Sequence[RetrievedChunk]) -> tuple[Source, ...]:
    """The articles behind the cited passages, one entry per article.

    If the model cited nothing, every article in the context is listed, because the
    answer can only have come from those passages.
    """
    cited = cited_passages(reply, len(chunks))
    selected = [chunks[n - 1] for n in cited] if cited else list(chunks)

    sources: list[Source] = []
    titles: set[str] = set()
    for chunk in selected:
        if chunk.title not in titles:
            titles.add(chunk.title)
            sources.append(Source(title=chunk.title, url=chunk.url))
    return tuple(sources)
