#!/usr/bin/env python3
"""Draws the README charts from the measured results in eval/results. Standard library only.

    python scripts/plot_results.py      (or: make charts)

Writes two SVG files, so the charts always show the numbers of the committed reports:

- docs/images/m-sweep.svg: what a larger M buys (index recall, the right article in the top 10)
  and what it costs (build time), from the two M sweeps of 30 October 2026;
- docs/images/mariadb-vs-faiss.svg: time per question end to end, MariaDB's one statement
  against FAISS plus MariaDB, without and with a filter, from the FAISS run of 6 November 2026.

The SVGs carry their own light and dark colours (prefers-color-scheme), so they read on GitHub
in both themes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
IMAGES = ROOT / "docs" / "images"

# The first sweep sent the query vector as text and covered M 6 to 64; the second sent it as
# binary, the shipped format, for M 8, 16 and 32. Where both measured an M, the second wins.
M_SWEEPS = ("20261030-201017_m-sweep.json", "20261030-203723_m-sweep.json")
FAISS_RUN = "20261106-172053_faiss.json"
EF = 40  # the shipped mhnsw_ef_search
SHIPPED_M = 16

STYLE = """
  .surface { fill: #fcfcfb; }
  .t1 { fill: #0b0b0b; } .t2 { fill: #52514e; }
  .grid { stroke: #e4e3df; } .axis { stroke: #9b9a94; }
  .s1 { fill: #2a78d6; } .s2 { fill: #eb6834; }
  .l1 { stroke: #2a78d6; fill: none; } .l2 { stroke: #eb6834; fill: none; }
  .neutral { fill: #c4c2bb; } .band { fill: #2a78d6; opacity: 0.08; }
  .ring { stroke: #fcfcfb; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; }
    .t1 { fill: #f0efec; } .t2 { fill: #c3c2b7; }
    .grid { stroke: #34332f; } .axis { stroke: #6f6e68; }
    .s1 { fill: #3987e5; } .s2 { fill: #d95926; }
    .l1 { stroke: #3987e5; } .l2 { stroke: #d95926; }
    .neutral { fill: #5b5a55; } .band { fill: #3987e5; opacity: 0.14; }
    .ring { stroke: #1a1a19; }
  }
  text { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
"""


# ---------------------------------------------------------------- data


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def m_sweep_points(sweeps: tuple[str, ...] = M_SWEEPS, ef: int = EF) -> list[dict]:
    """One point per M: build seconds, index recall@10 and Recall@10 at ``ef``, measured
    right after the build with the nearest-first statement (docs/database/Vector-Search.md)."""

    points: dict[int, dict] = {}
    for name in sweeps:
        report = load(name)
        builds = {b["m"]: b["build_seconds"] for b in report["builds"]}
        for row in report["rows"]:
            if (row["state"], row["shape"], row["ef_search"]) != ("built", "nearest_first", ef):
                continue
            points[row["m"]] = {
                "m": row["m"],
                "build_s": builds[row["m"]],
                "index_recall": row["index_recall@10"],
                "recall10": row["retrieval"]["recall@10"],
                "vector": report["config"]["vector_format"],
            }
    return [points[m] for m in sorted(points)]


def faiss_points(name: str = FAISS_RUN) -> dict[str, dict[str, dict]]:
    """End-to-end mean time and index recall@10, MariaDB against FAISS plus MariaDB."""

    report = load(name)
    pick = {
        "plain": ("MariaDB statement", "FAISS HNSW, then MariaDB for the text"),
        "filtered": ("MariaDB statement", "MariaDB ids, FAISS HNSW with selector, MariaDB text"),
    }
    result: dict[str, dict[str, dict]] = {}
    for part, (mariadb, faiss) in pick.items():
        rows = {row["method"]: row for row in report[part]}
        result[part] = {
            "mariadb": _point(rows[mariadb]),
            "faiss": _point(rows[faiss]),
            "questions": rows[mariadb]["questions"],
        }
    return result


def one_decimal(value: float) -> str:
    """Rounded half up, as in the docs (17.15 ms is "17.2 ms")."""
    return f"{math.floor(value * 10 + 0.5) / 10:.1f}"


def _point(row: dict) -> dict:
    return {"mean_ms": row["latency"]["mean_ms"], "index_recall": row["index_recall@10"]}


# ---------------------------------------------------------------- SVG helpers


def text(x, y, value, cls="t2", size=12, anchor="start", weight=None) -> str:
    bold = f' font-weight="{weight}"' if weight else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" '
        f'text-anchor="{anchor}"{bold}>{escape(str(value))}</text>'
    )


def line(x1, y1, x2, y2, cls="grid", width=1) -> str:
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}" '
        f'stroke-width="{width}"/>'
    )


def bar(x, y, w, h, cls, *, horizontal=False) -> str:
    """A bar with 4 px rounded data end, square at the baseline."""
    r = min(4.0, w / 2, h / 2) if w > 0 and h > 0 else 0
    if horizontal:  # baseline on the left
        d = (
            f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z"
        )
    else:  # baseline at the bottom
        d = (
            f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z"
        )
    return f'<path d="{d}" class="{cls}"/>'


def svg(width: int, height: int, title: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
            f"<title>{escape(title)}</title>",
            f"<style>{STYLE}</style>",
            f'<rect width="{width}" height="{height}" rx="8" class="surface"/>',
            *body,
            "</svg>",
            "",
        ]
    )


# ---------------------------------------------------------------- charts


def m_sweep_svg(points: list[dict]) -> str:
    width, height = 880, 376
    body = [
        text(
            24,
            32,
            "Choosing M: past 16, more of the exact neighbours, no better answers, "
            "much longer builds",
            "t1",
            15,
            weight="600",
        ),
    ]

    # Left: recall against M (log scale), two series on one 0.80-1.00 axis.
    left, right, top, bottom = 64, 430, 104, 296
    body.append(text(left, 62, f"Share at mhnsw_ef_search {EF}", "t1", 13, weight="600"))
    m_values = [p["m"] for p in points]
    lo, hi = math.log2(min(m_values)), math.log2(max(m_values))

    def x_of(m):
        return left + (math.log2(m) - lo) / (hi - lo) * (right - left)

    def y_of(v):
        return bottom - (v - 0.80) / 0.20 * (bottom - top)

    for tick in (0.80, 0.85, 0.90, 0.95, 1.00):
        body.append(line(left, y_of(tick), right, y_of(tick)))
        body.append(text(left - 8, y_of(tick) + 4, f"{tick:.2f}", size=11, anchor="end"))
    shipped = x_of(SHIPPED_M)
    body.append(
        f'<rect x="{shipped - 14:.1f}" y="{top}" width="28" height="{bottom - top}" class="band"/>'
    )
    body.append(text(shipped, top - 6, f"shipped: M={SHIPPED_M}", "t2", 11, "middle"))
    for m in m_values:
        body.append(text(x_of(m), bottom + 18, m, size=11, anchor="middle"))
    body.append(
        text(
            (left + right) / 2,
            bottom + 38,
            "M (links per node, log scale)",
            size=11,
            anchor="middle",
        )
    )

    series = (
        ("index_recall", "1", "exact top-10 neighbours found"),
        ("recall10", "2", "right article in the top 10"),
    )
    legend_x = left
    for key, slot, label in series:
        coords = [(x_of(p["m"]), y_of(p[key])) for p in points]
        path = " ".join(f"{'L' if i else 'M'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
        body.append(f'<path d="{path}" class="l{slot}" stroke-width="2"/>')
        for x, y in coords:
            body.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="s{slot} ring" stroke-width="2"/>'
            )
        # The legend: identity by text and swatch, not by colour alone.
        body.append(f'<circle cx="{legend_x + 5:.1f}" cy="77" r="4.5" class="s{slot}"/>')
        body.append(text(legend_x + 14, 81, label, "t1", 12))
        legend_x += 14 + 7.0 * len(label) + 18
    shipped_point = next(p for p in points if p["m"] == SHIPPED_M)
    body.append(
        text(
            shipped + 12,
            y_of(shipped_point["index_recall"]) + 16,
            f"{shipped_point['index_recall']:.3f}",
            "t2",
            11,
        )
    )

    # Right: build time per M.
    left2, right2 = 500, 852
    body.append(text(left2, 62, "Index build, seconds (6,144 chunks)", "t1", 13, weight="600"))
    ymax = 140
    for tick in (0, 35, 70, 105, 140):
        y = bottom - tick / ymax * (bottom - top)
        body.append(line(left2, y, right2, y, "axis" if tick == 0 else "grid"))
        body.append(text(left2 - 8, y + 4, tick, size=11, anchor="end"))
    slot = (right2 - left2) / len(points)
    for i, p in enumerate(points):
        x = left2 + i * slot + slot * 0.2
        h = p["build_s"] / ymax * (bottom - top)
        cls = "s1" if p["m"] == SHIPPED_M else "neutral"
        body.append(bar(x, bottom - h, slot * 0.6, h, cls))
        value = one_decimal(p["build_s"])
        body.append(text(x + slot * 0.3, bottom - h - 6, value, "t1", 11, "middle"))
        body.append(text(x + slot * 0.3, bottom + 18, p["m"], size=11, anchor="middle"))
    body.append(text((left2 + right2) / 2, bottom + 38, "M", size=11, anchor="middle"))

    body.append(
        text(
            24,
            height - 28,
            "MariaDB 12.3.3, 768-dimensional bge-base vectors, 54 questions without a "
            "filter, nearest-first statement, measured right after each build.",
            "t2",
            10.5,
        )
    )
    body.append(
        text(
            24,
            height - 12,
            "M 6, 48 and 64 come from the first sweep, which sent the query vector as "
            "text. Raw reports: eval/results/20261030-*_m-sweep.md",
            "t2",
            10.5,
        )
    )
    return svg(width, height, "M sweep: recall and build time against M", body)


def faiss_svg(points: dict[str, dict[str, dict]]) -> str:
    width, height = 880, 268
    body = [
        text(
            24,
            32,
            "Time per question from Python, end to end: MariaDB alone against FAISS plus MariaDB",
            "t1",
            15,
            weight="600",
        ),
    ]
    xmax = 25.0
    panels = (
        ("plain", f"Without a filter ({points['plain']['questions']} questions)", 200, 390),
        ("filtered", f"With a filter ({points['filtered']['questions']} questions)", 620, 790),
    )
    labels = (("mariadb", "s1", "MariaDB, one statement"), ("faiss", "s2", "FAISS + MariaDB"))
    top = 84
    for part, title, left, right in panels:
        body.append(text(left - 186, 64, title, "t1", 13, weight="600"))
        for tick in range(0, 26, 5):
            x = left + tick / xmax * (right - left)
            body.append(line(x, top - 6, x, top + 104, "axis" if tick == 0 else "grid"))
            label = f"{tick} ms" if tick == 25 else tick
            body.append(text(x, top + 122, label, size=11, anchor="middle"))
        for i, (key, cls, label) in enumerate(labels):
            point = points[part][key]
            y = top + 8 + i * 50
            w = point["mean_ms"] / xmax * (right - left)
            body.append(text(left - 10, y + 17, label, "t1", 12, "end"))
            body.append(bar(left, y, w, 26, cls, horizontal=True))
            recall = point["index_recall"]
            quality = "exact top 10" if recall >= 0.9995 else f"{recall:.0%} of the exact top 10"
            body.append(
                text(
                    left + w + 8,
                    y + 12,
                    f"{one_decimal(point['mean_ms'])} ms",
                    "t1",
                    12,
                    weight="600",
                )
            )
            body.append(text(left + w + 8, y + 27, quality, "t2", 11))
    body.append(
        text(
            24,
            height - 28,
            "The same 6,144 vectors, FAISS HNSW at efSearch 40, MariaDB at "
            "mhnsw_ef_search 40. FAISS needs MariaDB for the text, and with a filter",
            "t2",
            10.5,
        )
    )
    body.append(
        text(
            24,
            height - 12,
            "first for the ids of the allowed chunks. Raw report: "
            "eval/results/20261106-172053_faiss.md",
            "t2",
            10.5,
        )
    )
    return svg(width, height, "MariaDB against FAISS plus MariaDB", body)


def main() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    outputs = {
        IMAGES / "m-sweep.svg": m_sweep_svg(m_sweep_points()),
        IMAGES / "mariadb-vs-faiss.svg": faiss_svg(faiss_points()),
    }
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
