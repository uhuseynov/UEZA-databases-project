"""The README charts: drawn from the committed reports, and the committed SVGs are current."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("plot_results", ROOT / "scripts" / "plot_results.py")
plot_results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plot_results)


def test_m_sweep_points_match_the_documented_table():
    points = {p["m"]: p for p in plot_results.m_sweep_points()}

    assert sorted(points) == [6, 8, 16, 32, 48, 64]
    # docs/database/Vector-Search.md, "Choosing M and ef_search", at mhnsw_ef_search 40
    assert points[16]["build_s"] == 5.47
    assert points[16]["index_recall"] == pytest.approx(0.948, abs=5e-4)
    assert points[32]["index_recall"] == pytest.approx(0.987, abs=5e-4)
    assert points[16]["recall10"] == points[32]["recall10"] == pytest.approx(0.977, abs=5e-4)
    assert points[64]["build_s"] == 134.76
    # M 8, 16 and 32 come from the second sweep, with the query vector as binary
    assert {m: p["vector"] for m, p in points.items()} == {
        6: "text",
        8: "binary",
        16: "binary",
        32: "binary",
        48: "text",
        64: "text",
    }


def test_faiss_points_match_the_documented_numbers():
    points = plot_results.faiss_points()

    # docs/database/FAISS-Baseline.md
    assert points["plain"]["mariadb"]["mean_ms"] == pytest.approx(5.09, abs=0.005)
    assert points["plain"]["faiss"]["mean_ms"] == pytest.approx(6.26, abs=0.005)
    assert points["filtered"]["mariadb"] == {"mean_ms": 8.384, "index_recall": 1.0}
    assert points["filtered"]["faiss"]["mean_ms"] == pytest.approx(17.15)
    assert points["filtered"]["faiss"]["index_recall"] == pytest.approx(0.871, abs=5e-4)


@pytest.mark.parametrize(
    ("value", "expected"), [(17.15, "17.2"), (5.092, "5.1"), (134.76, "134.8")]
)
def test_one_decimal_rounds_half_up(value, expected):
    assert plot_results.one_decimal(value) == expected


def test_the_charts_are_valid_svg_with_both_colour_schemes():
    for content in (
        plot_results.m_sweep_svg(plot_results.m_sweep_points()),
        plot_results.faiss_svg(plot_results.faiss_points()),
    ):
        root = ET.fromstring(content)
        assert root.tag.endswith("svg")
        assert "prefers-color-scheme: dark" in content


@pytest.mark.parametrize(
    ("name", "draw"),
    [
        ("m-sweep.svg", lambda: plot_results.m_sweep_svg(plot_results.m_sweep_points())),
        ("mariadb-vs-faiss.svg", lambda: plot_results.faiss_svg(plot_results.faiss_points())),
    ],
)
def test_the_committed_charts_are_current(name, draw):
    committed = (ROOT / "docs" / "images" / name).read_text(encoding="utf-8")

    assert committed == draw(), f"run `make charts` to redraw docs/images/{name}"
