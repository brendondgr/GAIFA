#!/usr/bin/env bash
# Builds .venv/ for the tts mod (run by `aihub install tts`). The standalone installer is
# install.sh; under AIHub there is no localtts.service, and the engines come from
# engines/setup.sh (~/.config/tts-engines/engines.json) until plan Phase 12.1.
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt
echo "installed tts into .venv"
