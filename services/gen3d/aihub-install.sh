#!/usr/bin/env bash
# Builds .venv/ for the gen3d mod (run by `aihub install gen3d`). The standalone installer is
# install.sh; under AIHub there is no gen3d.service. The GPU worker runs in the ROCm container
# with CubeArt's own venv (~/Models/3D/CubeArt/.venv) until plan Phase 12.2.
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt
echo "installed gen3d into .venv"
