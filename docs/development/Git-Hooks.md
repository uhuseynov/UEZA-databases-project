# Git Hooks and Commit Messages

[← Development Workflow](./Home.md) | [Documentation Home](../Home.md)

The repository stores shared Git hooks in `.githooks/`. They are enabled by `scripts/setup-hooks.sh`, normally through:

```bash
make setup
```

or:

```bash
make hooks
```

## Commit Message Validation

`.githooks/commit-msg` enforces a Conventional Commits-style subject:

```text
<type>(optional-scope): <description>
```

Supported types are:

```text
feat fix docs style refactor perf test build ci chore revert
```

Examples:

```text
feat: add article cache
fix(database): rollback failed transactions
docs: update ingestion documentation
ci: add integration test gate
refactor(mediawiki): simplify retry handling
```

Breaking changes may use `!` before the colon:

```text
feat(api)!: change search response format
```

Merge commits and Git-generated `Revert ...` subjects are allowed without applying the pattern.

## Pre-Push Gate

`.githooks/pre-push` checks that `uv` is available and runs:

```bash
uv run pytest tests/unit -q
```

A failed unit test rejects the local push. This is intentionally lighter than the remote CI pipeline: MariaDB integration tests and the Docker smoke test remain CI responsibilities rather than making every local push start the complete stack.

## Hook Installation

`scripts/setup-hooks.sh`:

1. locates the repository root,
2. verifies `.githooks/` exists,
3. sets `core.hooksPath` to `.githooks`, and
4. marks `commit-msg` and `pre-push` executable.

`.gitattributes` forces LF line endings for shell scripts and files under `.githooks/`, preventing CRLF shebang failures in Unix environments.

## Relationship to CI

Local hooks provide fast feedback, but they are not the source of truth for merge safety. Hooks can be bypassed locally; GitHub Actions performs the authoritative repository checks after a push or pull request.
