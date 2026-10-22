#!/usr/bin/env bash
# Builds llama.cpp's llama-server from source for an accelerator (plan 39.2), where ggml-org publishes no
# Linux asset for it, or for macOS: cuda (needs the CUDA toolkit's nvcc), mps (Metal, Apple Silicon), cpu.
# The Vulkan build is the prebuilt release asset instead (setup/llama-cpp.md).
#   scripts/build-llama-cpp.sh <cuda|mps|cpu> [tag]      tag: a llama.cpp release, default b11445
# Clones the tag into runtime/llama.cpp/src/<tag>/, builds a static llama-server into
# runtime/llama.cpp/bin/llama-<tag>-<accel>/ and points runtime/llama.cpp/bin/current at it
# (LCPP_NO_LINK=1 skips that, to try a build without switching to it).
set -euo pipefail
ACCEL="${1:?usage: build-llama-cpp.sh <cuda|mps|cpu> [tag]}"
TAG="${2:-b11445}"
cd "$(dirname "$0")/.."
for cmd in git cmake; do
  command -v "$cmd" >/dev/null || { echo "build-llama-cpp.sh: needs $cmd (aihub setup host lists the install command)" >&2; exit 1; }
done
case "$ACCEL" in
  cuda)
    command -v nvcc >/dev/null || { echo "build-llama-cpp.sh: needs the CUDA toolkit's nvcc (Ubuntu: sudo apt install nvidia-cuda-toolkit, or NVIDIA's CUDA 12 toolkit; then make sure nvcc is on PATH)" >&2; exit 1; }
    FLAGS=(-DGGML_CUDA=ON) ;;
  mps) FLAGS=(-DGGML_METAL=ON) ;;
  cpu) FLAGS=(-DGGML_NATIVE=ON) ;;
  *) echo "build-llama-cpp.sh: no source build for $ACCEL (vulkan: the release asset; see setup/llama-cpp.md)" >&2; exit 2 ;;
esac
SRC="runtime/llama.cpp/src/$TAG"
if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$(dirname "$SRC")"
  git clone --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp "$SRC"
fi
BUILD="$SRC/build-$ACCEL"
cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF "${FLAGS[@]}"
cmake --build "$BUILD" --config Release -j "$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)" --target llama-server
OUT="runtime/llama.cpp/bin/llama-$TAG-$ACCEL"
mkdir -p "$OUT"
cp "$BUILD/bin/llama-server" "$OUT/"
"$OUT/llama-server" --version
if [ "${LCPP_NO_LINK:-}" != "1" ]; then
  ln -sfn "llama-$TAG-$ACCEL" runtime/llama.cpp/bin/current
  echo "runtime/llama.cpp/bin/current -> llama-$TAG-$ACCEL"
fi
