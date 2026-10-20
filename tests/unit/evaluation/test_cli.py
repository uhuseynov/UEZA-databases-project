import pytest

from src.evaluation.__main__ import explain_plans, main

pytestmark = pytest.mark.anyio


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    async def explain(self, query_vector, k=5, filters=None, *, exact=False):
        self.calls.append((len(query_vector), exact))
        return [{"id": 1, "select_type": "SIMPLE", "table": "c", "type": "index",
                 "key": None if exact else "embedding", "rows": 10, "Extra": ""}]


async def test_explain_plans_covers_index_and_exact_for_each_case():
    retriever = FakeRetriever()

    markdown = await explain_plans(retriever, dimension=8)

    assert len(retriever.calls) == 6
    assert {exact for _, exact in retriever.calls} == {False, True}
    assert all(size == 8 for size, _ in retriever.calls)
    assert "| 1 | SIMPLE | c | index | embedding | 10 |  |" in markdown
    assert "exact (ORDER BY distance + 0)" in markdown


async def test_missing_ground_truth_exits_with_code_2(tmp_path, capsys):
    code = await main(["--ground-truth", str(tmp_path / "missing.csv"), "run"])

    assert code == 2
    assert "Cannot load the ground truth" in capsys.readouterr().err
