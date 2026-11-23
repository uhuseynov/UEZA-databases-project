"""``data/build_article_list.py``: selection, safety of the output, failures and import safety.

Everything runs against a fake MediaWiki (``httpx.MockTransport``) and temporary directories.
The script is never pointed at the real Wikipedia, and the committed ``data/articles.csv`` is
never written.
"""

import csv
import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import data.build_article_list as script
from src.config import settings
from src.ingestion.pipeline import read_articles
from tests.unit.data.fake_wiki import FakeWiki

ROOT = Path(__file__).resolve().parents[3]
REAL_SNAPSHOT = ROOT / "data" / "articles.csv"
NO_PAUSE = {"sleep": lambda seconds: None}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def committed_snapshot_is_never_touched():
    before = (sha(REAL_SNAPSHOT), REAL_SNAPSHOT.stat().st_mtime_ns)
    yield
    assert (sha(REAL_SNAPSHOT), REAL_SNAPSHOT.stat().st_mtime_ns) == before


def small_world() -> FakeWiki:
    """Two roots, a skipped subcategory, duplicates, a core article that is a redirect."""
    wiki = FakeWiki()
    wiki.category(
        "Category:Machine learning",
        ["Alpha", "Beta", "List of ML topics", "Kinect", "Tiny", "Same length 1", "Same length 2"],
        ["Category:Neural networks", "Category:Machine learning researchers"],
    )
    wiki.category("Category:Neural networks", ["Gamma", "Alpha", "Delta"])
    wiki.category("Category:Machine learning researchers", ["Person X"])
    wiki.category("Category:Deep learning", ["Gamma", "Epsilon", "Zeta"])
    wiki.page("Alpha", 1, 9000, "2026-09-01T10:00:00Z")
    wiki.page("Beta", 2, 5000, "2026-09-02T10:00:00Z")
    wiki.page("Tiny", 3, 2999)
    wiki.page("Same length 1", 4, 4000)
    wiki.page("Same length 2", 5, 4000)
    wiki.page("Gamma", 6, 8000, "2026-09-03T10:00:00Z")
    wiki.page("Delta", 7, 7000)
    wiki.page("Epsilon", 8, 6000)
    wiki.page("Zeta", 9, 3000)  # exactly the minimum: kept
    wiki.page("Person X", 10, 9999)
    wiki.page("Kinect", 11, 9999)
    wiki.page("List of ML topics", 12, 9999)
    wiki.page("Artificial intelligence", 20, 50000)
    wiki.page("Supervised learning", 21, 12000)
    wiki.redirects["Overfitting"] = "Overfitting (statistics)"
    wiki.page("Overfitting (statistics)", 22, 8000)
    return wiki


# --- the selection --------------------------------------------------------------------------


def test_the_selection_definition_is_unchanged():
    """The rules that define the research dataset, pinned by a digest of the original script's."""
    payload = json.dumps(
        [
            script.ROOTS,
            script.MIN_LENGTH,
            script.MAX_PER_ROOT,
            script.ROOT_CAPS,
            script.BAD_STARTS,
            script.BAD_WORDS,
            script.REMOVE,
            script.CORE,
        ],
        ensure_ascii=False,
    )

    assert (
        hashlib.sha256(payload.encode()).hexdigest()
        == "4743438f12d664a00437cc5e9c15a1f0bef28e36bdf6de344611a391439cf243"
    )
    assert (len(script.ROOTS), len(script.REMOVE), len(script.CORE)) == (6, 104, 25)
    assert script.COLUMNS == ["title", "pageid", "length", "last_edit", "root_category", "category"]


def test_the_selection_rules_are_applied_in_order():
    wiki = small_world()
    api = script.WikiApi(wiki.client(), **NO_PAUSE)

    rows = script.select_articles(api, log=lambda message: None)

    titles = [row["title"] for row in rows]
    # Machine learning: longest first, equal lengths in the order MediaWiki answered; the
    # skipped subcategory, the list page, the removed article and the short stub are out.
    assert titles[:5] == ["Alpha", "Gamma", "Delta", "Beta", "Same length 1"]
    assert titles[5] == "Same length 2"
    # Deep learning: Gamma was taken by the first root; Zeta has exactly MIN_LENGTH
    assert titles[6:8] == ["Epsilon", "Zeta"]
    # then the core articles that exist; a redirect is followed to its canonical title
    assert titles[8:] == [
        "Artificial intelligence",
        "Supervised learning",
        "Overfitting (statistics)",
    ]

    by_title = {row["title"]: row for row in rows}
    assert by_title["Alpha"] == {
        "title": "Alpha",
        "pageid": 1,
        "length": 9000,
        "last_edit": "2026-09-01T10:00:00Z",
        "root_category": "Machine learning",
        "category": "Machine learning",
    }
    assert by_title["Gamma"]["category"] == "Neural networks"  # the subcategory it came from
    assert by_title["Gamma"]["root_category"] == "Machine learning"
    assert by_title["Epsilon"]["root_category"] == "Deep learning"
    assert by_title["Supervised learning"]["root_category"] == "Core"
    assert by_title["Supervised learning"]["category"] == "Core"


