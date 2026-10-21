"""27.4: the chat modes with a workspace mod's limits, cell by cell against `fake-ws`:
levels × modes × kinds of call, the old mode names, Bypass where a folder doesn't allow it,
calls that ask every time, the mod's grant key, refusals, and the judge's seam."""

from __future__ import annotations

import pytest

from utils import config
from utils.tools import approvals
from utils.tools.approvals import CELLS, MODES, canonical, decide

LEVELS = ("read", "edit", "run", "run_net")
NEEDS = {"read": "read", "edit": "edit", "delete": "edit", "commit": "edit", "command": "run", "network": "run_net",
         "host": "run", "remote": "run_net"}

# The plan's table (Phase 27), written out again so the code's CELLS is checked against it.
TABLE = {  # action: plan, manual, accept_edits, auto, bypass
    "read":    ("run", "run", "run", "run", "run"),
    "edit":    ("refused", "ask", "run", "run", "run"),
    "command": ("refused", "ask", "ask", "ask", "run"),       # auto: the judge decides (no model in tests: it asks)
    "network": ("refused", "ask", "ask", "ask", "run"),
    "host":    ("refused", "ask", "ask", "ask", "ask"),
}
STATUS = {"run": "done", "ask": "needs_approval", "refused": "denied"}

CALLS = {   # action → (tool, arguments without the folder)
    "read": ("read", {"path": "a.py"}),
    "edit": ("edit", {"path": "a.py", "old": "x", "new": "y"}),
    "delete": ("delete", {"path": "a.py"}),
    "commit": ("commit", {"message": "m"}),
    "command": ("run", {"command": "pytest -q"}),
    "network": ("run", {"command": "pip install six", "network": True}),
    "host": ("run", {"command": "make", "where": "host"}),
    "remote": ("run", {"command": "git push origin main", "network": True}),
}


def cfg(**lists) -> config.Config:
    c = config.Config()
    for k, v in lists.items():
        setattr(c.agent.permissions, k, list(v))
    return c


def test_cells_match_the_plans_table():
    for action, row in TABLE.items():
        for mode, want in zip(MODES, row):
            got = CELLS[mode][action]
            assert {"allow": "run", "deny": "refused", "ask": "ask", "judge": "ask"}[got] == want, (mode, action)
    assert CELLS["auto"]["command"] == CELLS["auto"]["network"] == "judge"
    assert all(CELLS[m]["host"] != "allow" and CELLS[m]["remote"] != "allow" for m in MODES)


def test_old_names_map_over():
    assert canonical("ask") == "manual" and canonical("read_only") == "plan" and canonical("auto") == "auto"
    assert canonical("bypass") == "bypass" and canonical("nonsense") == "manual" and canonical(None) == "manual"


@pytest.mark.parametrize("bypass", [False, True])
async def test_levels_x_modes_x_kinds(wh, bypass):
    """Every cell: the folder's level caps (denied with code "level"), then the mode decides."""
    for level in LEVELS:
        folder = level + ("-bypass" if bypass else "")
        for mode in MODES:
            for action, (tool, args) in CALLS.items():
                r = await wh.call(f"fake_ws_{tool}", {"folder": folder, **args}, mode=mode, thread="t1")
                if LEVELS.index(level) < LEVELS.index(NEEDS[action]):
                    assert r["status"] == "denied" and r["error"]["code"] == "level", (level, mode, action, r)
                    continue
                eff = "accept_edits" if mode == "bypass" and not bypass else mode
                cell = CELLS[eff][action]
                want = {"allow": "done", "deny": "denied", "ask": "needs_approval", "judge": "needs_approval"}[cell]
                assert r["status"] == want, (level, mode, action, r)
                if want == "done":
                    assert r["result"]["ran"] == tool
                if want == "needs_approval":
                    lim = r["limits"]
                    assert lim["action"] == action and lim["folder"] == folder and lim["level"] == level
                    assert lim["once"] == (action in ("host", "remote", "commit"))
                    if action in ("edit", "delete"):
                        assert lim["preview"]["diff"].startswith("--- a/a.py")


async def test_old_mode_names_through_the_api(wh):
    assert (await wh.call("fake_ws_edit", {"folder": "edit", "path": "a"}, mode="read_only"))["status"] == "denied"
    assert (await wh.call("fake_ws_edit", {"folder": "edit", "path": "a"}, mode="ask"))["status"] == "needs_approval"
    assert (await wh.call("fake_ws_edit", {"folder": "edit", "path": "a"}, mode="auto"))["status"] == "done"


async def test_bypass_is_refused_where_not_allowed(wh):
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="bypass")
    assert r["status"] == "needs_approval" and "Bypass isn't allowed" in r["why"]
    r = await wh.call("fake_ws_run", {"folder": "run-bypass", "command": "pytest"}, mode="bypass")
    assert r["status"] == "done"
    r = await wh.call("fake_ws_run", {"folder": "run-bypass", "command": "make", "where": "host"}, mode="bypass")
    assert r["status"] == "needs_approval" and r["limits"]["once"]          # a host run asks even in Bypass


async def test_hard_limits_refuse_in_every_mode(wh):
    for mode in MODES:
        r = await wh.call("fake_ws_run", {"folder": "run_net-bypass", "command": "sudo rm -rf /"}, mode=mode)
        assert r["status"] == "denied" and r["error"]["code"] == "sudo", mode
        r = await wh.call("fake_ws_read", {"folder": "nope", "path": "x"}, mode=mode)
        assert r["status"] == "denied" and r["error"]["code"] == "unknown_folder"


