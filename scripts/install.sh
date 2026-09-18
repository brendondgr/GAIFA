#!/usr/bin/env bash
# Install lcpp on this machine. Idempotent: safe to re-run after pulling.
#
#   1. uv sync                          project venv (the daemon runs from it)
#   2. uv tool install --editable .     the `lcpp` command in ~/.local/bin
#   3. lcpp service install             lcppd as an at-boot systemd user unit
#   4. retire the legacy setup          llamacpp-* symlinks + llamacpp-router.service
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> venv"
uv sync -q
echo "==> lcpp command"
uv tool install -q --editable . --force
LCPP="$HOME/.local/bin/lcpp"
echo "==> service"
"$LCPP" service install

echo "==> legacy cleanup"
for name in llamacpp-start llamacpp-stop llamacpp-restart llamacpp-status llamacpp-logs llamacpp-models; do
  link="$HOME/.local/bin/$name"
  if [ -L "$link" ] || [ -e "$link" ]; then rm -f "$link"; echo "removed $link"; fi
done
LEGACY="$HOME/.config/systemd/user/llamacpp-router.service"
if [ -f "$LEGACY" ]; then
  systemctl --user disable --now llamacpp-router.service || true
  rm -f "$LEGACY"
  systemctl --user daemon-reload
  echo "removed llamacpp-router.service (use: lcpp start --router --port 7070)"
fi

for _ in $(seq 50); do "$LCPP" status >/dev/null 2>&1 && break; sleep 0.1; done
"$LCPP" status
