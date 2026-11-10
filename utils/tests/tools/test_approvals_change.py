"""calendar 4.1: the `change` action a mod's preflight may answer (the calendar's writes): refused in Plan, asks in
Manual and Accept edits, the judge in Auto, runs in Bypass; a grant and the allow list still allow it, the ask
list still asks; and the calendar's own items it made in this chat come as `edit`."""

from __future__ import annotations

from utils import config
from utils.tools.approvals import ACTION_WORD, ACTIONS, CELLS, MODES, decide

WANT = {"plan": "deny", "manual": "ask", "accept_edits": "ask", "auto": "judge", "bypass": "allow"}
LIM = {"action": "change", "allow_bypass": True}


def cfg(**lists) -> config.Config:
    c = config.Config()
    for k, v in lists.items():
        setattr(c.agent.permissions, k, list(v))
    return c


def test_the_change_column():
    assert "change" in ACTIONS and ACTION_WORD["change"]
    for m in MODES:
        assert CELLS[m]["change"] == WANT[m], m
        assert decide("calendar_add", "write", cfg(), m, limits=LIM)[0] == WANT[m], m


def test_grants_and_lists():
    grant = {"scope": "thread", "key": None, "tool": "calendar_add"}
    assert decide("calendar_add", "write", cfg(), "manual", grant=grant, limits=LIM) == ("allow", "allowed in this chat")
    assert decide("calendar_add", "write", cfg(allow=["calendar_*"]), "accept_edits", limits=LIM)[0] == "allow"
    assert decide("calendar_add", "write", cfg(ask=["calendar_add"]), "auto", limits=LIM)[0] == "ask"
    assert decide("calendar_add", "write", cfg(deny=["calendar_*"]), "bypass", limits=LIM)[0] == "deny"


def test_its_own_items_as_edits():
    own = {"action": "edit", "allow_bypass": True}
    got = {m: decide("calendar_delete", "write", cfg(), m, limits=own)[0] for m in MODES}
    assert got == {"plan": "deny", "manual": "ask", "accept_edits": "allow", "auto": "allow", "bypass": "allow"}


def test_a_refusal_ends_it():
    lim = {"action": "change", "refuse": {"code": "not_found", "detail": "there's no calendar item 'c_x'"}}
    assert decide("calendar_update", "write", cfg(), "bypass", limits=lim)[0] == "deny"
