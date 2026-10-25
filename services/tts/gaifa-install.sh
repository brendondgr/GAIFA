#!/usr/bin/env bash
# Builds .venv/ for the tts mod (run by `gaifa install tts`). The standalone installer is
# install.sh; under GAIFA there is no localtts.service. The engines live in runtime/ and are
# rebuilt by scripts/install-runtime.sh (plan 12.1).
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt
echo "installed tts into .venv"
