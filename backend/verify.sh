#!/usr/bin/env bash
# The backend green bar: lint, format check, type-check (incl. reportDeprecated), tests.
# Run it before every commit. Fails fast on the first red stage.
set -euo pipefail

cd "$(dirname "$0")"

echo "== ruff check =="
uv run ruff check .

echo "== ruff format --check =="
uv run ruff format --check .

echo "== pyright (incl. reportDeprecated) =="
uv run pyright

echo "== pytest =="
uv run pytest

echo "All green."