def test_a_skipped_subcategory_is_not_even_requested():
    wiki = small_world()

    script.select_articles(script.WikiApi(wiki.client(), **NO_PAUSE), log=lambda message: None)

    asked = [r.url.params.get("cmtitle") for r in wiki.requests if "cmtitle" in r.url.params]
    assert "Category:Machine learning researchers" not in asked
    assert "Category:Neural networks" in asked


def test_the_cap_per_root_and_the_smaller_cap_for_computer_vision(monkeypatch):
    monkeypatch.setattr(script, "MAX_PER_ROOT", 2)
    monkeypatch.setattr(script, "ROOT_CAPS", {"Category:Computer vision": 1})
    monkeypatch.setattr(script, "CORE", [])
    wiki = FakeWiki()
    for root in ("Category:Machine learning", "Category:Computer vision"):
        names = [f"{root[9:12]} {i}" for i in range(5)]
        wiki.category(root, names)
        for i, name in enumerate(names):
            wiki.page(name, 100 + i + len(wiki.pages), 5000 + i)

    rows = script.select_articles(script.WikiApi(wiki.client(), **NO_PAUSE), log=lambda m: None)

    assert [r["root_category"] for r in rows] == ["Machine learning"] * 2 + ["Computer vision"]
    assert [r["length"] for r in rows if r["root_category"] == "Machine learning"] == [5004, 5003]


def test_a_missing_core_article_is_reported_and_not_added():
    wiki = small_world()
    messages: list[str] = []

    rows = script.select_articles(script.WikiApi(wiki.client(), **NO_PAUSE), log=messages.append)

    assert "Autoencoder" not in [r["title"] for r in rows]
    assert "  not found: Autoencoder" in messages
    assert messages[-1] == "  added 3"


def test_article_queries_ask_for_the_latest_revision_timestamp_only():
    wiki = small_world()

    script.select_articles(script.WikiApi(wiki.client(), **NO_PAUSE), log=lambda m: None)

    info = [r.url.params for r in wiki.requests if "titles" in r.url.params]
    assert all(p["prop"] == "info|revisions" and p["rvprop"] == "timestamp" for p in info)
    assert all("rvstart" not in p for p in info)  # the latest revision, as in the original
    assert [("redirects" in p) for p in info][-1] is True  # only the core query follows redirects
    assert not any("redirects" in p for p in info[:-1])


# --- the request itself ---------------------------------------------------------------------


def test_requests_carry_the_project_user_agent_and_the_configured_timeout(monkeypatch, tmp_path):
    wiki = small_world()
    seen: dict = {}
    real_client = httpx.Client

    def fake_client(**kwargs):
        seen.update(kwargs)
        return real_client(transport=httpx.MockTransport(wiki), headers=kwargs["headers"])

    monkeypatch.setattr(
        script,
        "settings",
        SimpleNamespace(
            mediawiki_user_agent="UEZA-test-agent/1.0 (contact: test@example.org)",
            mediawiki_timeout=3.5,
        ),
    )
    monkeypatch.setattr(script.httpx, "Client", fake_client)

    code = script.main(["--output", str(tmp_path / "out.csv")], **NO_PAUSE)

    assert code == 0
    assert seen["timeout"] == 3.5
    assert seen["headers"]["User-Agent"] == "UEZA-test-agent/1.0 (contact: test@example.org)"
    assert {r.headers["user-agent"] for r in wiki.requests} == {
        "UEZA-test-agent/1.0 (contact: test@example.org)"
    }
    assert all(
        r.url.host == "en.wikipedia.org" and r.url.path == "/w/api.php" for r in wiki.requests
    )
    assert all(
        r.url.params["format"] == "json" and r.url.params["formatversion"] == "2"
        for r in wiki.requests
    )


def test_the_default_user_agent_is_the_one_of_the_application():
    assert "UEZA-Databases-Project" in settings.mediawiki_user_agent
    assert "mailto:" in settings.mediawiki_user_agent
    assert "requests" not in sys.modules.get("data.build_article_list").__dict__


# --- failures: nothing is written -----------------------------------------------------------


