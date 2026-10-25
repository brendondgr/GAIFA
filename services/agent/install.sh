#!/usr/bin/env bash
# Builds .venv/ for the agent mod (run by `gaifa install agent`).
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt
echo "installed agent into .venv"
