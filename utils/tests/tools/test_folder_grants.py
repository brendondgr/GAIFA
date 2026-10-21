"""Plan 34: a read in a folder outside the chat's environment becomes a card ("Let this chat read …?"), not a
refusal; Allow for this chat writes a folder grant the hub passes to the mod as `origin.folders`; Allow once
covers one call; Deny, Always and forged origins don't open the folder. Against `fake-ws`."""

from __future__ import annotations

from utils.tools.approvals import MODES

MYC = "/home/u/Agents/Mycelium"


async def ask(wh, thread="t1", mode="manual", **o):
    return await wh.call("fake_ws_read", {"folder": MYC, "path": "core/net.py"}, mode=mode, thread=thread, service="agent", **o)


async def decide(wh, aid, **body):
    return await wh.client.post(f"/api/approvals/{aid}?wait=10", json={"approve": True, **body})


async def test_a_folder_outside_the_environment_asks_in_every_mode(wh):
    for mode in MODES:
        r = await ask(wh, mode=mode, environment="grants")
        assert r["status"] == "needs_approval", (mode, r)
        lim = r["limits"]
        assert lim["ask_folder"] == {"path": MYC, "level": "read", "environment": {"id": "grants", "name": "Grants"}}
        assert lim["key"] == f"folder:{MYC}" and lim["action"] == "read" and "isn't one of this chat's folders" in r["why"]
    a = await wh.client.get(f"/api/approvals/{r['approval_id']}")
    assert a.json()["origin"]["ask_folder"]["path"] == MYC          # the Approvals popover reads it from the origin


async def test_allow_for_this_chat_opens_the_folder_in_that_chat_only(wh):
    r = await ask(wh)
    d = await decide(wh, r["approval_id"], remember="thread")
    assert d.status_code == 200, d.text
    out = d.json()
    assert out["status"] == "done" and out["result"]["folders"] == [MYC]
    g = out["grant"]
    assert (g["tool"], g["key"], g["kind"], g["scope"], g["thread"], g["risk"]) == ("fake_ws_*", f"folder:{MYC}", "folder", "thread", "t1", "read")
    again = await ask(wh)
    assert again["status"] == "done" and again["result"]["folders"] == [MYC]      # no card: the hub passed it
    assert (await ask(wh, thread="t2"))["status"] == "needs_approval"             # another chat asks again
    edit = await wh.call("fake_ws_edit", {"folder": MYC, "path": "a", "old": "x", "new": "y"}, mode="bypass", thread="t1")
    assert edit["status"] == "denied" and edit["error"]["code"] == "level"         # allowed at Read only
    await wh.hub.grants.revoke(g["id"])
    assert (await ask(wh))["status"] == "needs_approval"                           # revoked: it asks again


async def test_allow_once_covers_one_call(wh):
    r = await ask(wh)
    d = await decide(wh, r["approval_id"])
    assert d.status_code == 200 and d.json()["status"] == "done" and d.json()["result"]["folders"] == [MYC]
    assert "grant" not in d.json()
    assert (await ask(wh))["status"] == "needs_approval"


async def test_always_and_deny_dont_open_it(wh):
    r = await ask(wh)
    bad = await decide(wh, r["approval_id"], remember="always", confirm=True)
    assert bad.status_code == 422 and bad.json()["code"] == "folder_always"
    no = await wh.client.post(f"/api/approvals/{r['approval_id']}", json={"approve": False, "reason": "not that one"})
    assert no.status_code == 200 and no.json()["status"] == "denied" and "don't run it again" in no.json()["error"]["fix"]
    assert await wh.hub.grants.list(thread="t1") == []
    assert (await ask(wh))["status"] == "needs_approval"


async def test_a_callers_own_folders_are_dropped(wh):
    r = await ask(wh, thread="t3", folders=[{"path": MYC, "level": "run_net"}])
    assert r["status"] == "needs_approval"
    direct = await wh.call("fake_ws_read", {"folder": MYC, "path": "x"}, mode="bypass", folders=[{"path": MYC}])
    assert direct["status"] == "needs_approval"                                    # no chat: nothing allowed


async def test_folders_never_asked_for_are_refused(wh):
    r = await wh.call("fake_ws_read", {"folder": "/etc", "path": "passwd"}, mode="bypass", thread="t1")
    assert r["status"] == "denied" and r["error"]["code"] == "not_grantable"
