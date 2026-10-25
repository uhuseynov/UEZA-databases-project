"""Unit tests for token-based article chunking."""

from collections.abc import Callable
from typing import Any

import pytest
from transformers import AutoTokenizer

from src.ingestion.chunker import chunk_article


@pytest.fixture(scope="module")
def tokenizer() -> Any:
    return AutoTokenizer.from_pretrained(
        "BAAI/bge-base-en-v1.5",
        use_fast=True,
    )


@pytest.fixture(scope="module")
def count_tokens(tokenizer: Any) -> Callable[[str], int]:
    def count(value: str) -> int:
        return len(
            tokenizer.encode(
                value,
                add_special_tokens=True,
            )
        )

    return count


def make_text(words: int = 3000) -> str:
    return " ".join(f"word{i % 1000}" for i in range(words))


def test_empty_text(tokenizer: Any) -> None:
    assert (
        chunk_article(
            "Test",
            "",
            tokenizer,
            "A",
        )
        == []
    )


def test_invalid_title(tokenizer: Any) -> None:
    with pytest.raises(ValueError):
        chunk_article(
            "",
            "Some text.",
            tokenizer,
            "A",
        )


def test_invalid_config(tokenizer: Any) -> None:
    with pytest.raises(ValueError):
        chunk_article(
            "Test",
            "Some text.",
            tokenizer,
            "INVALID",
        )


@pytest.mark.parametrize(
    ("config", "maximum"),
    [
        ("A", 256),
        ("B", 512),
        ("C", 512),
    ],
)
def test_token_limits(
    tokenizer: Any,
    count_tokens: Callable[[str], int],
    config: str,
    maximum: int,
) -> None:
    chunks = chunk_article(
        title="Test article",
        text=make_text(),
        tokenizer=tokenizer,
        config=config,
    )

    assert len(chunks) > 1

    assert all(count_tokens(chunk) <= maximum for chunk in chunks)


@pytest.mark.parametrize(
    "config",
    ["A", "B", "C"],
)
def test_every_chunk_starts_with_title(
    tokenizer: Any,
    config: str,
) -> None:
    title = "Artificial intelligence"

    chunks = chunk_article(
        title,
        make_text(1500),
        tokenizer,
        config,
    )

    assert chunks

    assert all(chunk.startswith(f"Title: {title}\n\n") for chunk in chunks)


def test_small_article_single_chunk(
    tokenizer: Any,
) -> None:
    chunks = chunk_article(
        "Machine learning",
        "Machine learning is useful.",
        tokenizer,
        "A",
    )

    assert len(chunks) == 1
    assert "Machine learning is useful." in chunks[0]


def test_long_article_multiple_chunks(
    tokenizer: Any,
) -> None:
    chunks = chunk_article(
        "Test",
        make_text(),
        tokenizer,
        "A",
    )

    assert len(chunks) > 5


def test_config_b_uses_fewer_chunks(
    tokenizer: Any,
) -> None:
    content = make_text()

    chunks_a = chunk_article("Test", content, tokenizer, "A")

    chunks_b = chunk_article("Test", content, tokenizer, "B")

    assert len(chunks_b) < len(chunks_a)


def test_paragraph_mode_preserves_separation(
    tokenizer: Any,
) -> None:
    content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

    chunks = chunk_article(
        "Test",
        content,
        tokenizer,
        "C",
    )

    assert len(chunks) == 3
    assert "First paragraph." in chunks[0]
    assert "Second paragraph." in chunks[1]
    assert "Third paragraph." in chunks[2]


def test_long_paragraph_is_split(
    tokenizer: Any,
    count_tokens: Callable[[str], int],
) -> None:
    chunks = chunk_article(
        "Test",
        make_text(),
        tokenizer,
        "C",
    )

    assert len(chunks) > 1

    assert all(count_tokens(chunk) <= 512 for chunk in chunks)


def test_chunk_content_is_not_empty(
    tokenizer: Any,
) -> None:
    chunks = chunk_article(
        "Test",
        make_text(1000),
        tokenizer,
        "A",
    )

    assert chunks

    assert all(chunk.removeprefix("Title: Test").strip() for chunk in chunks)


def test_deterministic_chunking(
    tokenizer: Any,
) -> None:
    content = make_text(1000)

    first = chunk_article("Test", content, tokenizer, "A")

    second = chunk_article("Test", content, tokenizer, "A")

    assert first == second


def test_long_title_rejected(
    tokenizer: Any,
) -> None:
    title = " ".join(["Artificial intelligence"] * 200)

    with pytest.raises(ValueError):
        chunk_article(
            title,
            "Some text.",
            tokenizer,
            "A",
        )
