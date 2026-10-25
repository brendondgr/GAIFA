#!/usr/bin/env bash
# Builds the speech engines inside the mod (plan 12.1): runtime/venvs/{kokoro,breeze-tts}, runtime/breeze-tts
# (Breeze source at engines/breeze/UPSTREAM_COMMIT plus its patches), then the engines' own installers, which
# add the programs, the kokoro-tts / breeze-tts launchers in ~/.local/bin and the entries in
# ~/.config/tts-engines/engines.json (video-maker reads both), and run each engine's smoke test. Re-running is safe.
#   scripts/install-runtime.sh [--accel <rocm|cuda|xpu|mps|cpu>] [--accept-breeze-license] [--allow-cpu-breeze] [--dry-run]
# --accel (plan 39.4; default GAIFA_ACCEL, else rocm): ROCm on gfx1151 installs the exact packages in locks/*.txt
# (as tested on this machine); any other accelerator installs PyTorch from its own index (scripts/torch_index.py)
# through the engines' installers. Breeze runs on ROCm, CUDA, and (slowly, with --allow-cpu-breeze) the CPU.
# --dry-run prints what would run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HUB="$(cd "$ROOT/../.." && pwd)"
RT="$ROOT/runtime"
ACCEPT=0 ALLOW_CPU=0 DRY=0
ACCEL="${GAIFA_ACCEL:-rocm}"
ARCH="${GAIFA_GPU_ARCH:-gfx1151}"
while [ $# -gt 0 ]; do
  case "$1" in
    --accel) ACCEL="$2"; shift 2 ;;
    --accept-breeze-license) ACCEPT=1; shift ;;
    --allow-cpu-breeze) ALLOW_CPU=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ "$ACCEL" = vulkan ] && ACCEL=cpu          # PyTorch has no Vulkan backend
export HF_HOME="$HUB/data/models/hf-cache" HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
KOKORO_INDEX=https://rocm.nightlies.amd.com/v2/gfx1151/
BREEZE_INDEX=https://nightly.repo.amd.com/rocm/whl-next/
BREEZE_TORCH="torch==2.9.1 torchaudio==2.9.1"      # what Breeze upstream pins and tests (engines/probe.py)
LOCKED=0
[ "$ACCEL" = rocm ] && [ "$ARCH" = gfx1151 ] && LOCKED=1

run() { if [ "$DRY" = 1 ]; then printf '%q ' "$@"; echo; else "$@"; fi; }
index() { python3 "$ROOT/scripts/torch_index.py" "$1"; }

venv() {  # name index: the exact lock (gfx1151)
  [ -x "$RT/venvs/$1/bin/python" ] || run uv venv -q --python 3.12 --python-preference only-managed "$RT/venvs/$1"
  run uv pip install -q --python "$RT/venvs/$1/bin/python" --index-url "$2" --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match -r "$ROOT/locks/$1.txt"
}

echo "== kokoro ($ACCEL)"
if [ "$LOCKED" = 1 ]; then
  venv kokoro "$KOKORO_INDEX"
  run bash "$ROOT/engines/install.sh" --gpu rocm --rocm-index "$KOKORO_INDEX" --prefix "$RT/venvs/kokoro"
else
  case "$ACCEL" in
    cuda) run bash "$ROOT/engines/install.sh" --gpu cuda --cuda "$(basename "$(index cuda)")" --prefix "$RT/venvs/kokoro" ;;
    rocm) run bash "$ROOT/engines/install.sh" --gpu rocm --rocm-arch "$ARCH" --prefix "$RT/venvs/kokoro" ;;
    xpu|mps|cpu) run bash "$ROOT/engines/install.sh" --gpu "$ACCEL" --prefix "$RT/venvs/kokoro" ;;
    *) echo "install-runtime.sh: no Kokoro build for $ACCEL" >&2; exit 2 ;;
  esac
fi

echo "== breeze ($ACCEL)"
[ "$ACCEPT" = 1 ] || { echo "Breeze TTS 2 is research / non-commercial only; re-run with --accept-breeze-license to install it"; exit 0; }
B=(--whisper openai/whisper-large-v3-turbo --prefix "$RT/venvs/breeze-tts" --src "$RT/breeze-tts"
   --weights "$HUB/data/models/tts/breeze-tts-2" --accept-license)
if [ "$LOCKED" = 1 ]; then
  venv breeze-tts "$BREEZE_INDEX"
  run bash "$ROOT/engines/breeze/install.sh" --backend rocm --device cuda --dtype bf16 --fast depth_decoder,backbone_decode \
    --torch-index "$BREEZE_INDEX" --torch-spec "torch[device-gfx1151] torchaudio" "${B[@]}"
  exit 0
fi
case "$ACCEL" in
  cuda) run bash "$ROOT/engines/breeze/install.sh" --backend cuda --device cuda --dtype bf16 --fast depth_decoder,backbone_decode \
          --torch-index "$(index cuda)" --torch-spec "$BREEZE_TORCH" "${B[@]}" ;;
  rocm) # another AMD GPU: AMD's index for its family, eager (HIP-graph capture hung on the TheRock builds tried)
        run bash "$ROOT/engines/breeze/install.sh" --backend rocm --device cuda --dtype bf16 --fast "" \
          --torch-index "$(index rocm)" --torch-spec "torch torchaudio" "${B[@]}" ;;
  cpu) [ "$ALLOW_CPU" = 1 ] || { echo "Breeze on the CPU is many times slower than real time; re-run with --allow-cpu-breeze to install it anyway"; exit 0; }
       B[1]=openai/whisper-base.en
       run bash "$ROOT/engines/breeze/install.sh" --backend cpu --device cpu --dtype bf16 --fast "" \
         --torch-index "$(index cpu)" --torch-spec "$BREEZE_TORCH" "${B[@]}" ;;
  *) echo "Breeze has no $ACCEL build (it runs on ROCm, CUDA or the CPU): skipped" ;;
esac
