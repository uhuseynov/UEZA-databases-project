"""Builds a candidate article list for the project from English Wikipedia.

This is how ``data/articles.csv`` was made (selection rules: docs/data_decisions.md). The
committed ``data/articles.csv`` is the research snapshot: the ingest, the evaluation and the
ground-truth questions depend on its exact articles and edit dates. A new run reads the
*current* category members, lengths and edit times, so it produces a different list. That is
why this script never writes ``data/articles.csv``:

    uv run python -m data.build_article_list                    # -> data/articles.generated.csv
    uv run python -m data.build_article_list --output my.csv
    uv run python -m data.build_article_list --overwrite        # replace an earlier generated file

An existing output file is never replaced unless ``--overwrite`` is given, and
``data/articles.csv`` is never replaced at all. The file is written only after every request
has succeeded, through a temporary file, so a failed run leaves nothing half-written.

Importing this module does nothing: no request is sent and no file is written until ``main()``
runs.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from src.config import settings

API_URL = "https://en.wikipedia.org/w/api.php"
DATA_DIR = Path(__file__).resolve().parent
COMMITTED_SNAPSHOT = DATA_DIR / "articles.csv"
DEFAULT_OUTPUT = DATA_DIR / "articles.generated.csv"
COLUMNS = ["title", "pageid", "length", "last_edit", "root_category", "category"]
PAUSE_SECONDS = 0.2  # between requests, to be polite to the API

ROOTS = [
    "Category:Machine learning",
    "Category:Deep learning",
    "Category:Natural language processing",
    "Category:Computer vision",
    "Category:Reinforcement learning",
    "Category:Philosophy of artificial intelligence",
]
MIN_LENGTH = 3000
MAX_PER_ROOT = 50
ROOT_CAPS = {"Category:Computer vision": 25}  # its subcategories drift into 3D imaging and optics
BAD_STARTS = ["List of", "Outline of", "Index of", "Timeline of", "Glossary of"]
BAD_WORDS = ["companies", "researchers", "people", "fiction", "films", "books"]

# Articles checked by hand and judged NOT to be about AI (products, films, geometry, optics,
# finite-state machines, fiction characters, laws). Verbatim from the selection that built the
# committed data/articles.csv.
REMOVE = [
    "Kinect",
    "Folding@home",
    "Google Nest",
    "Aphelion (software)",
    "Kruskal count",
    "Julia (programming language)",
    "Stockfish (chess)",
    "The Flash (film)",
    "The Capture (TV series)",
    "The Heart Part 5",
    "Fall (2022 film)",
    "1999 (Charli XCX and Troye Sivan song)",
    "Kuaishou",
    "Deepfake pornography",
    "Generative AI pornography",
    "Grok sexual deepfake scandal",
    "Laws of Form",
    "Suffix automaton",
    "UML state machine",
    "Büchi automaton",
    "Finite-state machine",
    "Asymmetric numeral systems",
    "CarPlay",
    "Verbal overshadowing",
    "Speech repetition",
    "IBM optical mark and character readers",
    "Automatic number-plate recognition",
    "ReCAPTCHA",
    "Ancient text corpora",
    "Hapax legomenon",
    "Haptik",
    "3D film",
    "IMAX",
    "Virtual reality applications",
    "Closed-circuit television",
    "Traffic enforcement camera",
    "Red light camera",
    "3D scanning",
    "Manifold",
    "Holography",
    "Color vision",
    "Color",
    "Convex hull",
    "Anaglyph 3D",
    "Stereoscopy",
    "Lenticular printing",
    "Charge-coupled device",
    "Erika Blumenfeld",
    "Autostereogram",
    "Binocular vision",
    "Differential geometry",
    "MATLAB",
    "Lie algebroid",
    "Depth perception",
    "3D modeling",
    "Convolution",
    "Tensor operator",
    "Avizo (software)",
    "Augmented reality",
    "Noise reduction",
    "CAPTCHA",
    "Eye tracking",
    "Mobileye",
    "Robot Operating System",
    "Medical imaging",
    "Vilém Flusser",
    "Fanged Noumena",
    "Skynet (Terminator)",
    "Émile P. Torres",
    "Sermon on the 'Mount (South Park)",
    "Lightricks",
    "TAKE IT DOWN Act",
    "No Fakes Act",
    "Tagged Deterministic Finite Automaton",
    "Nondeterministic finite automaton",
    "Deterministic finite automaton",
    "Trie",
    "Regular language",
    "Haskins Laboratories",
    "Physics of optical holography",
    "Time-of-flight camera",
    "Opponent process",
    "Amira (software)",
    "Nonogram",
    "Discrete Laplace operator",
    "3D projection",
    "Pixel-art scaling algorithms",
    "Artec 3D",
    "4DX",
    "Stereopsis",
    "3D display",
    "Active shutter 3D system",
    "Salience (neuroscience)",
    "Image editing",
    "CrysTBox",
    "Image noise",
    "The Outer Limits (1995 TV series)",
    "Omega Point",
    "Taylor Swift deepfake pornography controversy",
    "Open Syllabus Project",
    "Glottochronology",
    "Voice user interface",
    "Luciano Floridi",
    "Moral circle expansion",
]

# Important core articles that the six root categories do not contain.
CORE = [
    "Artificial intelligence",
    "Supervised learning",
    "Unsupervised learning",
    "Recurrent neural network",
    "Word embedding",
    "Attention Is All You Need",
    "Retrieval-augmented generation",
    "Autoencoder",
    "Decision tree learning",
    "Random forest",
    "Gradient boosting",
    "Expert system",
    "Knowledge graph",
    "Symbolic artificial intelligence",
    "History of artificial intelligence",
    "Overfitting",
    "Backpropagation",
    "Gradient descent",
    "Transfer learning",
    "Self-supervised learning",
    "Vector database",
    "Semantic search",
    "BERT (language model)",
    "GPT-3",
    "ChatGPT",
]


class ArticleListError(RuntimeError):
    """A request failed or MediaWiki answered with something unusable. Nothing was written."""


class WikiApi:
    """The three kinds of query the selection needs, over one ``httpx.Client``."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        pause: float = PAUSE_SECONDS,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._pause = pause

    def ask(self, params: dict[str, Any]) -> dict[str, Any]:
        query = {**params, "format": "json", "formatversion": 2}

        try:
            response = self._client.get(API_URL, params=query)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise ArticleListError(f"MediaWiki did not answer in time: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ArticleListError(f"MediaWiki answered with HTTP {status}") from exc
        except httpx.HTTPError as exc:
            raise ArticleListError(f"MediaWiki request failed: {exc}") from exc
        except ValueError as exc:
            raise ArticleListError("MediaWiki answered with something that is not JSON") from exc

        if not isinstance(data, dict):
            raise ArticleListError("MediaWiki answered with something that is not a JSON object")
        if isinstance(data.get("error"), dict):
            error = data["error"]
            raise ArticleListError(f"MediaWiki error {error.get('code')}: {error.get('info')}")

        self._sleep(self._pause)
        return data

    def get_category(self, category: str) -> tuple[list[str], list[str]]:
        """Article titles and subcategory titles of a category (the first 500 members)."""
        data = self.ask(
            {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": category,
                "cmlimit": 500,
            }
        )

        articles: list[str] = []
        subcats: list[str] = []

        try:
            for item in data["query"]["categorymembers"]:
                if item["ns"] == 0:
                    articles.append(item["title"])
                if item["ns"] == 14:
                    subcats.append(item["title"])
        except (KeyError, TypeError) as exc:
            raise ArticleListError(f"Unexpected answer for {category}") from exc

        return articles, subcats

    def get_info(
        self,
        titles: list[str],
        log: Callable[[str], None],
        follow_redirects: bool = False,
    ) -> dict[str, tuple[int, int, str]]:
        """``title -> (page id, length, timestamp of the latest revision)``, 50 titles a request."""
        result: dict[str, tuple[int, int, str]] = {}

        for i in range(0, len(titles), 50):
            part = titles[i : i + 50]
            params: dict[str, Any] = {
                "action": "query",
                "titles": "|".join(part),
                "prop": "info|revisions",
                "rvprop": "timestamp",
            }
            if follow_redirects:
                params["redirects"] = 1

            data = self.ask(params)

            try:
                for page in data["query"]["pages"]:
                    if "revisions" not in page:
                        log(f"  not found: {page['title']}")
                        continue
                    result[page["title"]] = (
                        page["pageid"],
                        page["length"],
                        page["revisions"][0]["timestamp"],
                    )
            except (KeyError, IndexError, TypeError) as exc:
                raise ArticleListError("Unexpected answer for an article query") from exc

        return result


def select_articles(api: WikiApi, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """The article list: up to a cap per root category, then the hand-picked core articles."""
    rows: list[dict[str, Any]] = []
    used: set[str] = set()

    # the six root categories
    for root in ROOTS:
        log(f"Working on {root}")
        label = root.replace("Category:", "")
        found: dict[str, str] = {}

        articles, subcats = api.get_category(root)
        for a in articles:
            found[a] = label

        for sub in subcats:
            if any(word in sub.lower() for word in BAD_WORDS):
                continue
            sub_articles, _other = api.get_category(sub)
            for a in sub_articles:
                if a not in found:
                    found[a] = sub.replace("Category:", "")

        titles = []
        for t in found:
            if t.startswith(tuple(BAD_STARTS)):
                continue
            if t in REMOVE:
                continue
            if t in used:
                continue
            titles.append(t)

        info = api.get_info(titles, log)

        root_rows = []
        for t in info:
            pageid, length, last_edit = info[t]
            if t not in found:
                continue
            if length >= MIN_LENGTH:
                root_rows.append(
                    {
                        "title": t,
                        "pageid": pageid,
                        "length": length,
                        "last_edit": last_edit,
                        "root_category": label,
                        "category": found[t],
                    }
                )

        root_rows.sort(key=lambda r: r["length"], reverse=True)

        root_rows = root_rows[: ROOT_CAPS.get(root, MAX_PER_ROOT)]
        for r in root_rows:
            used.add(r["title"])
            rows.append(r)
        log(f"  kept {len(root_rows)}")

    # core articles added by hand
    log("Adding core articles")
    info = api.get_info(CORE, log, follow_redirects=True)
    added = 0
    for t in info:
        if t in used:
            continue
        pageid, length, last_edit = info[t]
        rows.append(
            {
                "title": t,
                "pageid": pageid,
                "length": length,
                "last_edit": last_edit,
                "root_category": "Core",
                "category": "Core",
            }
        )
        used.add(t)
        added += 1
    log(f"  added {added}")

    return rows


class OutputRefused(RuntimeError):
    """The output path is not allowed. Nothing was requested or written."""


def check_output(output: Path, *, overwrite: bool) -> None:
    """Refuse the committed snapshot always, and any existing file unless ``overwrite``."""
    exists = output.exists()

    protected_by_path = output.resolve() == COMMITTED_SNAPSHOT.resolve()
    protected_by_identity = (
        exists and COMMITTED_SNAPSHOT.exists() and os.path.samefile(output, COMMITTED_SNAPSHOT)
    )
    if protected_by_path or protected_by_identity:
        raise OutputRefused(
            f"{output} is the committed research snapshot (data/articles.csv); this script "
            "never writes it, not even with --overwrite. Write another file and compare."
        )

    if output.is_dir():
        raise OutputRefused(f"{output} is a directory")

    if exists and not overwrite:
        raise OutputRefused(f"{output} already exists; pass --overwrite to replace it")


def write_csv(rows: Sequence[dict[str, Any]], output: Path, *, overwrite: bool) -> None:
    """Write the CSV through a temporary file in the same directory, then move it into place.

    A failure leaves no partial file at ``output``. Without ``overwrite`` the final step fails
    instead of replacing a file that appeared in the meantime.
    """
    check_output(output, overwrite=overwrite)
    output.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w",
        newline="",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)

    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        check_output(output, overwrite=overwrite)  # again, right before the move

        if overwrite:
            os.replace(temporary, output)
        else:
            try:
                os.link(temporary, output)  # fails if the file exists: never replaces
            except FileExistsError as exc:
                raise OutputRefused(f"{output} appeared meanwhile; not replaced") from exc
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m data.build_article_list",
        description="Build a candidate article list from English Wikipedia. The committed "
        "data/articles.csv is never written.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"file to write (default: {DEFAULT_OUTPUT.relative_to(DATA_DIR.parent)})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the output file if it exists (never data/articles.csv)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = build_parser().parse_args(argv)
    output: Path = args.output

    try:
        check_output(output, overwrite=args.overwrite)  # before any request
    except OutputRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    own_client = client is None
    http = client or httpx.Client(
        headers={"User-Agent": settings.mediawiki_user_agent, "Accept": "application/json"},
        timeout=settings.mediawiki_timeout,
    )

    try:
        rows = select_articles(WikiApi(http, sleep=sleep))
        write_csv(rows, output, overwrite=args.overwrite)
    except ArticleListError as exc:
        print(f"Failed, nothing was written: {exc}", file=sys.stderr)
        return 1
    except OutputRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    finally:
        if own_client:
            http.close()

    print(f"Done, saved {len(rows)} articles to {output}")
    print("The committed data/articles.csv was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
