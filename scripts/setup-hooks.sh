#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$ROOT_DIR/.githooks"

if [[ ! -d "$HOOKS_DIR" ]]; then
    echo "Error: .githooks directory not found."
    exit 1
fi

git config core.hooksPath .githooks

chmod +x "$HOOKS_DIR/commit-msg"
chmod +x "$HOOKS_DIR/pre-push"

echo
echo "Git hooks configured successfully."
echo
echo "Hooks path:"
echo "  $(git config --get core.hooksPath)"
echo
echo "Enabled hooks:"
echo "  commit-msg  - validates Conventional Commit messages"
echo "  pre-push    - runs unit tests before push"