def failing(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


FAILURES = {
    "http 500": lambda request: httpx.Response(500, text="boom"),
    "http 429": lambda request: httpx.Response(429, text="slow down"),
    "http 404": lambda request: httpx.Response(404),
    "not json": lambda request: httpx.Response(200, text="<html>maintenance</html>"),
    "json array": lambda request: httpx.Response(200, json=[]),
    "api error": lambda request: httpx.Response(
        200, json={"error": {"code": "readonly", "info": "The wiki is in read-only mode"}}
    ),
    "unexpected structure": lambda request: httpx.Response(200, json={"query": {}}),
}


def raising(error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error(f"boom {request.url}", request=request)

    return handler


FAILURES["timeout"] = raising(httpx.ReadTimeout)
FAILURES["connect timeout"] = raising(httpx.ConnectTimeout)
FAILURES["connection refused"] = raising(httpx.ConnectError)

EXPECTED_MESSAGE = {
    "http 500": "HTTP 500",
    "http 429": "HTTP 429",
    "http 404": "HTTP 404",
    "not json": "not JSON",
    "json array": "not a JSON object",
    "api error": "readonly",
    "unexpected structure": "Unexpected answer",
    "timeout": "did not answer in time",
    "connect timeout": "did not answer in time",
    "connection refused": "request failed",
}


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_request_writes_nothing_and_says_why(failure, tmp_path, capsys):
    output = tmp_path / "out.csv"

    code = script.main(["--output", str(output)], client=failing(FAILURES[failure]), **NO_PAUSE)

    assert code == 1
    assert EXPECTED_MESSAGE[failure] in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []  # no file, no temporary file


def test_a_failure_halfway_leaves_an_existing_file_untouched_even_with_overwrite(tmp_path, capsys):
    output = tmp_path / "out.csv"
    output.write_text("previous run\n", encoding="utf-8")
    wiki = small_world()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 5:  # after several good answers
            return httpx.Response(503)
        return wiki(request)

    code = script.main(
        ["--output", str(output), "--overwrite"], client=failing(handler), **NO_PAUSE
    )

    assert code == 1 and calls == 5
    assert output.read_text(encoding="utf-8") == "previous run\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]  # no leftover temporary file


def test_a_failure_while_writing_leaves_no_partial_file(monkeypatch, tmp_path):
    output = tmp_path / "out.csv"

    def explode(self, rows):
        raise OSError("disk full")

    monkeypatch.setattr(script.csv.DictWriter, "writerows", explode)

    with pytest.raises(OSError, match="disk full"):
        script.write_csv([{"title": "A"}], output, overwrite=False)

    assert list(tmp_path.iterdir()) == []


# --- the output ------------------------------------------------------------------------------


def test_the_default_output_is_a_separate_generated_file():
    parser = script.build_parser()

    assert parser.parse_args([]).output == script.DEFAULT_OUTPUT
    assert script.DEFAULT_OUTPUT.name == "articles.generated.csv"
    assert script.DEFAULT_OUTPUT.parent == script.COMMITTED_SNAPSHOT.parent
    assert script.DEFAULT_OUTPUT != script.COMMITTED_SNAPSHOT
    assert script.COMMITTED_SNAPSHOT == REAL_SNAPSHOT


def test_the_csv_has_the_columns_order_and_encoding_of_the_dataset(tmp_path):
    output = tmp_path / "nested" / "out.csv"
    wiki = small_world()
    wiki.category("Category:Reinforcement learning", ["Café Q-learning"])
    wiki.page("Café Q-learning", 30, 4321, "2026-10-04T08:00:00Z")

    code = script.main(["--output", str(output)], client=wiki.client(), **NO_PAUSE)

    assert code == 0
    raw = output.read_bytes()
    assert raw.startswith(b"title,pageid,length,last_edit,root_category,category\n")
    assert b"\r" not in raw  # LF, like the committed file
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == script.COLUMNS
    assert [r["title"] for r in rows][-4:] == [
        "Café Q-learning",
        "Artificial intelligence",
        "Supervised learning",
        "Overfitting (statistics)",
    ]
    assert rows[-4] == {
        "title": "Café Q-learning",
        "pageid": "30",
        "length": "4321",
        "last_edit": "2026-10-04T08:00:00Z",
        "root_category": "Reinforcement learning",
        "category": "Reinforcement learning",
    }
    assert [p.name for p in output.parent.iterdir()] == ["out.csv"]  # no temporary file


def test_the_generated_file_is_a_valid_input_for_the_ingest(tmp_path):
    output = tmp_path / "out.csv"
    script.main(["--output", str(output)], client=small_world().client(), **NO_PAUSE)

    rows = read_articles(str(output))

    assert [r["title"] for r in rows][:2] == ["Alpha", "Gamma"]


def test_the_same_answers_give_the_same_bytes(tmp_path):
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"

    script.main(["--output", str(first)], client=small_world().client(), **NO_PAUSE)
    script.main(["--output", str(second)], client=small_world().client(), **NO_PAUSE)

    assert first.read_bytes() == second.read_bytes()


# --- overwrite protection ----------------------------------------------------------------------


def never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no request may be sent when the output is refused")


def test_an_existing_output_is_not_replaced_by_default(tmp_path, capsys):
    output = tmp_path / "out.csv"
    output.write_text("earlier run\n", encoding="utf-8")

    code = script.main(["--output", str(output)], client=failing(never_called), **NO_PAUSE)

    assert code == 2
    assert "--overwrite" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "earlier run\n"


def test_overwrite_replaces_an_ordinary_generated_file(tmp_path):
    output = tmp_path / "out.csv"
    output.write_text("earlier run\n", encoding="utf-8")

    code = script.main(
        ["--output", str(output), "--overwrite"], client=small_world().client(), **NO_PAUSE
    )

    assert code == 0
    assert output.read_text(encoding="utf-8").startswith("title,pageid,")
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]


def test_a_directory_is_refused(tmp_path, capsys):
    code = script.main(
        ["--output", str(tmp_path), "--overwrite"], client=failing(never_called), **NO_PAUSE
    )

    assert code == 2
    assert "directory" in capsys.readouterr().err


def test_the_committed_snapshot_is_refused_even_with_overwrite(capsys):
    before = sha(REAL_SNAPSHOT)

    for extra in ([], ["--overwrite"]):
        code = script.main(
            ["--output", str(REAL_SNAPSHOT), *extra], client=failing(never_called), **NO_PAUSE
        )
        assert code == 2
        assert "committed research snapshot" in capsys.readouterr().err

    assert sha(REAL_SNAPSHOT) == before


def test_the_snapshot_is_recognised_under_other_spellings_of_its_path(monkeypatch, tmp_path):
    """Same file, other path: relative, with .., symlinked, hard-linked; on a stand-in snapshot."""
    snapshot = tmp_path / "data" / "articles.csv"
    snapshot.parent.mkdir()
    snapshot.write_text("the research snapshot\n", encoding="utf-8")
    monkeypatch.setattr(script, "COMMITTED_SNAPSHOT", snapshot)
    symlink = tmp_path / "link.csv"
    symlink.symlink_to(snapshot)
    hardlink = tmp_path / "hard.csv"
    os.link(snapshot, hardlink)
    monkeypatch.chdir(snapshot.parent)

    spellings = [
        snapshot,
        snapshot.parent / ".." / "data" / "articles.csv",
        Path("articles.csv"),
        Path("./articles.csv"),
        symlink,
        hardlink,
    ]
    for path in spellings:
        with pytest.raises(script.OutputRefused, match="committed research snapshot"):
            script.check_output(path, overwrite=True)
        with pytest.raises(script.OutputRefused, match="committed research snapshot"):
            script.write_csv([], path, overwrite=True)

    assert snapshot.read_text(encoding="utf-8") == "the research snapshot\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data", "hard.csv", "link.csv"]


