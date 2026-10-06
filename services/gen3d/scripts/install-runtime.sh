#!/usr/bin/env bash
# Builds CubeArt inside the mod (plan 12.2): runtime/CubeArt/ with the upstream code (Roblox/cube at a
# pinned commit), a `weights` link to the hub's data/models/3d, and .venv/ created inside the ROCm
# image and layered on the image's /opt/venv torch (a .pth file), with the exact packages in
# locks/cubeart.txt. The image's torch/numpy family is pinned so pip never replaces it.
# Re-running is safe: finished steps are skipped. CubeArt's own scripts (cubeart, cube-run,
# scripts/) come from the old ~/Models/3D/CubeArt and are kept as they are; the mod only needs
# cube/, .venv/ and .cache/.
#   scripts/install-runtime.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HUB="$(cd "$ROOT/../.." && pwd)"
CA="$ROOT/runtime/CubeArt"
IMAGE="${GEN3D_IMAGE:-docker.io/kyuz0/amd-strix-halo-comfyui:latest}"
COMMIT=3c6d06ddbef3160a1e1950cb13ab63dd12a61e50

mkdir -p "$CA/.cache"
if [ ! -d "$CA/cube/.git" ]; then
  echo "== cube source → $CA/cube"
  git clone --quiet https://github.com/Roblox/cube.git "$CA/cube"
  git -C "$CA/cube" checkout --quiet "$COMMIT"
fi
[ -e "$CA/weights" ] || ln -s ../../../../data/models/3d "$CA/weights"
podman image exists "$IMAGE" || { echo "the ROCm image $IMAGE isn't pulled (podman pull $IMAGE)" >&2; exit 1; }

echo "== venv (inside $IMAGE)"
podman run --rm --security-opt label=disable -v "$CA:$CA" -v "$ROOT/locks:$ROOT/locks:ro" \
  -e PIP_CACHE_DIR="$CA/.cache/pip" "$IMAGE" bash -euc '
CA="$1"; LOCK="$2"
[ -x "$CA/.venv/bin/python" ] || /usr/bin/python3.13 -m venv "$CA/.venv"
echo /opt/venv/lib/python3.13/site-packages > "$CA/.venv/lib/python3.13/site-packages/_opt_venv.pth"
/opt/venv/bin/pip list --format=freeze 2>/dev/null | grep -iE "^(torch|torchvision|torchaudio|triton|numpy)==" > "$CA/.venv/constraints.txt"
source "$CA/.venv/bin/activate"
pip install --quiet -c "$CA/.venv/constraints.txt" -r "$LOCK"
python -c "import torch, transformers, diffusers, trimesh, fpsample, skimage; print(\"torch\", torch.__version__, \"transformers\", transformers.__version__)"
python -c "from transformers import Qwen3VLForConditionalGeneration; print(\"Qwen3-VL ok\")"
' _ "$CA" "$ROOT/locks/cubeart.txt"
echo "installed CubeArt in $CA (weights: $(readlink -f "$CA/weights"))"
