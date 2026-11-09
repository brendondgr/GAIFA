"""Scheduled-tasks 2.1: in an unattended run (origin.unattended) what would be a card is refused, a grant still runs
the call (and says which), a judged ask is refused and recorded, and POST /api/grants writes a chat's grants ahead of
time: thread only, globs, one site or every site under the judge's URL rules."""

from __future__ import annotations

from utils.tests.tools.test_judge_auto import fake_model

FETCH, RUN, SEARCH = "fake_perms_fetch", "fake_perms_run", "fake_perms_search"


async def grant(h, **body):
    r = await h.client.post("/api/grants", json=body)
    return r


async def test_an_ask_is_refused_when_no_one_is_there(ph):
    r = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="t1", service="agent", unattended=True)
    assert r["status"] == "denied" and r["error"]["code"] == "unattended" and "no one is here" in r["error"]["detail"]
    assert (await ph.client.get("/api/approvals?state=pending")).json() == []          # no card
    attended = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="t1", service="agent")
    assert attended["status"] == "needs_approval"


async def test_a_grant_still_runs_it_and_says_which(ph):
    g = await grant(ph, tool=RUN, thread="t1")
    assert g.status_code == 201, g.text
    g = g.json()
    assert (g["tool"], g["scope"], g["thread"], g.get("key")) == (RUN, "thread", "t1", None)
    r = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="t1", service="agent", unattended=True)
    assert r["status"] == "done" and r["grant_id"] == g["id"]
    other = await ph.call(RUN, {"folder": "~/p", "command": "ls"}, thread="t2", service="agent", unattended=True)
    assert other["status"] == "denied"                                                  # another chat


async def test_globs_and_sites(ph):
    assert (await grant(ph, tool="fake_perms_*", thread="t1")).status_code == 201
    assert (await ph.call(SEARCH, {"query": "x"}, thread="t1", unattended=True))["status"] == "done"
    site = (await grant(ph, tool=FETCH, kind="url:host", key="Example.com.", thread="t2")).json()
    assert site["key"] == "example.com" and site["kind"] == "url:host"
    assert (await ph.call(FETCH, {"url": "https://example.com/a"}, thread="t2", unattended=True))["status"] == "done"
    assert (await ph.call(FETCH, {"url": "https://other.org/a"}, thread="t2", unattended=True))["status"] == "denied"
    every = (await grant(ph, tool=FETCH, kind="url:any", thread="t3")).json()
    assert every["key"] == "*" and every["kind"] == "url:any"
    assert (await ph.call(FETCH, {"url": "https://other.org/a"}, thread="t3", unattended=True))["status"] == "done"
    flagged = await ph.call(FETCH, {"url": "http://127.0.0.1:7000/api/settings"}, thread="t3", unattended=True)
    assert flagged["status"] == "denied"                                                # the URL rules still apply


async def test_bad_grants(ph):
    assert (await grant(ph, tool=RUN)).status_code == 422                               # no chat
    assert (await grant(ph, tool=RUN, thread="t1", scope="always")).status_code == 422  # never always
    r = await grant(ph, tool="nothing_*", thread="t1")
    assert r.status_code == 422 and r.json()["code"] == "unknown_tool"
    r = await grant(ph, tool=RUN, kind="url:host", key="example.com", thread="t1")
    assert r.status_code == 422 and r.json()["code"] == "not_a_web_tool"
    assert (await grant(ph, tool=FETCH, kind="url:host", key="https://x.org/a", thread="t1")).status_code == 422
    assert (await grant(ph, tool=FETCH, key="example.com", thread="t1")).status_code == 422   # a key needs its kind
    assert (await grant(ph, tool=FETCH, kind="folder", key="folder:/", thread="t1")).status_code == 422
    assert (await grant(ph, tool="Bad Name", thread="t1")).status_code == 422


async def test_a_judged_ask_is_refused_and_recorded(wh, monkeypatch):
    fake_model(monkeypatch, lambda state: ("ask", "the instructions don't ask for a deploy"))
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "make deploy"}, mode="auto", thread="t9",
                      said=["Summarize the README every morning."], unattended=True)
    assert r["status"] == "denied" and r["error"]["code"] == "unattended"
    assert r["judge"]["verdict"] == "ask" and r["judge"]["refused"] is True
    recent = (await wh.client.get("/api/judge/recent", params={"thread": "t9"})).json()
    assert recent[0]["verdict"] == "refused" and recent[0]["reason"] == "the instructions don't ask for a deploy"
    fake_model(monkeypatch)
    ok = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="auto", thread="t9",
                       said=["Run the tests every morning."], unattended=True)
    assert ok["status"] == "done" and ok["judge"]["verdict"] == "allow"
