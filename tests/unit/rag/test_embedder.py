import numpy as np
import pytest

from src.rag.embedder import Embedder


class FakeModel:
    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        return np.full((len(texts), self.dimension), 1 / np.sqrt(self.dimension))


def make_embedder(model: FakeModel, **kwargs) -> Embedder:
    return Embedder(model_name="fake", dimension=model.dimension, model=model, **kwargs)


def test_rejects_dimension_mismatch():
    with pytest.raises(ValueError, match="4-dimensional"):
        Embedder(model_name="fake", dimension=768, model=FakeModel(dimension=4))


def test_query_prefix_is_used_only_for_queries():
    model = FakeModel()
    embedder = make_embedder(model, query_prefix="Q: ")

    embedder.embed(["what is AI?"], kind="query")
    embedder.embed(["AI is a field of CS."])

    assert model.calls[0][0] == ["Q: what is AI?"]
    assert model.calls[1][0] == ["AI is a field of CS."]


def test_passage_prefix_is_applied():
    model = FakeModel()
    embedder = make_embedder(model, passage_prefix="passage: ")

    embedder.embed(["some chunk"], kind="passage")

    assert model.calls[0][0] == ["passage: some chunk"]


def test_returns_one_normalized_vector_per_text():
    model = FakeModel()
    embedder = make_embedder(model)

    vectors = embedder.embed(["a", "b", "c"])

    assert len(vectors) == 3
    assert all(len(v) == model.dimension for v in vectors)
    assert model.calls[0][1]["normalize_embeddings"] is True


def test_empty_input_does_not_call_model():
    model = FakeModel()
    embedder = make_embedder(model)

    assert embedder.embed([]) == []
    assert model.calls == []