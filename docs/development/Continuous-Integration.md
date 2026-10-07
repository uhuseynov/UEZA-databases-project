# Continuous Integration

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

The CI workflow is defined in `.github/workflows/ci.yml` and runs for pushes to `main`, pull requests targeting `main`, and manual workflow dispatches.

## Gated Pipeline

The jobs form a strict dependency chain:

```text
Unit Tests
    ↓
Integration Tests
    ↓
Docker Build & Smoke Test
    ↓
CI Passed
```

A failed stage prevents every downstream stage from running. Docker validation therefore occurs only after both test layers have passed.

## Unit Tests

The first gate installs the locked `uv` environment on Python 3.14 and runs:

```bash
uv run pytest tests/unit -ra
```

## Integration Tests

Integration tests depend on the unit-test job. CI starts the pinned MariaDB service from `docker-compose.yml`, waits for it to become healthy, applies all Alembic migrations, and then runs:

```bash
uv run pytest tests/integration -ra
```

The CI process connects from the runner through `127.0.0.1:3306`. MariaDB logs are printed when this stage fails, and containers/volumes are cleaned up even after failure.

## Docker Build and Smoke Test

This stage runs only after integration tests pass. It builds the application image, starts the complete Compose stack without rebuilding it, waits for service health checks, and verifies:

```text
GET /health → HTTP success
```

This exercises the real container startup path, including the application entrypoint, Alembic migration execution, FastAPI startup, MariaDB connectivity, and the application health check.

## Final Gate

`CI Passed` is reachable only when every previous gate succeeds. It is the natural single required status check for branch protection on `main`.

## Concurrency

The workflow cancels an older in-progress CI run when a newer run for the same workflow/ref is started. This avoids spending runner time validating commits that have already been superseded.
