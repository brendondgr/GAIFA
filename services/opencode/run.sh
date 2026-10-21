#!/usr/bin/env bash
# AIHub runs this as the opencode mod (service.toml). It was DashLLM's scripts/opencode-serve.sh.
#
# A wrapper rather than a bare ExecStart because systemd cannot expand
# variables in WorkingDirectory= or resolve `opencode` on its minimal PATH, and
# the project directory + port both live in .env. Sourcing .env here also keeps
# one config mechanism instead of two (this script and EnvironmentFile
# disagreeing about quoting would be a bad afternoon).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

# opencode installs to ~/.opencode/bin, which is not on a systemd user unit's
# default PATH.
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"

if ! command -v opencode >/dev/null; then
  echo "opencode is not on PATH (looked in ~/.opencode/bin)" >&2
  exit 127
fi

if [ "${OPENCODE_ENABLED:-1}" != "1" ]; then
  echo "OPENCODE_ENABLED is not 1 in $ROOT/.env; not starting" >&2
  exit 0
fi

# Load or mint the Basic credentials. Never served unauthenticated: this
# process runs shell commands in OPENCODE_PROJECT_DIR for anyone who reaches
# the port. relay reads the same file, so the two agree without configuration.
# shellcheck disable=SC1091
. "$ROOT/auth.sh"

# The folder OpenCode's shell, edit and write tools act in: one the person chose, outside AIHub
# (plan 23.14). Unset used to mean this folder, which put an agent's shell inside AIHub.
AIHUB="$(cd "$ROOT/../.." && pwd -P)"
how="set OPENCODE_PROJECT_DIR to a folder outside AIHub: aihub setup opencode asks for it, or [services.opencode.env] in config.toml (a line in $ROOT/.env wins over it), then aihub restart opencode"
if [ -z "${OPENCODE_PROJECT_DIR:-}" ]; then
  echo "OPENCODE_PROJECT_DIR is not set, so there's no folder for OpenCode to work in; $how" >&2
  exit 1
fi
PROJECT_DIR="$OPENCODE_PROJECT_DIR"
[ -d "$PROJECT_DIR" ] || { echo "OPENCODE_PROJECT_DIR does not exist: $PROJECT_DIR" >&2; exit 78; }
REAL="$(cd "$PROJECT_DIR" && pwd -P)"
case "$REAL/" in
  "$AIHUB"/*) echo "OPENCODE_PROJECT_DIR is inside AIHub ($REAL), which stays read-only to agents; $how" >&2; exit 1 ;;
esac

cd "$PROJECT_DIR"
echo "opencode serve --port ${OPENCODE_PORT:-4096} in $PROJECT_DIR"
exec opencode serve --port "${OPENCODE_PORT:-4096}"
