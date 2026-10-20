from src.rag.models import RetrievedChunk, Source
from src.rag.prompt import (
    NOT_FOUND,
    build_messages,
    cited_passages,
    format_context,
    is_not_found,
    sources_for,
)


def chunk(chunk_id: int, title: str, text: str = "text", chunk_index: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        article_id=chunk_id,
        title=title,
        url=f"https://en.wikipedia.org/wiki/{title}",
        chunk_index=chunk_index,
        text=text,
        distance=0.2,
    )


CHUNKS = [chunk(1, "Overfitting", "Overfitting is ..."), chunk(2, "Dropout", "Dropout is ...", 3)]


def test_context_numbers_passages_and_names_their_article():
    context = format_context(CHUNKS)

    assert context.startswith("[1] Overfitting (part 1)\nOverfitting is ...")
    assert "[2] Dropout (part 4)\nDropout is ..." in context


def test_messages_contain_rules_passages_and_question():
    messages = build_messages("What is overfitting?", CHUNKS)

    assert messages[0]["role"] == "system"
    assert NOT_FOUND in messages[0]["content"]
    assert "only" in messages[0]["content"]
    assert messages[1]["content"].endswith("Question: What is overfitting?")
    assert "[2] Dropout" in messages[1]["content"]


def test_not_found_detection_tolerates_case_and_a_trailing_dot():
    assert is_not_found("NOT_FOUND")
    assert is_not_found(" not_found. ")
    assert not is_not_found("Overfitting is NOT_FOUND in this text")


def test_cited_passages_are_unique_ordered_and_in_range():
    assert cited_passages("A [2]. B [1][2]. C [7].", passage_count=2) == [2, 1]


def test_sources_follow_citations_and_deduplicate_articles():
    chunks = [chunk(1, "A"), chunk(2, "B"), chunk(3, "A", chunk_index=1)]

    sources = sources_for("Fact [3]. Another fact [1][2].", chunks)

    assert sources == (
        Source(title="A", url="https://en.wikipedia.org/wiki/A"),
        Source(title="B", url="https://en.wikipedia.org/wiki/B"),
    )


def test_sources_fall_back_to_all_context_articles_without_citations():
    sources = sources_for("An answer without citations.", CHUNKS)

    assert [s.title for s in sources] == ["Overfitting", "Dropout"]
