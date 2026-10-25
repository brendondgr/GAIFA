#!/usr/bin/env bash
# Builds CubeArt inside the mod (plan 12.2): runtime/CubeArt/ with the upstream code (Roblox/cube at a
# pinned commit), a `weights` link to the hub's data/models/3d, and .venv/ created inside the ROCm
# image and layered on the image's /opt/venv torch (a .pth file), with the exact packages in
# locks/cubeart.txt. The image's torch/numpy family is pinned so pip never replaces it.
# Re-running is safe: finished steps are skipped. CubeArt's own scripts (cubeart, cube-run,
# scripts/) come from the old ~/Models/3D/CubeArt and are kept as they are; the mod only needs
# cube/, .venv/ and .cache/.
#   scripts/install-runtime.sh [--accel rocm|cuda]
# --accel (plan 39.7; default GAIFA_ACCEL, else rocm): rocm builds every venv inside the ROCm image, as above;
# cuda builds them on the host (Python 3.13 from uv, PyTorch's CUDA build from scripts/torch_index.py,
# the same locks and the same shims), and the workers then run there instead of in a container.
set -euo pipefail
ACCEL="${GAIFA_ACCEL:-rocm}"
while [ $# -gt 0 ]; do
  case "$1" in
    --accel) ACCEL="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
case "$ACCEL" in rocm|cuda) ;; *) echo "install-runtime.sh: 3D Generate's engines run on ROCm or CUDA, not $ACCEL" >&2; exit 2 ;; esac
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
mkdir -p "$HUB/data/models/3d"   # a fresh clone has no models yet: the link must not dangle
[ -L "$CA/weights" ] || [ -e "$CA/weights" ] || ln -s ../../../../data/models/3d "$CA/weights"
if [ "$ACCEL" = cuda ]; then
  RT="$ROOT/runtime"; SP=lib/python3.13/site-packages
  for cmd in uv git python3; do command -v "$cmd" >/dev/null || { echo "install-runtime.sh: needs $cmd" >&2; exit 1; }; done
  clone() { [ -d "$2/.git" ] || git clone --quiet "$1" "$2"; git -C "$2" checkout --quiet "$3"; }
  clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git "$RT/hunyuan3d-2.1" 82920d643c0dc2f7bfd7255f45f62d386edfe60c
  clone https://github.com/facebookresearch/sam-3d-objects.git "$RT/sam3d-objects" f91db411c50efee93d8db7aeb323885650f6f722
  clone https://github.com/facebookresearch/dinov2.git "$RT/sam3do/dinov2" 7764ea0f912e53c92e82eb78a2a1631e92725fc8
  INDEX="$(python3 "$ROOT/scripts/torch_index.py" cuda)"
  echo "== CubeArt venv on the host (PyTorch from $INDEX)"
  [ -x "$CA/.venv/bin/python" ] || uv venv -q --python 3.13 --python-preference only-managed "$CA/.venv"
  uv pip install -q --python "$CA/.venv/bin/python" --index-url "$INDEX" torch torchvision torchaudio
  uv pip freeze --python "$CA/.venv/bin/python" | grep -iE "^(torch|torchvision|torchaudio|triton|numpy)==" > "$CA/.venv/constraints.txt"
  uv pip install -q --python "$CA/.venv/bin/python" -c "$CA/.venv/constraints.txt" -r "$ROOT/locks/cubeart.txt"
  layered() {   # dir, then the site-packages it reads too: like the image build, one .pth of layers
    local d="$1"; shift
    [ -x "$d/.venv/bin/python" ] || uv venv -q --python 3.13 --python-preference only-managed "$d/.venv"
    printf "%s
" "$@" > "$d/.venv/$SP/_layers.pth"
    cp "$CA/.venv/constraints.txt" "$d/.venv/constraints.txt"
  }
  echo "== img3d and sam3do venvs on the host"
  layered "$RT/img3d" "$CA/.venv/$SP"
  uv pip install -q --python "$RT/img3d/.venv/bin/python" -c "$CA/.venv/constraints.txt" -r "$ROOT/locks/img3d.txt"
  layered "$RT/sam3do" "$RT/img3d/.venv/$SP" "$CA/.venv/$SP"
  uv pip install -q --python "$RT/sam3do/.venv/bin/python" -c "$CA/.venv/constraints.txt" -r "$ROOT/locks/sam3do.txt"
  "$RT/sam3do/.venv/bin/python" -c "import pytorch3d" 2>/dev/null || FORCE_CUDA=0 MAX_JOBS=16 \
    uv pip install -q --python "$RT/sam3do/.venv/bin/python" -c "$CA/.venv/constraints.txt" --no-build-isolation \
    "git+https://github.com/facebookresearch/pytorch3d.git@75ebeeaea0908c5527e7b1e305fbc7681382db47"
  "$CA/.venv/bin/python" -c "import torch, transformers, diffusers, trimesh; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
  PYTHONPATH="$RT/hunyuan3d-2.1/hy3dshape" "$RT/img3d/.venv/bin/python" -c "import hy3dshape, timm, fast_simplification; print('img3d ok')"
  PYTHONPATH="$ROOT/workers/shims:$RT/sam3d-objects" LIDRA_SKIP_INIT=true "$RT/sam3do/.venv/bin/python" -c "import sam3d_objects.pipeline.inference_pipeline_pointmap, pytorch3d; print('sam3do ok')"
  echo "installed CubeArt and the image engines for CUDA in $RT (weights: $(readlink -f "$CA/weights"))"
  exit 0
