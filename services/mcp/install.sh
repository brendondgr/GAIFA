#!/usr/bin/env bash
# Builds .venv/ for the mcp mod (run by `gaifa install mcp`): FastAPI and the MCP Python SDK. No GPU, no models.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  uv venv --quiet --python-preference only-managed .venv
  uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt
else
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements-dev.txt
fi
echo "installed mcp into .venv"
