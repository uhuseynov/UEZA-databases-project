import pytest

from src.evaluation.__main__ import build_parser, explain_plans, main, summarize_analyze

pytestmark = pytest.mark.anyio

PLAN = {
    "query_block": {
        "select_id": 1,
        "r_total_time_ms": 12.5,
        "filesort": {
            "r_total_time_ms": 3.25,
            "r_output_rows": 10,
            "r_used_priority_queue": True,
            "temporary_table": {
                "nested_loop": [
                    {"table": {"table_name": "a", "access_type": "ref", "key": "idx",
                               "rows": 5, "r_loops": 1, "r_rows": 4}},
                    {"table": {"table_name": "c", "access_type": "ref", "key": "uq_chunks_position",
                               "rows": 15, "r_loops": 4, "r_rows": 20.5}},
                ]
            },
        },
    }
}


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool, str]] = []
        self.analyzed: list[tuple[bool, str, str]] = []

    async def explain(self, query_vector, k=5, filters=None, *, exact=False, shape="join",
                      vector_format="text"):
        self.calls.append((len(query_vector), exact, shape))
        return [{"id": 1, "select_type": "SIMPLE", "table": "c", "type": "index",
                 "key": None if exact else "embedding", "rows": 10, "Extra": ""}]

    async def analyze(self, query_vector, k=5, filters=None, *, exact=False, shape="join",
                      vector_format="text"):
        self.analyzed.append((exact, shape, vector_format))
        return PLAN


async def test_explain_plans_covers_index_and_exact_for_each_case():
    retriever = FakeRetriever()

    markdown = await explain_plans(retriever, dimension=8)

    assert len(retriever.calls) == 10
    assert {exact for _, exact, _ in retriever.calls} == {False, True}
    assert {shape for _, _, shape in retriever.calls} == {"join", "nearest_first"}
    assert all(size == 8 for size, _, _ in retriever.calls)
    assert "| 1 | SIMPLE | c | index | embedding | 10 |  |" in markdown
    assert "exact (ORDER BY distance + 0)" in markdown
    assert "linked from Artificial intelligence" in markdown
    # every analyzed statement once with each vector format
    assert len(retriever.analyzed) == 10
    assert {fmt for _, _, fmt in retriever.analyzed} == {"text", "binary"}


def test_summarize_analyze_lists_tables_and_sorts():
    lines = summarize_analyze(PLAN)
    text = "\n".join(lines)

    assert lines[0] == "Total 12.50 ms in the server."
    assert "| a | ref | idx | 5 | 1 | 4 |" in text
    assert "| c | ref | uq_chunks_position | 15 | 4 | 20.5 |" in text
    assert "filesort: 3.25 ms, 10 rows out, priority queue True" in text


@pytest.mark.parametrize("argv", [["m-sweep", "--m", "2"], ["m-sweep", "--m", "201"],
                                  ["run", "--runs", "0"], ["run", "--shape", "chunks"]])
def test_parser_rejects_invalid_values(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_m_sweep_defaults():
    args = build_parser().parse_args(["m-sweep"])

    assert args.m == [6, 8, 16, 32, 48, 64]
    assert args.ef == [20, 40, 80]
    assert args.shapes == ["join", "nearest_first"]
    assert not args.no_restart


async def test_missing_ground_truth_exits_with_code_2(tmp_path, capsys):
    code = await main(["--ground-truth", str(tmp_path / "missing.csv"), "run"])

    assert code == 2
    assert "Cannot load the ground truth" in capsys.readouterr().err
