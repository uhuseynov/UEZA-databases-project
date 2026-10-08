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
make run             # FastAPI with hot reload
make test-unit       # unit tests
make test-integration
make test-all
make db-up           # MariaDB only
make up              # complete Docker Compose stack
make down
make migrate
make help
```

See [Git Hooks and Commit Messages](./Git-Hooks.md) and [Continuous Integration](./Continuous-Integration.md) for the repository gates around commits and pushes.
