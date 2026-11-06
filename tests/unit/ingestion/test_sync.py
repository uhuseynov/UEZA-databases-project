"""Unit tests for the live sync: which articles changed, what is replaced, when to rebuild."""

from datetime import UTC, datetime

import pytest

from src.ingestion.sync import find_changes, render_sync, sync_articles, write_sync_report

pytestmark = pytest.mark.anyio

CSV = """title,pageid,length,last_edit,root_category,category
Unchanged,1,1000,2026-09-01T10:00:00Z,Core,Core
Edited,2,1000,2026-09-01T10:00:00Z,Core,Core
Deleted,3,1000,2026-09-01T10:00:00Z,Core,Core
Broken,4,1000,2026-09-01T10:00:00Z,Core,Core
Never loaded,5,1000,2026-09-01T10:00:00Z,Core,Core
"""

EDITED_AT = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)


class FakeClient:
    def __init__(self) -> None:
        self.asked: list[int] = []

    def latest_revisions(self, page_ids):
        self.asked = list(page_ids)
        latest = {1: (100, EDITED_AT), 2: (201, EDITED_AT), 4: (401, EDITED_AT)}
        return {page_id: latest[page_id] for page_id in self.asked if page_id in latest}


class FakeRepository:
    def __init__(self) -> None:
        self.analyzed = 0
        self.rebuilt = 0

    async def revision_ids(self):
        return {1: 100, 2: 200, 3: 300, 4: 400}

    async def chunk_counts(self):
        return {1: 10, 2: 6, 3: 4, 4: 5}

    async def analyze(self):
        self.analyzed += 1

    async def rebuild_vector_index(self):
        self.rebuilt += 1
        return 1.5


class FakePipeline:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, bool]] = []

    async def ingest_one(self, row, config="A", snapshot=True):
        self.ingested.append((row["title"], snapshot))
        if row["title"] == "Broken":
            raise ValueError("Unclosed MediaWiki table")
        return 8


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "articles.csv"
    path.write_text(CSV, encoding="utf-8")
    return str(path)


async def test_find_changes_compares_stored_and_latest_revisions(csv_path):
    from src.ingestion.pipeline import read_articles

    client = FakeClient()
    result = await find_changes(client, FakeRepository(), read_articles(csv_path))

    assert client.asked == [1, 2, 3, 4]
    assert result.checked == 4
    assert [c.title for c in result.changed] == ["Edited", "Broken"]
    assert result.changed[0].stored_revision == 200
    assert result.changed[0].latest_revision == 201
    assert result.changed[0].latest_time == EDITED_AT.isoformat()
    assert [c.title for c in result.missing] == ["Deleted"]
    assert result.not_stored == ["Never loaded"]


async def test_dry_run_replaces_nothing_and_loads_no_model(csv_path):
    repository = FakeRepository()

    def no_pipeline():
        raise AssertionError("a dry run must not load the embedding model")

    result = await sync_articles(client=FakeClient(), repository=repository,
                                 pipeline_factory=no_pipeline, csv_path=csv_path, dry_run=True)

    assert result.dry_run
    assert len(result.changed) == 2
    assert result.replaced_articles == 0
    assert repository.analyzed == 0


async def test_sync_replaces_changed_articles_at_their_latest_revision(csv_path):
    repository, pipeline = FakeRepository(), FakePipeline()

    result = await sync_articles(client=FakeClient(), repository=repository,
                                 pipeline_factory=lambda: pipeline, csv_path=csv_path,
                                 rebuild_share=0.5)

    assert pipeline.ingested == [("Edited", False), ("Broken", False)]
    assert result.replaced_articles == 1
    assert result.failures == [("Broken", "Unclosed MediaWiki table")]
    assert result.chunks_before == 25
    assert result.deleted_chunks == 6
    assert result.inserted_chunks == 8
    assert repository.analyzed == 1
    # 6 of 25 chunks replaced is below the 50% threshold
    assert not result.rebuilt
    assert repository.rebuilt == 0


async def test_sync_rebuilds_the_index_above_the_threshold(csv_path):
    repository = FakeRepository()

    result = await sync_articles(client=FakeClient(), repository=repository,
                                 pipeline_factory=FakePipeline, csv_path=csv_path,
                                 rebuild_share=0.2)

    assert result.replaced_share == pytest.approx(6 / 25)
    assert result.rebuilt
    assert result.rebuild_seconds == 1.5
    assert repository.rebuilt == 1


async def test_limit_caps_the_replaced_articles(csv_path):
    pipeline = FakePipeline()

    await sync_articles(client=FakeClient(), repository=FakeRepository(),
                        pipeline_factory=lambda: pipeline, csv_path=csv_path, limit=1)

    assert pipeline.ingested == [("Edited", False)]


@pytest.mark.parametrize("options", [{"limit": 0}, {"rebuild_share": 1.5}])
async def test_rejects_invalid_options(csv_path, options):
    with pytest.raises(ValueError):
        await sync_articles(client=FakeClient(), repository=FakeRepository(),
                            pipeline_factory=FakePipeline, csv_path=csv_path, **options)


async def test_report_is_written_as_json_and_markdown(csv_path, tmp_path):
    result = await sync_articles(client=FakeClient(), repository=FakeRepository(),
                                 pipeline_factory=FakePipeline, csv_path=csv_path)

    json_path, md_path = write_sync_report(result, tmp_path / "results")

    assert json_path.name.endswith("_sync.json")
    markdown = md_path.read_text(encoding="utf-8")
    assert "| Edited | 200 | 201 |" in markdown
    assert "- Broken: Unclosed MediaWiki table" in markdown
    assert "Deleted" in render_sync(result)