async def test_allow_a_command_in_this_chat_covers_that_command_in_that_folder(wh):
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest -q"}, mode="manual", thread="t1", service="agent")
    assert r["status"] == "needs_approval" and r["limits"]["key"] == "run pytest"
    d = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "remember": "thread"})
    assert d.status_code == 200 and d.json()["grant"]["key"] == "run pytest"
    again = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest tests/test_x.py"}, mode="manual", thread="t1")
    assert again["status"] == "done"
    assert (await wh.call("fake_ws_run", {"folder": "run", "command": "ls"}, mode="manual", thread="t1"))["status"] == "needs_approval"
    assert (await wh.call("fake_ws_run", {"folder": "run_net", "command": "pytest"}, mode="manual", thread="t1"))["status"] == "needs_approval"
    assert (await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="manual", thread="t2"))["status"] == "needs_approval"
    assert (await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="plan", thread="t1"))["status"] == "denied"


async def test_once_only_calls_cannot_be_remembered_and_grants_dont_cover_them(wh):
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "make", "where": "host"}, mode="manual", thread="t1")
    bad = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "remember": "thread"})
    assert bad.status_code == 422 and bad.json()["code"] == "once_only"
    await wh.hub.grants.add("fake_ws_run", "run make", "always")
    r2 = await wh.call("fake_ws_run", {"folder": "run", "command": "make", "where": "host"}, mode="manual", thread="t1")
    assert r2["status"] == "needs_approval"
    ok = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True})
    assert ok.status_code == 200 and ok.json()["status"] == "done"


async def test_edited_arguments_are_checked_again(wh):
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="manual")
    bad = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10",
                               json={"approve": True, "arguments": {"folder": "run", "command": "sudo pytest"}})
    assert bad.status_code == 403 and bad.json()["code"] == "sudo"
    bad = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10",
                               json={"approve": True, "arguments": {"folder": "read", "command": "pytest"}})
    assert bad.status_code == 403 and bad.json()["code"] == "level"


async def test_lists_still_apply_with_limits(wh):
    wh.hub.config.agent.permissions.ask = ["fake_ws_edit"]
    try:
        assert (await wh.call("fake_ws_edit", {"folder": "edit", "path": "a"}, mode="accept_edits"))["status"] == "needs_approval"
    finally:
        wh.hub.config.agent.permissions.ask = []
    wh.hub.config.agent.permissions.deny = ["fake_ws_*"]
    try:
        assert (await wh.call("fake_ws_read", {"folder": "read", "path": "a"}, mode="bypass"))["status"] == "denied"
    finally:
        wh.hub.config.agent.permissions.deny = []


async def test_the_judges_seam(wh, monkeypatch):
    seen = {}

    async def fake_judge(hub, tool, arguments, origin, limits, why):
        seen.update(tool=tool.name, action=limits["action"], why=why)
        return "allow", "Auto: ran (judged safe: a test runner)", {"verdict": "allow", "reason": "a test runner"}

    monkeypatch.setattr(approvals, "judge", fake_judge)
    monkeypatch.setattr("utils.tools.calls.judge", fake_judge)
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="auto")
    assert r["status"] == "done" and seen == {"tool": "fake_ws_run", "action": "command", "why": "Auto: the judge decides"}
    assert r["judge"]["why"] == "Auto: ran (judged safe: a test runner)"
    seen.clear()
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "make", "where": "host"}, mode="auto")
    assert r["status"] == "needs_approval" and seen == {}                  # host runs never reach the judge


async def test_the_judge_fails_closed_by_default(wh):
    verdict, why, record = await approvals.judge(None, None, {}, None, None, "")     # no hub: it can't judge, so it asks
    assert verdict == "ask" and why.startswith("Auto: asked you (the judge failed") and record["source"] == "fail-closed"


async def test_a_preflight_that_fails_refuses(wh):
    for t in await wh.hub.tools.tools():
        if t.mod == "fake-ws":
            t.limits = "POST /v1/no-such-route"
    r = await wh.call("fake_ws_read", {"folder": "read", "path": "a"}, mode="bypass")
    assert r["status"] == "denied" and r["error"]["code"] == "limits_unavailable", r


def test_decide_with_limits_unit():
    lim = {"action": "edit", "allow_bypass": False}
    assert decide("w_edit", "write", cfg(), "plan", None, lim)[0] == "deny"
    assert decide("w_edit", "write", cfg(), "manual", None, lim)[0] == "ask"
    assert decide("w_edit", "write", cfg(), "accept_edits", None, lim)[0] == "allow"
    assert decide("w_edit", "write", cfg(), "manual", {"scope": "thread", "key": "f"}, lim)[0] == "allow"
    assert decide("w_edit", "write", cfg(), "manual", None, {**lim, "refuse": {"detail": "no"}}) == ("deny", "no")
    assert decide("w_run", "execute", cfg(allow=["w_*"]), "manual", None, {"action": "command"})[0] == "ask"
    assert decide("w_commit", "write", cfg(), "manual", {"scope": "always"}, {"action": "commit", "once": True})[0] == "ask"
    assert decide("w_run", "execute", cfg(), "auto", None, {"action": "command"})[0] == "judge"
    # a compound command is `once` (no grant covers it), but in Auto the judge still reads each part (2026-10-21)
    once = {"action": "command", "once": True}
    assert decide("w_run", "execute", cfg(), "auto", None, once)[0] == "judge"
    assert decide("w_run", "execute", cfg(), "auto", {"scope": "always"}, once)[0] == "judge"   # never the grant
    assert decide("w_run", "execute", cfg(), "manual", None, once)[0] == "ask"
    assert decide("w_run", "execute", cfg(ask=["w_run"]), "auto", None, once)[0] == "ask"
    assert decide("w_run", "execute", cfg(), "auto", None, {"action": "host", "once": True})[0] == "ask"
