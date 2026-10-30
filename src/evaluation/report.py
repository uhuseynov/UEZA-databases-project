"""Write evaluation results as JSON (full data) and Markdown (tables for the README)."""

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _clean(value: Any) -> Any:
    """NaN is not valid JSON: write it as null."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(item) for item in value]
    return value


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_fmt(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _environment_lines(environment: dict[str, Any]) -> list[str]:
    return [f"- {key}: `{value}`" for key, value in environment.items()]


def render_evaluation(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    config = report["config"]
    k_values = config["k_values"]
    mode = "exact search (no index)" if config["exact"] else (
        f"HNSW index, mhnsw_ef_search={config['ef_search'] or 'server default'}"
    )
    mode += (
        f", statement shape {config.get('shape', 'join')}, "
        f"query vector as {config.get('vector_format', 'text')}"
    )

    retrieval_rows = [
        [name, data["questions"], *[data[f"recall@{k}"] for k in k_values], data["mrr"]]
        for name, data in metrics["retrieval"].items()
    ]
    latency_rows = [
        [name, data["samples"], data["mean_ms"], data["std_ms"], data["p50_ms"], data["p95_ms"]]
        for name, data in metrics["latency"].items()
        if isinstance(data, dict) and name != "run_to_run"
    ]
    run_to_run = metrics["latency"]["run_to_run"]
    not_found = metrics["not_found"]
    configured, best = not_found["configured_threshold"], not_found["best_threshold"]

    parts = [
        f"# Evaluation: {report['label']}",
        "",
        f"Created {report['created_at']}. {mode}. "
        f"{config['runs']} timed runs after {config['warmup_runs']} warm-up run(s).",
        "",
        "## Retrieval (answerable questions)",
        "",
        _table(["questions", "n", *[f"Recall@{k}" for k in k_values], "MRR"], retrieval_rows),
        "",
        "## Search latency (MariaDB query only, embedding excluded)",
        "",
        _table(["questions", "samples", "mean ms", "std ms", "p50 ms", "p95 ms"], latency_rows),
        "",
        f"Run-to-run: mean of the per-run averages {_fmt(run_to_run['mean_ms'])} ms, "
        f"standard deviation {_fmt(run_to_run['std_ms'])} ms over {run_to_run['samples']} runs.",
        "",
        "## Not found",
        "",
        "Distance of the closest chunk (lower is closer):",
        "",
        _table(
            ["questions", "n", "mean", "min", "median", "max"],
            [
                [name, data["samples"], data["mean"], data["min"], data["p50"], data["max"]]
                for name, data in (
                    ("answerable", not_found["answerable_top_distance"]),
                    ("unanswerable", not_found["unanswerable_top_distance"]),
                )
            ],
        ),
        "",
        f"With RAG_MAX_DISTANCE={_fmt(configured['threshold'])}: "
        f"{_fmt(configured['answerable_kept'])} of answerable questions keep their context, "
        f"{_fmt(configured['unanswerable_rejected'])} of unanswerable ones are rejected.",
    ]
    if best:
        parts.append(
            f"Best separating threshold on this set: {_fmt(best['threshold'], 4)} "
            f"(balanced accuracy {_fmt(best['balanced_accuracy'])})."
        )
    if metrics["filtered_with_fewer_than_k_results"]:
        parts += [
            "",
            f"Filtered questions that returned fewer than {max(k_values)} chunks: "
            + ", ".join(metrics["filtered_with_fewer_than_k_results"]),
        ]
    if metrics["unstable_questions"]:
        parts += ["", "Questions whose results changed between runs: "
                  + ", ".join(metrics["unstable_questions"])]
    if metrics["errors"]:
        parts += ["", "## Errors", ""]
        parts += [f"- {qid}: `{error}`" for qid, error in metrics["errors"].items()]
    if report.get("environment"):
        parts += ["", "## Environment", "", *_environment_lines(report["environment"])]
    return "\n".join(parts) + "\n"


def render_sweep(report: dict[str, Any]) -> str:
    config = report["config"]
    k = config["k"]
    rows = [
        [
            row["ef_search"],
            row[f"index_recall@{k}"],
            row[f"index_recall@{k}_plain"],
            row[f"index_recall@{k}_filtered"],
            row["retrieval"].get(f"recall@{k}"),
            row["retrieval"]["mrr"],
            row["latency"]["mean_ms"],
            row["latency"]["p95_ms"],
            row.get("latency_plain", {}).get("mean_ms"),
            row["latency_filtered"]["mean_ms"],
            len(row["filtered_with_fewer_than_k_results"]),
        ]
        for row in report["rows"]
    ]
    parts = [
        "# mhnsw_ef_search sweep",
        "",
        f"Created {report['created_at']}. {config['runs']} timed runs per setting. "
        f"Statement shape {config.get('shape', 'join')}, query vector as "
        f"{config.get('vector_format', 'text')}. "
        f"Index recall = share of the exact top-{k} chunks (full scan) that the index returned.",
        "",
        _table(
            [
                "ef_search",
                f"index recall@{k}",
                "plain",
                "filtered",
                f"Recall@{k}",
                "MRR",
                "mean ms",
                "p95 ms",
                "plain mean ms",
                "filtered mean ms",
                f"filtered < {k} results",
            ],
            rows,
        ),
    ]
    if report.get("environment"):
        parts += ["", "## Environment", "", *_environment_lines(report["environment"])]
    return "\n".join(parts) + "\n"


def render_m_sweep(report: dict[str, Any]) -> str:
    config = report["config"]
    k = config["k"]
    rows = [
        [
            row["m"] if row["m"] is not None else "–",
            row["state"] or "–",
            row["shape"],
            row["ef_search"],
            row[f"index_recall@{k}"],
            row["retrieval"].get("recall@1"),
            row["retrieval"].get(f"recall@{k}"),
            row["retrieval"]["mrr"],
            row["latency"]["mean_ms"],
            row["latency"]["p50_ms"],
            row["latency"]["p95_ms"],
        ]
        for row in report["rows"]
    ]
    parts = [
        "# Vector index M sweep",
        "",
        f"Created {report['created_at']}. {config['questions']} questions without a filter, "
        f"{config['runs']} timed runs per setting after {config['warmup_runs']} warm-up run(s), "
        f"query vector as {config['vector_format']}. For every M the index was dropped and "
        "added again, measured right after the build (built)"
        + (" and after a server restart (restarted)." if config["restarted"] else ".")
        + f" Index recall = share of the exact top-{k} chunks (full scan) that the search returned.",
        "",
        "## Index build",
        "",
        _table(["M", "build s"], [[b["m"], b["build_seconds"]] for b in report["builds"]]),
        "",
        "## Searches",
        "",
        _table(
            ["M", "state", "shape", "ef_search", f"index recall@{k}", "Recall@1", f"Recall@{k}",
             "MRR", "mean ms", "p50 ms", "p95 ms"],
            rows,
        ),
    ]
    if report.get("environment"):
        parts += ["", "## Environment", "", *_environment_lines(report["environment"])]
    return "\n".join(parts) + "\n"


def write_report(report: dict[str, Any], results_dir: str | Path) -> tuple[Path, Path]:
    """Write ``<timestamp>_<label>.json`` and ``.md`` and return both paths."""
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    label = report.get("label") or report["kind"]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "run"
    stem = f"{datetime.now(UTC):%Y%m%d-%H%M%S}_{slug}"

    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(_clean(report), indent=2, ensure_ascii=False), encoding="utf-8")
    renderer = {
        "ef_search_sweep": render_sweep,
        "m_sweep": render_m_sweep,
    }.get(report["kind"], render_evaluation)
    md_path.write_text(renderer(report), encoding="utf-8")
    return json_path, md_path
