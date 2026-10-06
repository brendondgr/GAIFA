#!/usr/bin/env bash
# Builds .venv/ for the comfy adapter (run by `aihub install comfy`). ComfyUI itself runs in the
# strix-halo-comfyui toolbox (bin/comfyui), with its own Python.
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt
echo "installed comfy into .venv"
