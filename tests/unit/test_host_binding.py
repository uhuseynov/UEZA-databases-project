"""The API has no authentication, so nothing listens on the network unless asked to.

Covers the defaults of the app started on the host (``make run``, ``python -m src.main``) and
checks that the Docker image keeps listening on all interfaces *inside* the container, which
the published port needs.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import Settings

ROOT = Path(__file__).resolve().parents[2]
needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


def settings_from(monkeypatch, tmp_path, **env):
    """Settings as an environment would build them, ignoring any .env of the developer."""
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.chdir(tmp_path)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings()


def test_the_default_host_is_loopback(monkeypatch, tmp_path):
    assert settings_from(monkeypatch, tmp_path).app_host == "127.0.0.1"


def test_listening_on_all_interfaces_is_an_explicit_opt_in(monkeypatch, tmp_path):
    assert settings_from(monkeypatch, tmp_path, APP_HOST="0.0.0.0").app_host == "0.0.0.0"


def test_env_example_defaults_to_loopback():
    lines = (ROOT / ".env.example").read_text().splitlines()
    values = [line.split("=", 1)[1] for line in lines if line.startswith("APP_HOST=")]

    assert values == ["127.0.0.1"]


def make_run_command(tmp_path, *args, env=None):
    """The command ``make run`` would execute (``-n``: nothing is started).

    Run from an empty directory, so a developer's own ``.env`` cannot change the result.
    """
    clean = {"PATH": os.environ["PATH"], **(env or {})}
    result = subprocess.run(
        ["make", "-f", str(ROOT / "Makefile"), "-n", "run", *args],
        cwd=tmp_path,
        env=clean,
        capture_output=True,
        text=True,
        check=True,
    )
    joined = re.sub(r"\\\n\s*", " ", result.stdout)  # the recipe continues lines with a backslash
    (command,) = [line for line in joined.splitlines() if "uvicorn" in line]
    return command


@needs_make
def test_make_run_binds_loopback_by_default(tmp_path):
    command = make_run_command(tmp_path)

    assert re.search(r"--host 127\.0\.0\.1\b", command)
    assert "0.0.0.0" not in command


@needs_make
@pytest.mark.parametrize("how", ["command line", "environment"])
def test_make_run_honours_an_explicit_override(tmp_path, how):
    if how == "command line":
        command = make_run_command(tmp_path, "APP_HOST=0.0.0.0")
    else:
        command = make_run_command(tmp_path, env={"APP_HOST": "0.0.0.0"})

    assert re.search(r"--host 0\.0\.0\.0\b", command)


@needs_make
def test_a_value_in_dot_env_is_used_by_make_run(tmp_path):
    (tmp_path / ".env").write_text("APP_HOST=0.0.0.0\nAPP_PORT=9123\n")

    command = make_run_command(tmp_path)

    assert re.search(r"--host 0\.0\.0\.0\b", command)
    assert "--port 9123" in command


def test_the_docker_image_listens_on_all_interfaces_inside_the_container():
    dockerfile = (ROOT / "Dockerfile").read_text()

    (cmd,) = re.findall(r"^CMD (\[.*\])$", dockerfile, re.M)
    assert '"--host", "0.0.0.0"' in cmd  # the published port reaches it through the bridge


def test_compose_publishes_the_app_on_loopback_unless_overridden():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert '"${APP_BIND_ADDRESS:-127.0.0.1}:${APP_PORT:-8000}:8000"' in compose
    assert '"127.0.0.1:${MARIADB_PORT:-3306}:3306"' in compose
