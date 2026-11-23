"""The documentation validator: it must catch real drift and stay quiet about correct docs."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)

CONFIG = """
class Settings:
    app_env: str = "development"
    llm_model: str = "x"
    model_config = {}
"""
MAKEFILE = """APP_PORT ?= 8000
EVAL_RUNS ?= 5

.PHONY: run
run: ## runs
\t@echo run

test: ## tests
\t@echo test
"""
CONFIGURATION = """# Configuration

| Variable | Default |
| --- | --- |
| `APP_ENV` | development |
| `LLM_MODEL` | x |
"""


def make_repo(tmp_path: Path, **pages: str) -> Path:
    """A tiny repository: Makefile, settings, .env.example, a Configuration page and the pages."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "config.py").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    (tmp_path / ".env.example").write_text("APP_ENV=development\n# LLM_MODEL=x\n", encoding="utf-8")
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "Configuration.md").write_text(
        CONFIGURATION, encoding="utf-8"
    )
    for name, text in pages.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def problems(root: Path) -> list[str]:
    return check_docs.check(root)


def test_the_real_repository_documentation_is_consistent():
    assert problems(ROOT) == []


def test_a_correct_tiny_repository_has_no_problems(tmp_path):
    root = make_repo(
        tmp_path,
        **{
            "README.md": (
                "# Title\n\nSee [docs](docs/Home.md#start-here) and `src/config.py`, "
                "then `make run`.\n\n```bash\nmake test\nmake run EVAL_RUNS=3\n```\n"
            ),
            "docs/Home.md": "# Home\n\n## Start here\n\n[back](../README.md#title)\n",
        },
    )

    assert problems(root) == []


# --- links and anchors -------------------------------------------------------------------------


def test_a_missing_link_target_is_reported_with_its_line(tmp_path):
    root = make_repo(tmp_path, **{"README.md": "# T\n\nfine\n\n[gone](docs/Missing.md)\n"})

    assert problems(root) == ["README.md:5: link target does not exist: docs/Missing.md"]


def test_a_missing_anchor_is_reported(tmp_path):
    root = make_repo(
        tmp_path,
        **{"README.md": "# T\n\n[x](docs/Home.md#nowhere)\n", "docs/Home.md": "# Home\n"},
    )

    assert problems(root) == ["README.md:3: no heading for anchor #nowhere in Home.md"]


def test_external_links_and_links_in_code_are_not_checked(tmp_path):
    root = make_repo(
        tmp_path,
        **{
            "README.md": (
                "# T\n\n[web](https://example.org/x#y) [mail](mailto:a@b.c)\n\n"
                "`[not a link](nowhere.md)`\n\n```\n[also not](nowhere.md)\n```\n"
            )
        },
    )

    assert problems(root) == []


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("Vector Search and Index Parameters", "vector-search-and-index-parameters"),
        (
            "Building the article list: `data/build_article_list.py`",
            "building-the-article-list-databuild_article_listpy",
        ),
        ("What it does (and doesn't)", "what-it-does-and-doesnt"),
        ("[Linked](x.md) title", "linked-title"),
        ("Café résumé", "café-résumé"),
    ],
)
def test_anchors_follow_githubs_rules(heading, anchor):
    assert check_docs.slug(heading) == anchor


def test_repeated_headings_get_numbered_anchors(tmp_path):
    page = tmp_path / "p.md"
    page.write_text("# Same\n\n## Same\n\n## Same\n\n```\n# Not a heading\n```\n", encoding="utf-8")

    assert check_docs.anchors(page) == {"same", "same-1", "same-2"}


# --- repository paths --------------------------------------------------------------------------


def test_a_path_that_does_not_exist_is_reported(tmp_path):
    root = make_repo(tmp_path, **{"README.md": "# T\n\nSee `src/gone.py` and `src/config.py`.\n"})

    assert problems(root) == ["README.md:3: path does not exist: src/gone.py"]


def test_only_things_that_look_like_repository_paths_are_checked(tmp_path):
    root = make_repo(
        tmp_path,
        **{
            "README.md": (
                "# T\n\n`docs/<name>.md` `src/*.py` `a/b` `https://x.org/src/y` `.cache/articles` "
                "`data/articles.generated.csv` `pyproject.toml`\n"
            ),
            "pyproject.toml": "",
        },
    )

    assert problems(root) == []


# --- make targets ------------------------------------------------------------------------------


def test_a_make_target_that_does_not_exist_is_reported_inline_and_in_code_blocks(tmp_path):
    root = make_repo(
        tmp_path,
        **{"README.md": "# T\n\nRun `make nothing`.\n\n```bash\nmake alsonot\n$ make run\n```\n"},
    )

    assert problems(root) == [
        "README.md:3: Makefile has no target 'nothing'",
        "README.md:6: Makefile has no target 'alsonot'",
    ]


def test_options_and_variables_before_the_target_are_skipped(tmp_path):
    assert check_docs.make_target_of("-n APP_PORT=1 run") == "run"
    assert check_docs.make_target_of("") is None
    assert check_docs.make_target_of("run ARGS='--x'") == "run"


def test_prose_that_says_make_is_not_a_make_command(tmp_path):
    root = make_repo(tmp_path, **{"README.md": "# T\n\nThat would make slower searches.\n"})

    assert problems(root) == []


# --- configuration names -----------------------------------------------------------------------


def test_a_setting_missing_from_the_configuration_table_is_reported(tmp_path):
    root = make_repo(tmp_path)
    config = CONFIG.replace(
        "    model_config = {}\n", "    model_config = {}\n    new_setting: int = 1\n"
    )
    (root / "src" / "config.py").write_text(config, encoding="utf-8")

    assert problems(root) == [
        "docs/architecture/Configuration.md: setting not in the table: NEW_SETTING"
    ]


def test_a_table_row_that_is_not_a_setting_is_reported(tmp_path):
    root = make_repo(tmp_path)
    page = root / "docs" / "architecture" / "Configuration.md"
    page.write_text(page.read_text(encoding="utf-8") + "| `OLD_SETTING` | 1 |\n", encoding="utf-8")

    assert problems(root) == [
        "docs/architecture/Configuration.md: table row is not a setting: OLD_SETTING"
    ]


def test_an_unknown_name_in_the_example_environment_file_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / ".env.example").write_text(
        "APP_ENV=a\nMARIADB_ROOT_PASSWORD=b\nTYPO_NAME=c\n", encoding="utf-8"
    )

    assert problems(root) == [".env.example:3: unknown setting TYPO_NAME"]


def test_a_prefixed_name_in_the_docs_must_be_a_known_setting(tmp_path):
    root = make_repo(
        tmp_path,
        **{
            "README.md": "# T\n\nSet `LLM_MODELL`, `LLM_MODEL`, `EVAL_RUNS` and `APP_BIND_ADDRESS`.\n"
        },
    )

    assert problems(root) == [
        "README.md:3: LLM_MODELL is not a setting, a Makefile variable or a Compose variable"
    ]


def test_the_command_line_reports_and_sets_the_exit_status(tmp_path, capsys):
    (tmp_path / "broken").mkdir()
    broken = make_repo(tmp_path / "broken", **{"README.md": "# T\n\n[x](nope.md)\n"})

    assert check_docs.main(["--root", str(broken)]) == 1
    assert "link target does not exist: nope.md" in capsys.readouterr().out
    assert check_docs.main(["--root", str(ROOT)]) == 0
