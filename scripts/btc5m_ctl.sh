#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v uv >/dev/null 2>&1; then
    exec uv run --locked --project "$repo_dir" btc5m "$@"
fi
exec "$HOME/.local/bin/uv" run --locked --project "$repo_dir" btc5m "$@"
