#!/usr/bin/env bash
# Builds .venv/ for the stt mod (setup/stt.md). Run by `aihub install stt`.
# 1. a uv-managed Python 3.14 venv with requirements-dev.txt (faster-whisper, onnxruntime, soxr, pytest);
# 2. the ROCm build of CTranslate2 over PyPI's CPU/CUDA one, from runtime/wheels/ (kept, gitignored),
#    fetched from the CTranslate2 GitHub release when it isn't there yet.
set -euo pipefail
cd "$(dirname "$0")"
PY=3.14
CT2=4.8.1
WHEELS=runtime/wheels
uv venv --quiet --allow-existing --python-preference only-managed --python "$PY" .venv
uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt

if [ -e /dev/kfd ]; then
  tag="cp${PY/./}"
  wheel=$(ls "$WHEELS"/ctranslate2-$CT2-$tag-$tag-manylinux*x86_64.whl 2>/dev/null | head -1 || true)
  if [ -z "$wheel" ]; then
    mkdir -p "$WHEELS" runtime/tmp
    zip=runtime/tmp/rocm-python-wheels-Linux.zip
    echo "fetching the ROCm CTranslate2 $CT2 wheels (~400 MB) from GitHub"
    curl -fL --retry 3 -o "$zip" "https://github.com/OpenNMT/CTranslate2/releases/download/v$CT2/rocm-python-wheels-Linux.zip"
    # The dash after the second tag keeps the free-threaded cp314t wheel out.
    unzip -o -j -d "$WHEELS" "$zip" "*$tag-$tag-manylinux*x86_64.whl"
    rm -f "$zip"
    wheel=$(ls "$WHEELS"/ctranslate2-$CT2-$tag-$tag-manylinux*x86_64.whl | head -1)
  fi
  uv pip install --quiet --python .venv/bin/python --reinstall --no-deps "$wheel"
  echo "installed the ROCm build of CTranslate2 from $wheel"
fi
echo "installed stt into .venv"
