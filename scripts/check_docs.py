#!/usr/bin/env python3
"""Checks the documentation against the repository. Standard library only, no network.

    python scripts/check_docs.py [--root PATH]      (or: make docs-check)

What it checks, each reported as ``file:line: message``:

1. Relative Markdown links and images point to files that exist, and ``#anchors`` to headings
   that exist (GitHub's rules for turning a heading into an anchor).
2. Repository paths written in backticks (``src/...``, ``tests/...``, ``scripts/...``, ...) exist.
3. ``make <target>`` mentions name a target of the Makefile.
4. Configuration names: the table of ``docs/architecture/Configuration.md`` lists exactly the
   settings of ``src/config.py``; ``.env.example`` sets only names the project knows; names with
   a project prefix (``LLM_``, ``MARIADB_``, ...) that the docs mention are settings, Makefile
   variables or the few Compose-only variables.

It does not judge prose, check external links, or run any command. Exit status 1 if anything is
reported.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from urllib.parse import unquote

TOP_LEVEL_DIRS = (
    "src",
    "tests",
    "scripts",
    "data",
    "experiments",
    "docs",
    "eval",
    ".githooks",
    ".github",
)
TOP_LEVEL_FILES = (
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "pyproject.toml",
    "schema.sql",
    ".env.example",
    "uv.lock",
    ".gitignore",
    ".dockerignore",
    "README.md",
    "LICENSE",
)
# Documented on purpose although it does not exist in a checkout: the output of
# data/build_article_list.py, which Git ignores.
MAY_BE_ABSENT = {"data/articles.generated.csv"}
# Read by Docker Compose, not by src/config.py.
COMPOSE_ONLY = {"MARIADB_ROOT_PASSWORD", "APP_BIND_ADDRESS"}
CONFIG_PREFIXES = (
    "APP_",
    "LOG_",
    "MARIADB_",
    "CACHE_",
    "MEDIAWIKI_",
    "ARTICLES_",
    "CHUNK_",
    "INGESTION_",
    "EMBEDDING_",
    "VECTOR_SEARCH_",
    "LLM_",
    "RAG_",
    "GROUND_",
    "EVAL_",
)

LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MAKE_MENTION = re.compile(r"^(?:\$\s+)?make\s+(.*)$")
PATH_TOKEN = re.compile(r"^[A-Za-z0-9_.\-/]+$")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def markdown_files(root: Path) -> list[Path]:
    found = [root / "README.md", root / "eval" / "results" / "README.md"]
    found += sorted((root / "docs").rglob("*.md"))
    found += sorted((root / "experiments").rglob("README.md"))
    return [path for path in found if path.is_file()]


def lines_with_fences(path: Path):
    """``(line number, text, inside a code fence)`` for every line."""
    inside = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        yield number, line, inside


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: formatting removed, lowercase, punctuation dropped."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links and images: their text
    text = re.sub(r"[`*~]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)  # keeps letters, digits, "_" and "-"
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for _, line, inside in lines_with_fences(path):
        match = None if inside else HEADING.match(line)
        if match:
            base = slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            found.add(base if count == 0 else f"{base}-{count}")
    return found


def check_links(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    cache: dict[Path, set[str]] = {}
    for path in files:
        for number, line, inside in lines_with_fences(path):
            if inside:
                continue
            for match in LINK.finditer(INLINE_CODE.sub("", line)):
                target = match.group(1)
                if SCHEME.match(target):
                    continue
                name, _, fragment = target.partition("#")
                destination = path if not name else (path.parent / unquote(name))
                where = f"{path.relative_to(root)}:{number}"
                if not destination.exists():
                    errors.append(f"{where}: link target does not exist: {target}")
                elif fragment and destination.suffix == ".md":
                    known = cache.setdefault(destination, anchors(destination))
                    if unquote(fragment).lower() not in known:
                        errors.append(
                            f"{where}: no heading for anchor #{fragment} in {destination.name}"
                        )
    return errors


def check_paths(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        for number, line, _ in lines_with_fences(path):
            for match in INLINE_CODE.finditer(line):
                token = match.group(1).rstrip(",.;:")
                if not PATH_TOKEN.match(token) or token in MAY_BE_ABSENT:
                    continue
                known = token.split("/")[0] in TOP_LEVEL_DIRS and "/" in token
                if (known or token in TOP_LEVEL_FILES) and not (root / token).exists():
                    errors.append(
                        f"{path.relative_to(root)}:{number}: path does not exist: {token}"
                    )
    return errors


def makefile_targets(root: Path) -> set[str]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*):(?!=)", text, re.M)) - {".PHONY"}


def makefile_variables(root: Path) -> set[str]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)\s*[:?+]?=", text, re.M))


def make_target_of(command: str) -> str | None:
    """The target in ``make [options] [VAR=value ...] target`` (``None``: bare ``make``)."""
    for word in command.split():
        if word.startswith("-") or "=" in word:
            continue
        return re.sub(r"[^A-Za-z0-9_.\-].*$", "", word) or None
    return None


def check_make_targets(root: Path, files: list[Path]) -> list[str]:
    targets = makefile_targets(root)
    errors: list[str] = []
    for path in files:
        for number, line, inside in lines_with_fences(path):
            mentions: list[str] = []
            if inside:
                match = MAKE_MENTION.match(line.strip())
                if match:
                    mentions.append(match.group(1).split("#")[0])
            else:
                for code in INLINE_CODE.finditer(line):
                    match = MAKE_MENTION.match(code.group(1).strip())
                    if match:
                        mentions.append(match.group(1))
            for command in mentions:
                target = make_target_of(command)
                if target and target not in targets:
                    errors.append(
                        f"{path.relative_to(root)}:{number}: Makefile has no target {target!r}"
                    )
    return errors


def settings_fields(root: Path) -> set[str]:
    """Upper-case names of the fields of ``class Settings`` in src/config.py (read, not imported)."""
    tree = ast.parse((root / "src" / "config.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                item.target.id.upper()
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and not item.target.id.startswith("_")
                and item.target.id != "model_config"
            }
    raise SystemExit("src/config.py has no class Settings")


def check_configuration(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    fields = settings_fields(root)
    known = fields | COMPOSE_ONLY | makefile_variables(root)

    page = root / "docs" / "architecture" / "Configuration.md"
    if page.is_file():
        rows: set[str] = set()
        for _, line, inside in lines_with_fences(page):
            if not inside and line.startswith("|"):
                first_cell = line.split("|")[1] if line.count("|") > 1 else ""
                rows |= set(re.findall(r"`([A-Z][A-Z0-9_]+)`", first_cell))
        for name in sorted(fields - rows):
            errors.append(f"docs/architecture/Configuration.md: setting not in the table: {name}")
        for name in sorted(rows - fields):
            errors.append(f"docs/architecture/Configuration.md: table row is not a setting: {name}")

    example = root / ".env.example"
    if example.is_file():
        for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), start=1):
            match = re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=", line)
            if match and match.group(1) not in known:
                errors.append(f".env.example:{number}: unknown setting {match.group(1)}")

    for path in files:
        for number, line, _ in lines_with_fences(path):
            for code in INLINE_CODE.finditer(line):
                for name in re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", code.group(1)):
                    if name.startswith(CONFIG_PREFIXES) and name not in known:
                        errors.append(
                            f"{path.relative_to(root)}:{number}: {name} is not a setting, "
                            "a Makefile variable or a Compose variable"
                        )
    return errors


def check(root: Path) -> list[str]:
    files = markdown_files(root)
    return [
        *check_links(root, files),
        *check_paths(root, files),
        *check_make_targets(root, files),
        *check_configuration(root, files),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the documentation against the repository.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the one this script is in)",
    )
    root = parser.parse_args(argv).root.resolve()

    errors = check(root)
    for error in errors:
        print(error)
    count = len(markdown_files(root))
    print(
        f"{count} Markdown files checked: "
        + (f"{len(errors)} problems" if errors else "no problems")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
