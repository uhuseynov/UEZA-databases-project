"""Unit tests for Wikipedia wikitext cleaning."""

from typing import Any

import pytest

from src.ingestion.cleaner import clean_wikitext


def test_empty_input() -> None:
    assert clean_wikitext("") == ""
    assert clean_wikitext("   \n  ") == ""


def test_invalid_input() -> None:
    invalid: Any = None

    with pytest.raises(TypeError):
        clean_wikitext(invalid)


def test_internal_links_preserve_labels() -> None:
    source = "Artificial intelligence uses [[machine learning|ML]] algorithms."

    cleaned = clean_wikitext(source)

    assert "ML" in cleaned
    assert "Artificial intelligence" in cleaned
    assert "[[" not in cleaned


def test_templates_and_infoboxes_removed() -> None:
    source = """
{{Infobox technology
| name = Machine learning
| image = Example.png
| caption = Example image
}}

Machine learning is a field of artificial intelligence.
"""

    cleaned = clean_wikitext(source)

    assert "Machine learning is a field" in cleaned
    assert "Infobox" not in cleaned
    assert "Example.png" not in cleaned
    assert "Example image" not in cleaned


@pytest.mark.parametrize(
    "markup",
    [
        "[[File:Example.png|thumb|upright=1.2|A sample image]]",
        "[[Image:Example.jpg|thumb|Example caption]]",
        "[[Media:Example.ogg|Audio recording]]",
    ],
)
def test_media_links_removed(markup: str) -> None:
    source = f"Before.\n{markup}\nAfter."

    cleaned = clean_wikitext(source)

    assert "Before." in cleaned
    assert "After." in cleaned
    assert "thumb" not in cleaned
    assert "upright" not in cleaned
    assert "Example" not in cleaned


def test_wiki_tables_removed() -> None:
    source = """
Introduction.

{| class="wikitable"
|-
! Model !! Accuracy
|-
| Model A || 95%
|}

This paragraph must remain.
"""

    cleaned = clean_wikitext(source)

    assert "Introduction." in cleaned
    assert "This paragraph must remain." in cleaned
    assert "Model A" not in cleaned
    assert "wikitable" not in cleaned
    assert "{|" not in cleaned


def test_nested_tables_removed() -> None:
    source = """
Start.

{| class="wikitable"
| Outer
{| class="wikitable"
| Inner
|}
|}

End.
"""

    cleaned = clean_wikitext(source)

    assert "Start." in cleaned
    assert "End." in cleaned
    assert "Outer" not in cleaned
    assert "Inner" not in cleaned


def test_references_removed() -> None:
    source = """
A useful scientific statement.<ref>Some citation</ref>

Another useful statement.

== References ==
* Reference one
* Reference two
"""

    cleaned = clean_wikitext(source)

    assert "A useful scientific statement." in cleaned
    assert "Another useful statement." in cleaned
    assert "Some citation" not in cleaned
    assert "Reference one" not in cleaned


def test_excluded_sections_removed() -> None:
    source = """
Introduction paragraph.

== History ==
Historical information.

== References ==
Citation list.

== External links ==
Example website.

== See also ==
Unrelated entries.
"""

    cleaned = clean_wikitext(source)

    assert "Introduction paragraph." in cleaned
    assert "Historical information." in cleaned
    assert "Citation list." not in cleaned
    assert "Example website." not in cleaned
    assert "Unrelated entries." not in cleaned


def test_section_after_excluded_section() -> None:
    source = """
== References ==
Citation list.

== Applications ==
Applications of artificial intelligence.
"""

    cleaned = clean_wikitext(source)

    assert "Citation list." not in cleaned
    assert "Applications of artificial intelligence." in cleaned


def test_headings_preserved() -> None:
    source = """
== History ==
Artificial intelligence has a long history.

=== Early research ===
Early researchers studied symbolic systems.
"""

    cleaned = clean_wikitext(source)

    assert "History" in cleaned
    assert "Early research" in cleaned
    assert "Artificial intelligence has a long history." in cleaned
    assert "Early researchers studied symbolic systems." in cleaned
    assert "==" not in cleaned


def test_html_and_comments_removed() -> None:
    source = """
Before.
<!-- Internal editor note -->
<div>Useful text.</div>
After.
"""

    cleaned = clean_wikitext(source)

    assert "Before." in cleaned
    assert "Useful text." in cleaned
    assert "After." in cleaned
    assert "Internal editor note" not in cleaned
    assert "<div>" not in cleaned


def test_whitespace_normalization() -> None:
    source = "First   sentence.\n\n\n\nSecond sentence."

    cleaned = clean_wikitext(source)

    assert "First sentence." in cleaned
    assert "Second sentence." in cleaned
    assert "\n\n\n" not in cleaned


def test_prose_preserved() -> None:
    source = """
'''Artificial intelligence''' (AI) is a field of
[[computer science]] focused on intelligent systems.

== Machine learning ==
Machine learning enables systems to learn from data.
"""

    cleaned = clean_wikitext(source)

    assert "Artificial intelligence" in cleaned
    assert "computer science" in cleaned
    assert "Machine learning enables systems" in cleaned
    assert "'''" not in cleaned
