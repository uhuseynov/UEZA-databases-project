# Continuous Integration

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

The CI workflow is defined in `.github/workflows/ci.yml` and runs for pushes to `main`, pull requests targeting `main`, and manual workflow dispatches.

## Gated Pipeline

```text
Lint ─────────────────────────┐
                              ▼
Unit Tests → Integration Tests → Docker Build & Smoke Test → CI Passed
```

The test jobs form a strict dependency chain, and `Lint` runs next to it in parallel. A failed stage prevents every downstream stage from running; `CI Passed` needs both `Lint` and the Docker job. Docker validation therefore occurs only after both test layers have passed.

## Lint

The `Lint` job installs only the `dev` dependency group (Ruff needs neither torch nor the runtime packages) and runs three checks, each of which fails the job (and so `CI Passed`): `ruff check --output-format=github .` (findings appear as annotations on the changed lines), `ruff format --check --diff .` (the log shows what the formatter would change) and `python3 scripts/check_docs.py` (see below). The rule set is in `pyproject.toml` (`[tool.ruff.lint]`): Pyflakes, the pycodestyle errors that are bugs, import order, pyupgrade and bugbear. Locally: `make lint` runs the first two (lint and format check, `make format` fixes the formatting, `make lint-fix` the safe lint findings), `make docs-check` runs the third, and `make ci` runs all of them plus the unit tests.

## Documentation check

[`scripts/check_docs.py`](../../scripts/check_docs.py) uses only the standard library and takes under a second. It checks that relative Markdown links and `#anchors` resolve, that repository paths written in backticks exist, that every `make <target>` mentioned exists in the Makefile, and that the settings table of [Configuration](../architecture/Configuration.md) lists exactly the fields of `src/config.py` (and that `.env.example` and the docs only use names the project knows). It does not judge prose, check external links or run commands. Its own tests are in `tests/unit/scripts/`, and the same check on the real documentation is one of them.

## Unit Tests

The first gate installs the locked `uv` environment on Python 3.14 and runs:

```bash
uv run pytest tests/unit -ra
```

## Integration Tests

Integration tests depend on the unit-test job. CI starts the pinned MariaDB service from `docker-compose.yml`, waits for it to become healthy (the image loads `schema.sql` into the empty database), and then runs:

```bash
uv run pytest tests/integration -ra
```

Some database tests skip themselves when MariaDB or its schema is missing. In CI that would turn a broken database into a green run, so the step fails if pytest reports any skipped test.

None of the integration tests contacts Wikipedia, a language model or the Hugging Face hub: the MediaWiki client tests use a mocked HTTP transport, and the database tests insert synthetic articles and vectors through the repository. The only external service is MariaDB. A check against the live services is a manual step (see [Docker and Compose](./Docker.md) and the evaluation documentation).

The CI process connects from the runner through `127.0.0.1:3306`. MariaDB logs are printed when this stage fails, and containers/volumes are cleaned up even after failure.

## Docker Build and Smoke Test

This stage runs only after integration tests pass. It builds the application image, starts the complete Compose stack without rebuilding it, waits for service health checks, and verifies:

```text
GET /health → HTTP success   (through the loopback-published port)
```

This exercises the real container startup path, including the application entrypoint, FastAPI startup, MariaDB connectivity, and the application health check.

## Final Gate

`CI Passed` is reachable only when `Lint` and every test gate succeed. It is the natural single required status check for branch protection on `main`.

## Concurrency

The workflow cancels an older in-progress CI run when a newer run for the same workflow/ref is started. This avoids spending runner time validating commits that have already been superseded.
