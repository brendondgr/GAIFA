#!/usr/bin/env bash
# End-to-end check against the real services: lcppd (:7700), the relay
# (:4000) and real llama-server processes. Touches only its own instances
# (ports 7181/7182), so a router or anything else you have running is left alone.
#
#   utils/e2e_live.sh
set -euo pipefail

RELAY="${RELAY:-http://127.0.0.1:4000}"
A=7181 B=7182
pass() { printf '  \033[32mok\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
cleanup() { lcpp stop "$A" >/dev/null 2>&1 || true; lcpp stop "$B" >/dev/null 2>&1 || true; }
trap cleanup EXIT

regs() { curl -sf "$RELAY/admin/registrations?owner=lcpp" | python3 -c 'import json,sys; print(" ".join(r["key"] for r in json.load(sys.stdin)))'; }
chat() {  # chat <model-name-on-relay> -> prints the model that answered
  curl -sf "$RELAY/v1/chat/completions" -H 'content-type: application/json' \
    -d "{\"model\":\"$1\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])'
}

echo "== daemon"
curl -sf http://127.0.0.1:7700/api/health >/dev/null && pass "lcppd answers on :7700" || fail "lcppd is not running (lcpp service start)"
systemctl --user is-enabled lcpp.service >/dev/null && pass "lcpp.service enabled at boot" || fail "lcpp.service not enabled"
curl -sf "$RELAY/health" >/dev/null && pass "relay answers on $RELAY" || fail "relay is not running"

echo "== launch two instances on chosen ports"
lcpp start minicpm --port "$A" --name e2e-mini >/dev/null && pass "minicpm on :$A"
lcpp start gemma4-E4B --port "$B" --name e2e-e4b --alias e2e-e4b >/dev/null && pass "gemma4-E4B on :$B"
lcpp status | grep -q "e2e-mini .*registered" && lcpp status | grep -q "e2e-e4b .*registered" \
  && pass "both registered with the relay" || fail "not registered: $(lcpp status)"

echo "== routing through the relay"
[ "$(chat MiniCPM5-2B)" = "MiniCPM5-2B" ] && pass "model name MiniCPM5-2B -> :$A" || fail "MiniCPM5-2B misrouted"
[ -n "$(chat e2e-e4b)" ] && pass "alias e2e-e4b -> :$B" || fail "alias e2e-e4b did not route"

echo "== daemon restart keeps instances and registrations"
systemctl --user restart lcpp.service
until curl -sf http://127.0.0.1:7700/api/health >/dev/null; do sleep 0.1; done
lcpp status | grep -q "e2e-mini .*ready\|e2e-mini  *$A" && pass "instances survived the restart" || fail "instances lost: $(lcpp status)"
case " $(regs) " in *" lcpp:$A "*) pass "registration lcpp:$A intact" ;; *) fail "lcpp:$A missing after restart" ;; esac
[ "$(chat MiniCPM5-2B)" = "MiniCPM5-2B" ] && pass "still routes after restart" || fail "routing broke after restart"

echo "== stop"
lcpp stop "$A" --wait >/dev/null && lcpp stop "$B" --wait >/dev/null && pass "both stopped"
case " $(regs) " in *" lcpp:$A "*|*" lcpp:$B "*) fail "stale registrations: $(regs)" ;; *) pass "relay has no stale registrations" ;; esac
for p in $A $B; do
  systemctl --user show -p LoadState --value "lcpp-e2e-$([ "$p" = "$A" ] && echo mini || echo e4b).service" | grep -q not-found \
    && pass "unit for :$p is gone" || fail "unit for :$p still loaded"
done
echo "all checks passed"
