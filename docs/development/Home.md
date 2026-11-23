# Development Workflow

[← Documentation Home](../Home.md)

The repository includes local developer tooling, repository-managed Git hooks, Docker Compose, and a gated GitHub Actions CI pipeline.

## First-Time Setup

After cloning the repository, run:

```bash
make setup
```

`make setup` installs the locked project environment through `uv` and configures the repository Git hooks through `scripts/setup-hooks.sh`.

If dependencies are already installed and only the hooks need to be configured:

```bash
make hooks
```

Git hooks are stored in `.githooks/` and activated locally with:

```bash
git config core.hooksPath .githooks
```

Git does not automatically enable repository-managed hooks after clone, so each contributor must run the setup command once.

## Local Development

Common commands are exposed through the root `Makefile`:

```bash
make run             # FastAPI with hot reload, on 127.0.0.1 (APP_HOST=0.0.0.0 exposes it)
make lint            # Ruff lint and format check, as in CI (make lint-fix, make format fix them)
make docs-check      # links, anchors, paths, make targets and setting names in the docs
make test-unit       # unit tests
make test-integration
make test-all
make db-up           # MariaDB only
make reindex         # rebuild the vector index (M=32 for another M, ARGS="..." forwards flags)
make ingest-sync     # re-ingest the articles that changed on Wikipedia (ARGS="--limit 5")
make ingest-sync-dry-run
make up              # complete Docker Compose stack
make down
make help
```

See [Git Hooks and Commit Messages](./Git-Hooks.md) and [Continuous Integration](./Continuous-Integration.md) for the repository gates around commits and pushes.

More: [Docker and Compose](./Docker.md) (what runs in the container and what on the host), [Scripts and Experiments](./Scripts.md), and [Installing Podman on Windows](../database/podman.md). `make help` lists every target.
