#!/usr/bin/env bash
# Builds the voice mod's environment (setup/llama-cpp.md). Run by `gaifa install voice`.
# 1. .venv/ (uv-managed Python) with requirements-dev.txt;
# 2. llama.cpp's release build for the variant into runtime/llama.cpp/bin/llama-<tag>-<accel>/, checked against
#    its sha256, with runtime/llama.cpp/bin/current pointing at it (--accel, else GAIFA_ACCEL, else vulkan
#    where a Vulkan driver is found, cpu otherwise);
# 3. the Silero VAD model (2 MB, MIT) into runtime/vad/, which finds the end of your turn.
set -euo pipefail
cd "$(dirname "$0")"
ACCEL="${GAIFA_ACCEL:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --accel) ACCEL="$2"; shift 2 ;;
    *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
  esac
done
if [ -z "$ACCEL" ]; then
  if [ "$(uname -s)" = Darwin ]; then ACCEL=mps
  elif ls /usr/share/vulkan/icd.d/*.json >/dev/null 2>&1; then ACCEL=vulkan
  else ACCEL=cpu; fi
fi
TAG=b12292
case "$(uname -s)-$(uname -m)-$ACCEL" in
  Linux-x86_64-vulkan) ASSET="llama-$TAG-bin-ubuntu-vulkan-x64.tar.gz"; SHA=01a6e2a7caa8d6ab6cb2dd906bd7c5c435440849c259440b1c3d3724850fa8e7 ;;
  Linux-x86_64-cuda)   ASSET="llama-$TAG-bin-ubuntu-cuda-12.8-x64.tar.gz"; SHA=2ef7a79a1e6d2b8aea76fc4e8a2448619869588c5914a514831bbe17e61dcbfd ;;
  Linux-x86_64-rocm)   ASSET="llama-$TAG-bin-ubuntu-vulkan-x64.tar.gz"; SHA=01a6e2a7caa8d6ab6cb2dd906bd7c5c435440849c259440b1c3d3724850fa8e7 ;;
  Linux-x86_64-*)      ASSET="llama-$TAG-bin-ubuntu-x64.tar.gz"; SHA=ffaf53f17a4601493e6ffb5869c9f0c7d400bb7e124fe0096eee3b65a5862568 ;;
  Linux-aarch64-vulkan) ASSET="llama-$TAG-bin-ubuntu-vulkan-arm64.tar.gz"; SHA=462b22e035311435d6f9708150216718e3480394cc6033c59d993e41a252ef27 ;;
  Linux-aarch64-*)     ASSET="llama-$TAG-bin-ubuntu-arm64.tar.gz"; SHA=e2e199c6e3094a2abb4f4745aab0ad036b545bab97113ebcb7d696cfbe4ac656 ;;
  *) ASSET=""; SHA="" ;;
esac

uv venv --quiet --allow-existing --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt

BIN=runtime/llama.cpp/bin
DEST="$BIN/llama-$TAG-$ACCEL"
if [ -x "$DEST/llama-server" ]; then
  echo "llama.cpp $TAG ($ACCEL) is already in $DEST"
elif [ -n "$ASSET" ]; then
  mkdir -p runtime/llama.cpp/vendor "$BIN"
  tarball="runtime/llama.cpp/vendor/$ASSET"
  if [ ! -f "$tarball" ]; then
    echo "fetching $ASSET from github.com/ggml-org/llama.cpp"
    curl -fL --retry 3 -o "$tarball.part" "https://github.com/ggml-org/llama.cpp/releases/download/$TAG/$ASSET"
    mv "$tarball.part" "$tarball"
  fi
  echo "$SHA  $tarball" | sha256sum -c --quiet -
  rm -rf "$DEST.tmp" && mkdir -p "$DEST.tmp"
  tar -xzf "$tarball" -C "$DEST.tmp" --strip-components=1
  mv "$DEST.tmp" "$DEST"
else
  echo "no llama.cpp release build for $(uname -s) $(uname -m) ($ACCEL): build $TAG yourself and point" >&2
  echo "VOICE_LLAMA_BIN at its llama-server (setup/llama-cpp.md)" >&2
fi
[ -x "$DEST/llama-server" ] && ln -sfn "llama-$TAG-$ACCEL" "$BIN/current"

VAD=runtime/vad/silero_vad.onnx
VAD_SHA=1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3
if [ ! -f "$VAD" ]; then
  mkdir -p runtime/vad
  if curl -fL --retry 3 -o "$VAD.part" "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2/src/silero_vad/data/silero_vad.onnx" \
     && echo "$VAD_SHA  $VAD.part" | sha256sum -c --quiet -; then
    mv "$VAD.part" "$VAD"
  else
    rm -f "$VAD.part"
    echo "couldn't fetch the Silero VAD model: turn ends fall back to a loudness gate" >&2
  fi
fi
echo "installed voice into .venv ($ACCEL, llama.cpp $TAG)"
