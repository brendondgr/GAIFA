#!/usr/bin/env bash
# Builds .venv/ for the decide mod (run by `aihub install decide`) and downloads d3-lite (1.7 GB) at its pinned
# revision into data/models/decide/d3-lite when it isn't there, then checks every file against the model's
# manifest. Re-running is safe.
#   install.sh            on gfx1151: the exact packages in locks/decide.txt (ROCm nightlies, as tested here)
#   install.sh --cpu      any other machine: requirements.txt with PyTorch's CPU wheels (slower)
#   install.sh --no-weights
#   install.sh --force    download the weights again (after `aihub check decide` reports changed files)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HUB="$(cd "$ROOT/../.." && pwd)"
MODELS="${AIHUB_MODELS:-$HUB/data/models}"
ROCM_INDEX=https://nightly.repo.amd.com/rocm/whl-next/      # tts's Breeze line, as embed
REPO=vllm-sr/d3-lite
REVISION=03560c26f5199c3c04129a2ccb38960c913635e0           # = decide/models/d3_lite.py REVISION (code read 2026-10-20)
CPU=0 WEIGHTS=1 FORCE=0
for a in "$@"; do
  case "$a" in
    --cpu) CPU=1 ;;
    --no-weights) WEIGHTS=0 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
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
    --index-strategy unsafe-best-match -r locks/decide.txt
fi
uv pip install --quiet --python .venv/bin/python pytest

DEST="$MODELS/decide/d3-lite"
if [ "$WEIGHTS" = 1 ] && { [ "$FORCE" = 1 ] || [ ! -f "$DEST/model-00001-of-00001.safetensors" ]; }; then
  echo "downloading $REPO@${REVISION:0:8} (1.7 GB) to $DEST"
  # The card's images aren't read by the runtime; --force replaces changed files with the pinned revision's.
  HF_HOME="$MODELS/hf-cache" .venv/bin/hf download "$REPO" --revision "$REVISION" --local-dir "$DEST" \
    --exclude "assets/*" $([ "$FORCE" = 1 ] && echo --force-download)
fi
if [ -f "$DEST/MODEL_MANIFEST.json" ]; then
  .venv/bin/python -I - "$DEST" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
listed = json.loads((root / "MODEL_MANIFEST.json").read_text())["files_sha256"]
bad = []
for name, want in listed.items():
    p = root / name
    if name.startswith("assets/") or not p.is_file():
        continue
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(16 << 20), b""):
            h.update(block)
    if h.hexdigest() != want:
        bad.append(name)
print("d3-lite: every file matches its manifest" if not bad else f"d3-lite: CHANGED FILES {bad}; run install.sh --force")
sys.exit(1 if bad else 0)
PY
fi
echo "installed decide into .venv"
