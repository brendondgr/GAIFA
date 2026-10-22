#!/usr/bin/env bash
# Builds .venv/ for this mod. Run by `aihub new`; run it again after changing requirements.txt.
#   --accel <rocm|cuda|xpu|mps|vulkan|cpu>   the variant (default: $AIHUB_ACCEL, else cpu); plan 38.4
# A mod that uses PyTorch lists it in requirements-torch.txt: it's installed from the index for that accel.
set -euo pipefail
cd "$(dirname "$0")"
ACCEL="${AIHUB_ACCEL:-cpu}"
while [ $# -gt 0 ]; do
  case "$1" in
    --accel) ACCEL="$2"; shift 2 ;;
    *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
  esac
done
if command -v uv >/dev/null 2>&1; then
  # uv-managed Python lives in your home folder, so the venv works both on the host and in a toolbox.
  uv venv --quiet --python-preference only-managed .venv
  pip_install() { uv pip install --quiet --python .venv/bin/python "$@"; }
else
  python3 -m venv .venv
  pip_install() { .venv/bin/pip install --quiet "$@"; }
fi
pip_install -r requirements.txt
if [ -f requirements-torch.txt ]; then
  pip_install --index-url "$(.venv/bin/python torch_index.py "$ACCEL")" -r requirements-torch.txt
fi
echo "installed $(basename "$PWD") into .venv ($ACCEL)"
