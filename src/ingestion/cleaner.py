"""Clean MediaWiki wikitext for semantic search."""

from __future__ import annotations

import html
import re

import mwparserfromhell

EXCLUDED_SECTIONS = {
    "references",
    "external links",
    "see also",
    "further reading",
    "notes",
    "bibliography",
    "sources",
    "footnotes",
    "citations",
}

EXCLUDED_TAGS = {
    "ref",
    "references",
    "gallery",
    "math",
    "timeline",
    "score",
    "syntaxhighlight",
    "source",
    "imagemap",
    "chem",
    # mwparserfromhell parses {| ... |} wiki tables as "table" tags, nested ones
    # included. A hand-written scanner mistook "{|" inside <math> for a table.
    "table",
}

MEDIA_NAMESPACES = (
    "file:",
    "image:",
    "media:",
)

HEADING_PATTERN = re.compile(r"^\s*(={2,6})\s*(.*?)\s*\1\s*$")


def _remove_excluded_sections(text: str) -> str:
    """Remove unwanted sections and their subsections."""

    output = []
    excluded_level = None

    for line in text.splitlines():
        match = HEADING_PATTERN.match(line)

        if match:
            level = len(match.group(1))
            heading = mwparserfromhell.parse(match.group(2)).strip_code().strip().casefold()

            if excluded_level is not None and level <= excluded_level:
                excluded_level = None

            if heading in EXCLUDED_SECTIONS:
                excluded_level = level
                continue

        if excluded_level is None:
            output.append(line)

    return "\n".join(output)


def _remove_nodes(code) -> None:
    """Remove markup nodes that should not be embedded."""

    for template in list(code.filter_templates(recursive=True)):
        try:
            code.remove(template, recursive=True)
        except ValueError:
            pass

    for link in list(code.filter_wikilinks(recursive=True)):
        target = str(link.title).strip().casefold()

        if target.startswith(MEDIA_NAMESPACES):
            try:
                code.remove(link, recursive=True)
            except ValueError:
                pass

    for tag in list(code.filter_tags(recursive=True)):
        name = str(tag.tag).strip().casefold()

        if name in EXCLUDED_TAGS:
            try:
                code.remove(tag, recursive=True)
            except ValueError:
                pass

    for comment in list(code.filter_comments(recursive=True)):
        try:
            code.remove(comment, recursive=True)
        except ValueError:
            pass


def clean_wikitext(raw_text: str) -> str:
    """Return clean article prose with section headings preserved.

    Removes non-prose MediaWiki markup while retaining useful
    paragraphs, ordinary internal-link labels and headings.
    """

    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be a string")

    if not raw_text.strip():
        return ""

    text = _remove_excluded_sections(raw_text)

    code = mwparserfromhell.parse(text)
    _remove_nodes(code)

    # Turn MediaWiki headings into plain-text headings.
    text = str(code)

    text = re.sub(
        r"(?m)^\s*={2,6}\s*(.*?)\s*={2,6}\s*$",
        lambda match: "\n\n" + match.group(1).strip() + "\n\n",
        text,
    )

    code = mwparserfromhell.parse(text)
    _remove_nodes(code)

    text = code.strip_code(
        normalize=True,
        collapse=False,
    )

    text = html.unescape(text)

    # Remove any remaining HTML tags.
    text = re.sub(
        r"</?[A-Za-z][^>]*>",
        " ",
        text,
    )

    # Normalize Unicode and wiki formatting whitespace.
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^[ \t]+|[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
