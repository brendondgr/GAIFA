#!/usr/bin/env bash
# Builds .venv/ for the lcpp mod (run by `aihub install lcpp`). llama.cpp itself lives in
# runtime/ (gitignored; see setup/llama-cpp.md).
set -euo pipefail
cd "$(dirname "$0")"
UV_PYTHON_PREFERENCE=only-managed uv sync --quiet --python 3.14
echo "installed lcpp into .venv"
