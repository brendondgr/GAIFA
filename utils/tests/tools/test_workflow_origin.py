"""Plan agent-workflows 1.4: a read-only sub-agent's calls above `read` (and `network`) are refused; grants on a
workflow's root chat cover its sub-agents, and "allow in this chat" from a sub-agent is written for the root."""

from __future__ import annotations

FETCH, RUN, SEARCH = "fake_perms_fetch", "fake_perms_run", "fake_perms_search"
MYC = "/home/u/Agents/Mycelium"


async def test_a_read_only_sub_agent_is_refused_what_changes_things(ph):
    r = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, mode="bypass", thread="c1", root="r1", read_only=True)
    assert r["status"] == "denied" and r["error"]["code"] == "read_only" and "only reads" in r["error"]["detail"]
    assert "start a sub-agent that may change files" in r["error"]["fix"]
    web = await ph.call(SEARCH, {"query": "glaciers"}, mode="bypass", thread="c1", root="r1", read_only=True)
    assert web["status"] in ("done", "needs_approval")                   # reading the web: decided as usual, not refused
    writer = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, mode="bypass", thread="c2", root="r1")
    assert writer["status"] == "needs_approval"                          # the workflow's writer: an execute tool asks, as usual


async def test_grants_on_the_root_cover_its_sub_agents(ph):
    g = await ph.client.post("/api/grants", json={"tool": RUN, "thread": "r1"})
    assert g.status_code == 201, g.text
    child = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="c1", root="r1", unattended=True)
    assert child["status"] == "done" and child["grant_id"] == g.json()["id"]
    other = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="c9", root="r9", unattended=True)
    assert other["status"] == "denied"                                   # another workflow
    sibling_grant = await ph.client.post("/api/grants", json={"tool": SEARCH, "thread": "c1"})
    assert sibling_grant.status_code == 201
    sibling = await ph.call(SEARCH, {"query": "x"}, thread="c2", root="r1", unattended=True)
    assert sibling["status"] == "denied"                                 # a sub-agent's own grant stays its own


async def test_allow_in_this_chat_from_a_sub_agent_is_the_workflow_s(ph):
    r = await ph.call(FETCH, {"url": "https://github.com/a"}, thread="c1", root="r1", service="agent")
    assert r["status"] == "needs_approval"
    resp = await ph.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "remember": "thread"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["grant"]["thread"] == "r1"
    for thread in ("r1", "c2"):
        again = await ph.call(FETCH, {"url": "https://github.com/b"}, thread=thread, root="r1", service="agent")
        assert again["status"] == "done", thread


async def test_folder_grants_on_the_root_reach_its_sub_agents(wh):
    r = await wh.call("fake_ws_read", {"folder": MYC, "path": "core/net.py"}, mode="manual", thread="r1", service="agent")
    d = await wh.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "remember": "thread"})
    assert d.status_code == 200 and d.json()["grant"]["thread"] == "r1"
    child = await wh.call("fake_ws_read", {"folder": MYC, "path": "core/net.py"}, mode="manual", thread="c1", root="r1",
                          service="agent", read_only=True)
    assert child["status"] == "done" and child["result"]["folders"] == [MYC]
