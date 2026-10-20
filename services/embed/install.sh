#!/usr/bin/env bash
# Builds .venv/ for the embed mod (run by `aihub install embed`) and downloads EmbeddingGemma 2 (1.5 GB) into
# data/models/embed/embeddinggemma-2 when it isn't there. Re-running is safe.
#   install.sh            on gfx1151: the exact packages in locks/embed.txt (ROCm nightlies, as tested here)
#   install.sh --cpu      any other machine: requirements.txt with PyTorch's CPU wheels (fp32, slower)
#   install.sh --no-weights
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HUB="$(cd "$ROOT/../.." && pwd)"
MODELS="${AIHUB_MODELS:-$HUB/data/models}"
ROCM_INDEX=https://nightly.repo.amd.com/rocm/whl-next/      # tts's Breeze line (services/tts/scripts/install-runtime.sh)
REPO=google/embeddinggemma-2
REVISION=914f7f89142e33e77833254d9c9b90c3cef7303b           # = embed/settings.py REVISION
CPU=0 WEIGHTS=1
for a in "$@"; do
  case "$a" in
    --cpu) CPU=1 ;;
    --no-weights) WEIGHTS=0 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
cd "$ROOT"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
if [ "$CPU" = 1 ]; then
  uv pip install --quiet --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match -r requirements.txt
else
  uv pip install --quiet --python .venv/bin/python --index-url "$ROCM_INDEX" --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match -r locks/embed.txt
fi
uv pip install --quiet --python .venv/bin/python pytest
command -v ffmpeg >/dev/null || echo "  WARNING: ffmpeg not on PATH; audio and video inputs need it"

DEST="$MODELS/embed/embeddinggemma-2"
if [ "$WEIGHTS" = 1 ] && [ ! -f "$DEST/model.safetensors" ]; then
  echo "downloading $REPO@${REVISION:0:8} (1.5 GB) to $DEST"
  HF_HOME="$MODELS/hf-cache" .venv/bin/hf download "$REPO" --revision "$REVISION" --local-dir "$DEST"
fi
echo "installed embed into .venv"
