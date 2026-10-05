from typing import Any, Literal

Kind = Literal["query", "passage"]


class Embedder:
    """Turns text into normalized vectors.

    Chunks (passages) and user questions (queries) must go through the same model,
    otherwise their vectors are not comparable. Some models (bge, e5) expect a
    different prefix for queries and passages, so both are configurable.
    """

    def __init__(
        self,
        model_name: str,
        dimension: int,
        query_prefix: str = "",
        passage_prefix: str = "",
        model: Any | None = None,
    ) -> None:
        if model is None:
            # Heavy import (torch), loaded only when a real model is needed
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)

        actual = model.get_sentence_embedding_dimension()
        if actual != dimension:
            raise ValueError(
                f"{model_name} produces {actual}-dimensional vectors, "
                f"but EMBEDDING_DIMENSION is {dimension}"
            )

        self.model = model
        self.model_name = model_name
        self.dimension = dimension
        self.prefixes: dict[Kind, str] = {"query": query_prefix, "passage": passage_prefix}

    def embed(self, texts: list[str], kind: Kind = "passage") -> list[list[float]]:
        if not texts:
            return []

        prefix = self.prefixes[kind]
        vectors = self.model.encode(
            [prefix + text for text in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.tolist()