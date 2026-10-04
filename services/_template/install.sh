#!/usr/bin/env bash
# Builds .venv/ for this mod. Run by `aihub new`; run it again after changing requirements.txt.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  # uv-managed Python lives in your home folder, so the venv works both on the host and in a toolbox.
  uv venv --quiet --python-preference only-managed .venv
  uv pip install --quiet --python .venv/bin/python -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi
echo "installed $(basename "$PWD") into .venv"
