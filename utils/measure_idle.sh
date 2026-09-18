#!/usr/bin/env bash
# Measure lcppd's idle cost: time to first /api/health, RSS, and CPU over a window.
#
#   utils/measure_idle.sh              # against the running daemon on :7700
#   utils/measure_idle.sh --spawn      # start a throwaway daemon on :7790 first
#
# Budget: first answer < 1.5 s, RSS < 60 MB, ~0% CPU while idle.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=7700
WINDOW="${WINDOW:-30}"
SPAWNED=""

if [ "${1:-}" = "--spawn" ]; then
  PORT=7790
  STATE="$(mktemp -d)"
  start=$(date +%s.%N)
  LCPP_STATE_DIR="$STATE" "$ROOT/.venv/bin/python" -m lcpp.daemon --port "$PORT" &
  SPAWNED=$!
  trap 'kill $SPAWNED 2>/dev/null; rm -rf "$STATE"' EXIT
  until curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; do sleep 0.02; done
  echo "startup: $(echo "$(date +%s.%N) - $start" | bc | cut -c1-5) s to first /api/health"
fi

PID="${SPAWNED:-$(systemctl --user show -p MainPID --value lcpp.service 2>/dev/null || true)}"
[ -n "$PID" ] && [ "$PID" != "0" ] || { echo "no daemon pid found"; exit 1; }

rss_kb=$(awk '/VmRSS/ {print $2}' "/proc/$PID/status")
echo "rss: $((rss_kb / 1024)) MB"

ticks() { awk '{print $14 + $15}' "/proc/$PID/stat"; }
t0=$(ticks); sleep "$WINDOW"; t1=$(ticks)
hz=$(getconf CLK_TCK)
echo "cpu: $(echo "scale=3; ($t1 - $t0) / $hz / $WINDOW * 100" | bc)% over ${WINDOW}s idle"
