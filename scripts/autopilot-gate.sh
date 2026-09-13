#!/usr/bin/env bash
# Called through the shared two-slot verification semaphore.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$HOME/.local/bin:$PATH"
bash -n scripts/autopilot.sh
bash -n scripts/autopilot-gate.sh
uv lock --check
uv run --locked --python 3.12 pytest -q
uv run --locked --python 3.12 ruff check src/btc5m tests scripts/autopilot_result.py
uv run --locked --python 3.12 ruff format --check src/btc5m tests scripts/autopilot_result.py
uv run --locked --python 3.12 mypy src/btc5m
