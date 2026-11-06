"""Live sync: bring the stored articles up to their latest Wikipedia revision.

1. Ask MediaWiki for the latest revision of every stored page, 50 pages per request and
   without the text, so checking all 262 articles takes 6 requests.
2. Compare it with ``articles.revision_id``.
3. Re-ingest only the articles that changed, at their latest revision. As in the ingest,
   each article's metadata, categories, links, chunks and vectors are replaced in one
   transaction.
4. Refresh the statistics, and rebuild the vector index when the replaced chunks reach a
   share of all chunks: a deleted chunk stays in the HNSW graph as a deleted node until the
   next rebuild (docs/database/Index-State.md).

A synced article no longer matches the snapshot date in ``data/articles.csv``, so the
ground-truth questions with an edit-date filter may need checking afterwards.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.ingestion.pipeline import read_articles

logger = logging.getLogger(__name__)

DEFAULT_REBUILD_SHARE = 0.25


@dataclass(slots=True, frozen=True)
class ArticleChange:
    title: str
    page_id: int
    stored_revision: int
    latest_revision: int | None  # None: the page no longer exists
    latest_time: str | None


@dataclass(slots=True)
class SyncResult:
    checked: int
    changed: list[ArticleChange] = field(default_factory=list)
    missing: list[ArticleChange] = field(default_factory=list)
    not_stored: list[str] = field(default_factory=list)
    dry_run: bool = False
    replaced_articles: int = 0
    chunks_before: int = 0
    deleted_chunks: int = 0
    inserted_chunks: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    rebuild_share: float = DEFAULT_REBUILD_SHARE
    rebuilt: bool = False
    rebuild_seconds: float | None = None
    check_seconds: float = 0.0
    seconds: float = 0.0

    @property
    def replaced_share(self) -> float:
        return self.deleted_chunks / self.chunks_before if self.chunks_before else 0.0


async def find_changes(client, repository, rows: list[dict[str, str]]) -> SyncResult:
    """Which stored articles have a newer revision on Wikipedia, and which are gone."""

    stored = await repository.revision_ids()
    by_page = {int(row["pageid"]): row for row in rows}
    pages = [page_id for page_id in by_page if page_id in stored]

    latest = await asyncio.to_thread(client.latest_revisions, pages)

    result = SyncResult(checked=len(pages))
    result.not_stored = [row["title"] for page_id, row in by_page.items() if page_id not in stored]

    for page_id in pages:
        title = by_page[page_id]["title"]
        if page_id not in latest:
            result.missing.append(ArticleChange(title, page_id, stored[page_id], None, None))
            continue

        revision, timestamp = latest[page_id]
        if revision != stored[page_id]:
            result.changed.append(
                ArticleChange(title, page_id, stored[page_id], revision, timestamp.isoformat())
            )

    return result


async def sync_articles(
    *,
    client,
    repository,
    pipeline_factory,
    csv_path: str,
    config: str = "A",
    dry_run: bool = False,
    limit: int | None = None,
    rebuild_share: float = DEFAULT_REBUILD_SHARE,
) -> SyncResult:
    """Re-ingest the changed articles. ``pipeline_factory()`` is only called when needed,
    so a dry run does not load the embedding model."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if not 0 <= rebuild_share <= 1:
        raise ValueError("rebuild_share must be between 0 and 1")

    start = time.perf_counter()
    rows = read_articles(csv_path)
    result = await find_changes(client, repository, rows)
    result.check_seconds = time.perf_counter() - start
    result.dry_run = dry_run
    result.rebuild_share = rebuild_share

    logger.info(
        "Checked %d articles in %.1f s: %d changed, %d no longer on Wikipedia",
        result.checked, result.check_seconds, len(result.changed), len(result.missing),
    )

    to_replace = result.changed[:limit] if limit is not None else result.changed
    if dry_run or not to_replace:
        result.seconds = time.perf_counter() - start
        return result

    counts = await repository.chunk_counts()
    result.chunks_before = sum(counts.values())
    by_page = {int(row["pageid"]): row for row in rows}
    pipeline = pipeline_factory()

    for index, change in enumerate(to_replace, start=1):
        try:
            chunks = await pipeline.ingest_one(
                row=by_page[change.page_id], config=config, snapshot=False
            )
        except Exception as exc:  # noqa: BLE001 - recorded, the others continue
            logger.exception("[%d/%d] Failed: %s", index, len(to_replace), change.title)
            result.failures.append((change.title, str(exc)))
            continue

        result.replaced_articles += 1
        result.deleted_chunks += counts.get(change.page_id, 0)
        result.inserted_chunks += chunks
        logger.info("[%d/%d] %s: %d chunks", index, len(to_replace), change.title, chunks)

    if result.replaced_articles:
        await repository.analyze()
        if result.replaced_share >= rebuild_share:
            result.rebuild_seconds = await repository.rebuild_vector_index()
            result.rebuilt = True
            logger.info(
                "Replaced %.0f%% of the chunks: rebuilt the vector index (%.1f s)",
                100 * result.replaced_share, result.rebuild_seconds,
            )

    result.seconds = time.perf_counter() - start
    return result


def write_sync_report(result: SyncResult, results_dir: str | Path) -> tuple[Path, Path]:
    """``<timestamp>_sync.json`` (or ``_sync-dry-run``) and a short Markdown summary."""

    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    label = "sync-dry-run" if result.dry_run else "sync"
    stem = f"{datetime.now(UTC):%Y%m%d-%H%M%S}_{label}"

    data: dict[str, Any] = {
        "kind": "sync",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **asdict(result),
        "replaced_share": round(result.replaced_share, 4),
    }
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_sync(result), encoding="utf-8")
    return json_path, md_path


def render_sync(result: SyncResult) -> str:
    lines = [
        "# Live sync" + (" (dry run)" if result.dry_run else ""),
        "",
        f"Checked {result.checked} stored articles against Wikipedia in "
        f"{result.check_seconds:.1f} s: {len(result.changed)} have a newer revision, "
        f"{len(result.missing)} no longer exist, {len(result.not_stored)} in the CSV are not stored.",
    ]
    if not result.dry_run and result.chunks_before:
        lines += [
            "",
            f"Replaced {result.replaced_articles} articles: {result.deleted_chunks} chunks deleted "
            f"({100 * result.replaced_share:.1f}% of {result.chunks_before}), "
            f"{result.inserted_chunks} inserted, in {result.seconds:.1f} s.",
            (
                f"The vector index was rebuilt ({result.rebuild_seconds:.1f} s), since at least "
                f"{100 * result.rebuild_share:.0f}% of the chunks were replaced."
                if result.rebuilt
                else f"The vector index was not rebuilt (below {100 * result.rebuild_share:.0f}% "
                "of the chunks); the deleted chunks stay in the graph until the next rebuild."
            ),
        ]
    if result.failures:
        lines += ["", "## Failures", ""] + [f"- {title}: {error}" for title, error in result.failures]
    if result.changed:
        lines += ["", "## Changed articles", "", "| title | stored revision | latest revision | latest edit |",
                  "|---|---|---|---|"]
        lines += [
            f"| {c.title} | {c.stored_revision} | {c.latest_revision} | {c.latest_time} |"
            for c in result.changed
        ]
    if result.missing:
        lines += ["", "## No longer on Wikipedia", ""] + [f"- {c.title}" for c in result.missing]
    return "\n".join(lines) + "\n"
