"""Token-based article chunking using LangChain."""

from __future__ import annotations

import re
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_CONFIGS = {
    "A": (256, 32),
    "B": (512, 64),
    "C": (512, 0),
}


def chunk_article(
    title: str,
    text: str,
    tokenizer: Any,
    config: str = "A",
) -> list[str]:
    """Chunk articles using the embedding model tokenizer."""

    if config not in CHUNK_CONFIGS:
        raise ValueError(f"Invalid chunk config: {config}")

    if not title.strip():
        raise ValueError("Article title cannot be empty")

    if not text.strip():
        return []

    size, overlap = CHUNK_CONFIGS[config]

    prefix = f"Title: {title}\n\n"

    # Reserve the article title and model special tokens.
    prefix_tokens = len(tokenizer.encode(prefix, add_special_tokens=False))

    special_tokens = tokenizer.num_special_tokens_to_add(pair=False)

    budget = size - prefix_tokens - special_tokens

    if budget <= overlap:
        raise ValueError("Insufficient token budget for chunking")

    if config == "C":
        # Preserve paragraph boundaries.
        source_units = [
            paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()
        ]

        splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
            tokenizer,
            chunk_size=budget,
            chunk_overlap=0,
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=False,
        )

        chunks = []

        for paragraph in source_units:
            chunks.extend(splitter.split_text(paragraph))

    else:
        splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
            tokenizer,
            chunk_size=budget,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=False,
        )

        chunks = splitter.split_text(text)

    result = []

    for chunk in chunks:
        value = prefix + chunk.strip()

        if not chunk.strip():
            continue

        token_count = len(
            tokenizer.encode(
                value,
                add_special_tokens=True,
            )
        )

        if token_count > size:
            raise ValueError(f"Chunk exceeds limit: {token_count} > {size}")

        result.append(value)

    return result
