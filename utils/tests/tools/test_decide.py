"""25.1: every risk in every mode, with and without list entries and grants, in the fixed order
deny list → (a mod's limits, plan 27.4) → thread mode → grants → ask/allow lists → risk default."""

from __future__ import annotations

import pytest

from utils import config
from utils.tools.approvals import MODES, decide
from utils.tools.catalog import RISKS

# The risk default, per mode (no list entry, no grant, no mod limits). Auto sends `network` to the
# judge (plan Phase 30), which asks until it exists.
DEFAULT = {
    "read":        {"plan": "allow", "manual": "allow", "accept_edits": "allow", "auto": "allow", "bypass": "allow"},
    "write":       {"plan": "deny",  "manual": "ask",   "accept_edits": "allow", "auto": "allow", "bypass": "allow"},
    "generate":    {"plan": "deny",  "manual": "ask",   "accept_edits": "allow", "auto": "allow", "bypass": "allow"},
    "network":     {"plan": "deny",  "manual": "ask",   "accept_edits": "ask",   "auto": "judge", "bypass": "ask"},
    "execute":     {"plan": "deny",  "manual": "ask",   "accept_edits": "ask",   "auto": "ask",   "bypass": "ask"},
    "destructive": {"plan": "deny",  "manual": "ask",   "accept_edits": "ask",   "auto": "ask",   "bypass": "ask"},
}
GRANT = {"id": "gr_1", "tool": "x_tool", "key": "github.com", "scope": "thread"}


def cfg(deny=(), ask=(), allow=()) -> config.Config:
    c = config.Config()
    c.agent.permissions.deny, c.agent.permissions.ask, c.agent.permissions.allow = list(deny), list(ask), list(allow)
    return c


def test_the_table_covers_every_risk_and_mode():
    assert set(DEFAULT) == set(RISKS) and all(set(v) == set(MODES) for v in DEFAULT.values())


@pytest.mark.parametrize("risk", RISKS)
@pytest.mark.parametrize("mode", MODES)
def test_risk_default(risk, mode):
    assert decide("x_tool", risk, cfg(), mode)[0] == DEFAULT[risk][mode]


@pytest.mark.parametrize("risk", RISKS)
@pytest.mark.parametrize("mode", MODES)
def test_deny_list_wins_over_everything(risk, mode):
    verdict, why = decide("x_tool", risk, cfg(deny=["x_*"], ask=["x_*"], allow=["x_*"]), mode, GRANT)
    assert verdict == "deny" and "permissions" in why


@pytest.mark.parametrize("risk", RISKS)
@pytest.mark.parametrize("mode", MODES)
def test_ask_list(risk, mode):
    want = "deny" if mode == "plan" and risk != "read" else "ask"   # the mode comes before the lists
    assert decide("x_tool", risk, cfg(ask=["x_tool"]), mode)[0] == want


@pytest.mark.parametrize("risk", RISKS)
@pytest.mark.parametrize("mode", MODES)
def test_allow_list(risk, mode):
    if mode == "plan" and risk != "read":
        want = "deny"
    elif risk == "execute":
        want = "ask"          # only a grant skips an execute card
    else:
        want = "allow"
    assert decide("x_tool", risk, cfg(allow=["x_*"]), mode)[0] == want


@pytest.mark.parametrize("risk", RISKS)
@pytest.mark.parametrize("mode", MODES)
def test_a_grant_allows_unless_denied_or_plan(risk, mode):
    verdict, why = decide("x_tool", risk, cfg(ask=["x_tool"]), mode, GRANT)   # a grant beats the ask list
    if mode == "plan" and risk != "read":
        assert verdict == "deny"
    else:
        assert verdict == "allow" and why == "allowed in this chat for github.com"


def test_grant_reasons():
    assert decide("x", "execute", cfg(), "auto", {"scope": "always", "key": None})[1] == "always allowed"
    assert decide("x", "network", cfg(), "manual", {"scope": "always", "key": "search"})[1] == "always allowed for search"


def test_ask_beats_allow_and_reasons_name_the_rule():
    c = cfg(ask=["x_*"], allow=["x_*"])
    assert decide("x_tool", "generate", c) == ("ask", "your permissions ask for this tool")
    assert decide("x_tool", "network", cfg()) == ("ask", "network tools ask first")
    assert decide("x_tool", "execute", cfg(), "auto") == ("ask", "execute tools ask first")
    assert decide("x_tool", "generate", cfg(), "accept_edits")[1].startswith("Accept edits")
    assert decide("x_tool", "network", cfg(), "auto") == ("judge", "Auto: the judge decides")


async def test_a_mod_declares_network_and_execute_tools(ph):
    tools = {t["name"]: t for t in (await ph.client.get("/api/tools/index")).json() if t["mod"] == "fake-perms"}
    assert {k: v["risk"] for k, v in tools.items()} == {
        "fake_perms_search": "network", "fake_perms_fetch": "network", "fake_perms_python": "execute",
        "fake_perms_run": "execute", "fake_perms_wipe": "destructive"}
    for mode in ("manual", "accept_edits", "auto"):    # network and execute ask in these modes (auto: the judge asks)
        r = await ph.call("fake_perms_fetch", {"url": "https://github.com/x"}, mode=mode)
        assert r["status"] == "needs_approval" and r["risk"] == "network"
        r = await ph.call("fake_perms_python", {"code": "print(1)"}, mode=mode)
        assert r["status"] == "needs_approval" and r["risk"] == "execute"
    r = await ph.call("fake_perms_python", {"code": "print(1)"}, mode="plan")
    assert r["status"] == "denied"


async def test_mcp_annotations_follow_the_risk(ph):
    r = await ph.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             headers={"accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18"})
    ann = {t["name"]: t["annotations"] for t in r.json()["result"]["tools"]}
    assert ann["fake_perms_fetch"]["openWorldHint"] is True and ann["fake_perms_fetch"]["destructiveHint"] is False
    assert ann["fake_perms_python"]["destructiveHint"] is True and ann["fake_perms_python"]["readOnlyHint"] is False
