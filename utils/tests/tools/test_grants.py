"""25.2: grants. Keys from arguments, thread vs always, expiry, revoke, a grant for one domain not
covering another, the second confirm for execute and destructive, and MCP calls (no thread: only
`always` grants apply), against fake-perms."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from utils.manifest import ToolSpec
from utils.tests.tools.test_mcp import call as mcp_call
from utils.tools.grants import key_of, problems

FETCH, RUN, PY, SEARCH, WIPE = "fake_perms_fetch", "fake_perms_run", "fake_perms_python", "fake_perms_search", "fake_perms_wipe"
SHIPPED = "gr_default_web_search"   # migration 010 (plan 26.2): in every database; test_shipped_grant covers it


def made(grants: list[dict]) -> list[dict]:
    """The grants a test made: without the one AIHub ships."""
    return [g for g in grants if g["id"] != SHIPPED]


def test_keys_from_arguments():
    assert key_of("url:host", {"url": "https://GitHub.com:443/a/b?c"}) == "github.com"
    assert key_of("url:host", {"url": "https://api.github.com/x"}) == "api.github.com"
    assert key_of("url:host", {"url": "not a url"}) is None and key_of("url:host", {}) is None
    assert key_of("url:host", {"url": "http://[::1"}) is None              # a broken URL reads as no key
    assert key_of("arg:folder", {"folder": "~/Projects/foo"}) == "~/Projects/foo"
    assert key_of("arg:folder", {"folder": ""}) is None and key_of("arg:n", {"n": 3}) == "3"
    assert key_of("const:search", {}) == "search" and key_of(None, {"url": "https://x.org"}) is None


def test_grant_key_is_checked_in_the_manifest_and_against_the_parameters():
    assert ToolSpec(op="POST /v1/x", grant_key="arg:folder").grant_key == "arg:folder"
    for bad in ("host", "url:path", "arg:", "const:two words"):
        with pytest.raises(ValidationError):
            ToolSpec(op="POST /v1/x", grant_key=bad)
    params = {"properties": {"folder": {}, "code": {}}}
    assert problems("arg:folder", params) == [] and problems("const:x", params) == []
    assert "isn't a parameter" in problems("arg:path", params)[0] and "url" in problems("url:host", params)[0]


async def approve(ph, r: dict, status: int = 200, **body) -> dict:
    resp = await ph.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, **body})
    assert resp.status_code == status, resp.text
    return resp.json()


async def test_allow_in_this_chat_covers_that_domain_in_that_chat_only(ph):
    r = await ph.call(FETCH, {"url": "https://github.com/a"}, thread="t1", service="agent")
    assert r["status"] == "needs_approval" and r["grant_key"] == "url:host"
    out = await approve(ph, r, remember="thread")
    assert out["status"] == "done" and out["result"]["ran"] == "fetch"
    g = out["grant"]
    assert (g["tool"], g["key"], g["kind"], g["scope"], g["thread"], g["risk"]) == (FETCH, "github.com", "url:host", "thread", "t1", "network")
    again = await ph.call(FETCH, {"url": "https://github.com/b/c"}, thread="t1", service="agent")
    assert again["status"] == "done" and not again.get("approval_id")     # no card
    assert (await ph.call(FETCH, {"url": "https://example.com/"}, thread="t1"))["status"] == "needs_approval"   # another domain
    assert (await ph.call(FETCH, {"url": "https://api.github.com/"}, thread="t1"))["status"] == "needs_approval"  # a subdomain too
    assert (await ph.call(FETCH, {"url": "https://github.com/a"}, thread="t2"))["status"] == "needs_approval"   # another chat
    assert (await ph.call(FETCH, {"url": "https://github.com/a"}))["status"] == "needs_approval"                # no chat
    listed = (await ph.client.get("/api/grants?thread=t1")).json()
    assert [x["id"] for x in listed] == [g["id"]] and listed[0]["used"] == 1 and listed[0]["note"].startswith("from approval")


async def test_a_grant_runs_the_call_with_its_id_in_the_origin(ph):
    r = await ph.call(SEARCH, {"query": "llama.cpp"}, thread="t1")
    g = (await approve(ph, r, remember="thread"))["grant"]
    assert g["key"] == "search"                                            # const: every search in this chat
    again = await ph.call(SEARCH, {"query": "something else"}, thread="t1")
    assert again["status"] == "done"
    row = await ph.hub.db.fetchone("SELECT origin FROM tool_calls WHERE id = ?", (again["call_id"],))
    assert f'"grant": "{g["id"]}"' in row["origin"]


async def test_always_covers_every_chat_and_callers_without_one(ph):
    r = await ph.call(FETCH, {"url": "https://docs.python.org/3/"})
    g = (await approve(ph, r, remember="always"))["grant"]
    assert g["scope"] == "always" and g.get("thread") is None
    for origin in ({"thread": "t9"}, {}, {"service": "mcp", "client": "x"}):
        assert (await ph.call(FETCH, {"url": "https://docs.python.org/x"}, **origin))["status"] == "done"
    assert (await ph.call(FETCH, {"url": "https://python.org/x"}))["status"] == "needs_approval"


async def test_arg_keys_cover_one_folder(ph):
    r = await ph.call(RUN, {"folder": "~/Projects/foo", "command": "pytest -x"}, thread="t1")
    assert r["risk"] == "execute"
    g = (await approve(ph, r, remember="thread"))["grant"]                # thread grants need no second confirm
    assert g["key"] == "~/Projects/foo"
    ok = await ph.call(RUN, {"folder": "~/Projects/foo", "command": "ruff check"}, thread="t1", mode="auto")
    assert ok["status"] == "done"                                          # execute runs under a grant, in any mode but read-only
    assert (await ph.call(RUN, {"folder": "~/Projects/bar", "command": "ls"}, thread="t1"))["status"] == "needs_approval"
    ro = await ph.call(RUN, {"folder": "~/Projects/foo", "command": "ls"}, thread="t1", mode="read_only")
    assert ro["status"] == "denied"                                        # the mode comes before grants


async def test_deny_list_beats_a_grant(ph):
    r = await ph.call(PY, {"code": "print(1)"}, thread="t1")
    await approve(ph, r, remember="thread")
    ph.hub.config.agent.permissions.deny = ["fake_perms_*"]
    try:
        assert (await ph.call(PY, {"code": "print(2)"}, thread="t1"))["status"] == "denied"
    finally:
        ph.hub.config.agent.permissions.deny = []


async def test_always_for_execute_and_destructive_needs_a_second_confirm(ph):
    r = await ph.call(PY, {"code": "print(1)"}, thread="t1")
    err = await approve(ph, r, 422, remember="always")
    assert err["code"] == "confirm_needed" and err["data"]["fix"]
    assert (await ph.client.get(f"/api/approvals/{r['approval_id']}")).json()["state"] == "pending"   # nothing decided
    assert not made((await ph.client.get("/api/grants")).json())
    g = (await approve(ph, r, remember="always", confirm=True))["grant"]
    assert (g["scope"], g["key"], g["risk"]) == ("always", "python", "execute")
    w = await ph.call(WIPE, {"jid": "j_1"})
    assert w["risk"] == "destructive"
    assert (await approve(ph, w, 422, remember="always"))["code"] == "confirm_needed"
    # a network tool's `always` needs no second confirm
    f = await ph.call(FETCH, {"url": "https://a.org"})
    assert (await approve(ph, f, remember="always"))["grant"]["key"] == "a.org"


async def test_allow_in_this_chat_needs_a_chat(ph):
    r = await ph.call(FETCH, {"url": "https://github.com"}, service="mcp", client="claude")
    err = await approve(ph, r, 422, remember="thread")
    assert err["code"] == "no_thread"


async def test_expiry_and_revoke(ph):
    grants = ph.hub.grants
    old = await grants.add(FETCH, "github.com", "always", kind="url:host", expires_ts=time.time() - 1)
    assert (await ph.call(FETCH, {"url": "https://github.com"}))["status"] == "needs_approval"
    assert old["id"] not in [g["id"] for g in (await ph.client.get("/api/grants")).json()]
    r = await ph.call(FETCH, {"url": "https://github.com"})
    g = (await approve(ph, r, remember="always", grant_hours=1))["grant"]
    assert 3500 < g["expires_ts"] - time.time() <= 3600
    assert (await ph.call(FETCH, {"url": "https://github.com"}))["status"] == "done"
    assert (await ph.client.delete(f"/api/grants/{g['id']}")).json() == {"deleted": 1}
    assert (await ph.client.delete(f"/api/grants/{g['id']}")).status_code == 404
    assert (await ph.call(FETCH, {"url": "https://github.com"}))["status"] == "needs_approval"


async def test_a_deleted_chat_ends_its_grants(ph):
    for t in ("t1", "t2"):
        await ph.hub.grants.add(SEARCH, "search", "thread", t, kind="const:search")
    keep = await ph.hub.grants.add(FETCH, "a.org", "always")
    assert (await ph.client.delete("/api/grants")).status_code == 422      # a thread is required
    assert (await ph.client.delete("/api/grants?thread=t1")).json() == {"deleted": 1}
    assert {(g.get("thread"), g["tool"]) for g in made((await ph.client.get("/api/grants")).json())} == {("t2", SEARCH), (None, FETCH)}
    assert keep["id"] in [g["id"] for g in (await ph.client.get(f"/api/grants?tool={FETCH}")).json()]


async def test_mcp_calls_use_only_always_grants(ph):
    await ph.hub.grants.add(FETCH, "github.com", "thread", "t1", kind="url:host")
    res = await mcp_call(ph, FETCH, {"url": "https://github.com/x"})
    assert "aihub/approval" in (res.get("_meta") or {})                    # a thread grant doesn't reach MCP
    await ph.hub.grants.add(FETCH, "github.com", "always", kind="url:host")
    res = await mcp_call(ph, FETCH, {"url": "https://github.com/x"})
    assert "aihub/approval" not in (res.get("_meta") or {}) and not res.get("isError"), res
    assert "fetch" in res["content"][0]["text"]


@pytest.mark.parametrize("tool,args", [(FETCH, {"url": "https://github.com/x"}), (RUN, {"folder": "~/p", "command": "ls"})])
async def test_every_mode_and_button_in_chat_and_over_mcp(ph, tool, args):
    """Phase 25's check: for a network and an execute tool, each mode × each button, then the next
    call from the same chat, another chat and MCP."""
    for mode in ("ask", "auto", "read_only"):
        for remember in ("once", "thread", "always"):
            thread = f"{mode}-{remember}"
            r = await ph.call(tool, args, mode=mode, thread=thread, service="agent")
            if mode == "read_only":
                assert r["status"] == "denied"
                continue
            assert r["status"] == "needs_approval"
            extra = {"confirm": True} if remember == "always" and tool == RUN else {}
            out = await approve(ph, r, remember=remember, **extra)
            assert out["status"] == "done" and bool(out.get("grant")) == (remember != "once")
            same = await ph.call(tool, args, mode=mode, thread=thread, service="agent")
            other = await ph.call(tool, args, mode=mode, thread="elsewhere", service="agent")
            mcp = await mcp_call(ph, tool, args)
            assert same["status"] == ("needs_approval" if remember == "once" else "done"), (mode, remember)
            assert other["status"] == ("done" if remember == "always" else "needs_approval"), (mode, remember)
            assert ("aihub/approval" in (mcp.get("_meta") or {})) == (remember != "always"), (mode, remember)
            for g in (await ph.client.get("/api/grants")).json():
                await ph.client.delete(f"/api/grants/{g['id']}")


async def test_shipped_grant_lets_web_search_run_and_a_revoke_stays(ph, tmp_path):
    """Migration 010 (plan 26.2): one `always` grant for web_search, listed like any grant; revoking
    it deletes it, and opening the database again doesn't bring it back."""
    import sqlite3

    from utils.db import MIGRATIONS, migrate
    from utils.tools.catalog import ToolDef

    g = {x["id"]: x for x in (await ph.client.get("/api/grants")).json()}[SHIPPED]
    assert (g["tool"], g["key"], g["kind"], g["risk"], g["scope"], g.get("thread")) == ("web_search", "search", "const:search", "network", "always", None)
    assert "Revoke" in g["note"]
    search = ToolDef("web_search", "web", "search", "", {}, risk="network", grant_key="const:search")
    fetch = ToolDef("web_fetch", "web", "fetch", "", {}, risk="network", grant_key="url:host")
    assert (await ph.hub.grants.match(search, {"query": "x"}, {"thread": "t9"}))["id"] == SHIPPED
    assert (await ph.hub.grants.match(search, {"query": "x"}, None))["id"] == SHIPPED      # MCP too: it's `always`
    assert await ph.hub.grants.match(fetch, {"url": "https://example.org/"}, {"thread": "t9"}) is None
    assert (await ph.client.delete(f"/api/grants/{SHIPPED}")).status_code == 200
    assert SHIPPED not in [x["id"] for x in (await ph.client.get("/api/grants")).json()]

    conn = sqlite3.connect(tmp_path / "hub.db")
    assert migrate(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT count(*) FROM grants WHERE id = ?", (SHIPPED,)).fetchone()[0] == 1
    conn.execute("DELETE FROM grants WHERE id = ?", (SHIPPED,))
    conn.commit()
    assert migrate(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT count(*) FROM grants WHERE id = ?", (SHIPPED,)).fetchone()[0] == 0
    conn.close()


async def test_dry_run_reaches_a_mod_that_answers_it(ph):
    """`dry_run = true` in `[tools]` (plan 26.2): in a dry run the call goes to the mod, which sees
    `dry_run` in X-AIHub-Origin; a network tool without it gets the stand-in, as before."""
    r = await ph.call(FETCH, {"url": "https://example.org/a"}, thread="t1", dry_run=True, service="agent")
    out = await approve(ph, r)
    assert out["result"] == {"ran": "fetch", "arguments": {"url": "https://example.org/a"}, "dry_run": True}
    r = await ph.call(SEARCH, {"query": "x"}, thread="t1", dry_run=True, service="agent")
    out = await approve(ph, r)
    assert out["result"] == {"dry_run": True, "arguments": {"query": "x"}}
    assert (await ph.call(FETCH, {"url": "https://example.org/b"}, thread="t1", service="agent"))["status"] == "needs_approval"


async def test_a_dry_run_ignores_a_persons_always_grants(ph):
    """In a dry run (the agent eval) only the grants AIHub ships and the chat's own count, so a card the
    eval means to test still shows on a machine where someone chose "always allow"."""
    from utils.tools.catalog import ToolDef

    r = await ph.call(FETCH, {"url": "https://docs.python.org/3/"})
    await approve(ph, r, remember="always")
    assert (await ph.call(FETCH, {"url": "https://docs.python.org/x"}, thread="t1", service="agent"))["status"] == "done"
    r = await ph.call(FETCH, {"url": "https://docs.python.org/y"}, thread="t2", dry_run=True, service="agent")
    assert r["status"] == "needs_approval"
    await approve(ph, r, remember="thread")
    assert (await ph.call(FETCH, {"url": "https://docs.python.org/z"}, thread="t2", dry_run=True, service="agent"))["status"] == "done"
    search = ToolDef("web_search", "web", "search", "", {}, risk="network", grant_key="const:search")
    assert (await ph.hub.grants.match(search, {"query": "x"}, {"thread": "t3", "dry_run": True}))["id"] == SHIPPED
