#!/usr/bin/env bash
# Builds the speech engines inside the mod (plan 12.1): runtime/venvs/{kokoro,breeze-tts} with the
# exact packages in locks/*.txt (ROCm nightlies for gfx1151, as tested on this machine),
# runtime/breeze-tts (Breeze source at engines/breeze/UPSTREAM_COMMIT plus its patches), then the
# engines' own installers, which add the programs, the kokoro-tts / breeze-tts launchers in
# ~/.local/bin and the entries in ~/.config/tts-engines/engines.json (video-maker reads both),
# and run each engine's smoke test. Re-running is safe.
#   scripts/install-runtime.sh [--accept-breeze-license]
# Another GPU: engines/setup.sh --plan picks the right torch build instead of the lock files.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HUB="$(cd "$ROOT/../.." && pwd)"
RT="$ROOT/runtime"
ACCEPT=0
[ "${1:-}" = --accept-breeze-license ] && ACCEPT=1
export HF_HOME="$HUB/data/models/hf-cache" HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
KOKORO_INDEX=https://rocm.nightlies.amd.com/v2/gfx1151/
BREEZE_INDEX=https://nightly.repo.amd.com/rocm/whl-next/

venv() {  # name index
  [ -x "$RT/venvs/$1/bin/python" ] || uv venv -q --python 3.12 --python-preference only-managed "$RT/venvs/$1"
  uv pip install -q --python "$RT/venvs/$1/bin/python" --index-url "$2" --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match -r "$ROOT/locks/$1.txt"
}

echo "== kokoro"
venv kokoro "$KOKORO_INDEX"
bash "$ROOT/engines/install.sh" --gpu rocm --rocm-index "$KOKORO_INDEX" --prefix "$RT/venvs/kokoro"

echo "== breeze"
[ "$ACCEPT" = 1 ] || { echo "Breeze TTS 2 is research / non-commercial only; re-run with --accept-breeze-license to install it"; exit 0; }
venv breeze-tts "$BREEZE_INDEX"
bash "$ROOT/engines/breeze/install.sh" --backend rocm --device cuda --dtype bf16 --fast depth_decoder,backbone_decode \
  --whisper openai/whisper-large-v3-turbo --torch-index "$BREEZE_INDEX" --torch-spec "torch[device-gfx1151] torchaudio" \
  --prefix "$RT/venvs/breeze-tts" --src "$RT/breeze-tts" --weights "$HUB/data/models/tts/breeze-tts-2" --accept-license
