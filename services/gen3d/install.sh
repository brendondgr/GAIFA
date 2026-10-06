#!/usr/bin/env bash
# Install 3DGenerate: the API server venv, the `gen3d` command, and a service that starts at boot
# (systemd user unit). Re-run any time; it is idempotent.
#
#   ./install.sh                 # server + command + boot service
#   ./install.sh --no-service    # no boot service (run it with `gen3d start`)
#
# The models themselves (Cube3D, CubePart code and the container's venv) are set up in
# runtime/CubeArt (GEN3D_CUBEART) by scripts/install-runtime.sh; this only checks they are there.
set -euo pipefail
if [ -z "${GEN3D_NO_HOST:-}" ] && { [ -e /run/.toolboxenv ] || [ -e /run/.containerenv ]; }; then
  if command -v flatpak-spawn >/dev/null 2>&1; then exec flatpak-spawn --host bash "$(readlink -f "$0")" "$@"
  elif command -v distrobox-host-exec >/dev/null 2>&1; then exec distrobox-host-exec bash "$(readlink -f "$0")" "$@"; fi
fi
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CONF_DIR="$HOME/.config/gen3d"
SERVICE=1
for a in "$@"; do
  case "$a" in
    --no-service) SERVICE=0 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
command -v uv >/dev/null || { echo "uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

echo "== server venv ($ROOT/.venv)"
[[ -x "$ROOT/.venv/bin/python" ]] || uv venv -q "$ROOT/.venv" --python 3.12
uv pip install -q --python "$ROOT/.venv/bin/python" -r "$ROOT/requirements.txt"
PY="$ROOT/.venv/bin/python"

echo "== config"
mkdir -p "$CONF_DIR"
[[ -f "$CONF_DIR/gen3d.env" ]] || cp "$ROOT/gen3d.env.example" "$CONF_DIR/gen3d.env"
echo "  $CONF_DIR/gen3d.env"

echo "== models"
(cd "$ROOT" && "$PY" -m gen3d.doctor) || echo "  some pieces are missing; the UI will say which"

echo "== command"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bin/gen3d" "$HOME/.local/bin/gen3d"
echo "  $HOME/.local/bin/gen3d"

echo "== desktop launcher"
"$ROOT/bin/gen3d" launcher

[[ "$SERVICE" == 1 ]] && "$ROOT/bin/gen3d" enable
"$ROOT/bin/gen3d" restart