fi
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

# ---- image engines (plan 17.1) ------------------------------------------------------------------
# Hunyuan3D 2.1 (shape) in runtime/hunyuan3d-2.1 with runtime/img3d/.venv layered on CubeArt's venv;
# SAM 3D Objects in runtime/sam3d-objects (+ DINOv2's code in runtime/sam3do/dinov2) with
# runtime/sam3do/.venv layered on img3d. spconv, gsplat, kaolin and open3d have no ROCm/cp313 build:
# the worker puts workers/shims/ first on its path instead. TRELLIS.2 and SAM 3D Body run in the
# comfy mod (packs trellis2-* and sam3d-body).
RT="$ROOT/runtime"
clone_at() {   # url dir commit
  if [ ! -d "$2/.git" ]; then
    echo "== $(basename "$2") → $2"
    git clone --quiet "$1" "$2"
  fi
  git -C "$2" checkout --quiet "$3"
}
clone_at https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git "$RT/hunyuan3d-2.1" 82920d643c0dc2f7bfd7255f45f62d386edfe60c
clone_at https://github.com/facebookresearch/sam-3d-objects.git "$RT/sam3d-objects" f91db411c50efee93d8db7aeb323885650f6f722
clone_at https://github.com/facebookresearch/dinov2.git "$RT/sam3do/dinov2" 7764ea0f912e53c92e82eb78a2a1631e92725fc8

echo "== img3d and sam3do venvs (inside $IMAGE)"
podman run --rm --security-opt label=disable -v "$RT:$RT" -v "$ROOT/locks:$ROOT/locks:ro" \
  -v "$ROOT/workers:$ROOT/workers:ro" -e PIP_CACHE_DIR="$CA/.cache/pip" "$IMAGE" bash -euc '
RT="$1"; LOCKS="$2"; SHIMS="$3"; SP=lib/python3.13/site-packages
venv() {   # dir, then the site-packages it is layered on
  local d="$1"; shift
  [ -x "$d/.venv/bin/python" ] || /usr/bin/python3.13 -m venv "$d/.venv"
  printf "%s\n" "$@" /opt/venv/$SP > "$d/.venv/$SP/_layers.pth"
  /opt/venv/bin/pip list --format=freeze 2>/dev/null | grep -iE "^(torch|torchvision|torchaudio|triton|numpy)==" > "$d/.venv/constraints.txt"
}
venv "$RT/img3d" "$RT/CubeArt/.venv/$SP"
"$RT/img3d/.venv/bin/pip" install --quiet -c "$RT/img3d/.venv/constraints.txt" -r "$LOCKS/img3d.txt"
venv "$RT/sam3do" "$RT/img3d/.venv/$SP" "$RT/CubeArt/.venv/$SP"
"$RT/sam3do/.venv/bin/pip" install --quiet -c "$RT/sam3do/.venv/constraints.txt" -r "$LOCKS/sam3do.txt"
"$RT/sam3do/.venv/bin/python" -c "import pytorch3d" 2>/dev/null || FORCE_CUDA=0 MAX_JOBS=16 \
  "$RT/sam3do/.venv/bin/pip" install --quiet -c "$RT/sam3do/.venv/constraints.txt" --no-build-isolation \
  "git+https://github.com/facebookresearch/pytorch3d.git@75ebeeaea0908c5527e7b1e305fbc7681382db47"
PYTHONPATH="$RT/hunyuan3d-2.1/hy3dshape" "$RT/img3d/.venv/bin/python" -c "import hy3dshape, timm, fast_simplification; print(\"img3d ok\")"
PYTHONPATH="$SHIMS:$RT/sam3d-objects" LIDRA_SKIP_INIT=true "$RT/sam3do/.venv/bin/python" -c "import sam3d_objects.pipeline.inference_pipeline_pointmap, pytorch3d; print(\"sam3do ok\")"
' _ "$RT" "$ROOT/locks" "$ROOT/workers/shims"
echo "installed the image engines in $RT"