def test_a_file_that_appears_during_the_run_is_not_replaced(monkeypatch, tmp_path):
    output = tmp_path / "out.csv"

    def link_fails(source, target):
        raise FileExistsError(target)

    monkeypatch.setattr(script.os, "link", link_fails)

    with pytest.raises(script.OutputRefused, match="appeared meanwhile"):
        script.write_csv([], output, overwrite=False)

    assert list(tmp_path.iterdir()) == []


# --- import and command line safety -----------------------------------------------------------


def listing(directory: Path) -> dict[str, tuple[str, int]]:
    return {p.name: (sha(p), p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}


def test_importing_the_module_sends_no_request_and_writes_nothing(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the import must not use the network")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.Client, "request", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    before = listing(script.DATA_DIR)

    importlib.reload(script)

    assert listing(script.DATA_DIR) == before
    assert not script.DEFAULT_OUTPUT.exists()


def run_module(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "data.build_article_list", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_command_line_help_needs_no_network_and_writes_nothing():
    before = listing(script.DATA_DIR)

    result = run_module("--help")

    assert result.returncode == 0
    assert "--overwrite" in result.stdout and "--output" in result.stdout
    assert "articles.generated.csv" in result.stdout
    assert listing(script.DATA_DIR) == before


def test_the_command_line_refuses_the_snapshot_before_any_request():
    before = listing(script.DATA_DIR)

    result = run_module("--output", "data/articles.csv", "--overwrite")

    assert result.returncode == 2
    assert "committed research snapshot" in result.stderr
    assert listing(script.DATA_DIR) == before
