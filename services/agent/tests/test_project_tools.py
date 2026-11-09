"""Plan projects 3.4: project_search, project_read and project_refresh_page, local tools of a project chat only: their
results say how to cite them and carry the text inside <untrusted>; a plain chat doesn't have them."""

from __future__ import annotations

import asyncio
import json
import time

from .test_project_index import _wait

URL = "https://news.example.org/alps-summer-melt"


def tool_names(env) -> set[str]:
    req = env.model.received[-1]
    return {t["function"]["name"] for t in req.get("tools") or []}


async def _setup(env):
    c = env.client
    p = (await c.post("/v1/projects", json={"name": "Thesis"})).json()
    text = "".join(f"Line {i}: the moraine of glacier {i} retreated.\n" for i in range(1, 80))
    oid = env.hub.doc("Field notes.md", text=text, kind="text")
    src = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "file", "output_id": oid})).json()
    env.hub.pages[URL] = "The Alps lost 4% of their ice."
    page = (await c.post(f"/v1/projects/{p['id']}/sources", json={"kind": "page", "url": URL})).json()
    await _wait(lambda: env.agent.projects.source(page["id"])["status"] == "ok")
    await _wait(lambda: env.agent.project_index_store.rows(p["id"], [src["id"]]))
    tid = (await c.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    return p, src, page, tid


def result(env, tid, name):
    return [e for e in env.payloads(tid, "tool_result") if e["name"] == name][-1]


async def test_search_read_and_refresh(env):
    p, src, page, tid = await _setup(env)
    env.model.queue({"tool_calls": [{"name": "project_search", "arguments": {"query": "glacier 42 moraine"}}]},
                    {"tool_calls": [{"name": "project_read", "arguments": {"source": src["id"], "offset": 0, "limit": 600}}]},
                    {"tool_calls": [{"name": "project_refresh_page", "arguments": {"source": page["id"]}}]},
                    {"text": "done"})
    env.hub.pages[URL] = "Updated: the Alps lost 5% of their ice."
    await env.send(tid, "what happened to the moraines?")
    assert {"project_search", "project_read", "project_refresh_page"} <= tool_names(env)
    s = result(env, tid, "project_search")
    assert s["status"] == "done" and s["content"].startswith("Cite a passage as src_") and "<untrusted source=" in s["content"]
    assert f"[{src['id']}:1]" in s["content"]
    r = result(env, tid, "project_read")
    assert r["status"] == "done" and "characters 0–600" in r["content"] and "next: offset 600" in r["content"]
    assert " 1| Line 1: the moraine" in r["content"]
    f = result(env, tid, "project_refresh_page")
    assert f["status"] == "done" and "Fetched" in f["content"]
    assert env.agent.projects.source(page["id"])["output_id"] != page.get("output_id")
    calls = [c["name"] for c in env.hub.calls]
    assert not any(n.startswith("project_") for n in calls)                    # local: never through the hub's catalog


async def test_errors(env):
    p, src, page, tid = await _setup(env)
    env.model.queue({"tool_calls": [{"name": "project_read", "arguments": {"source": "src_nope"}}]},
                    {"tool_calls": [{"name": "project_refresh_page", "arguments": {"source": src["id"]}}]},
                    {"text": "ok"})
    await env.send(tid, "read")
    r = result(env, tid, "project_read")
    assert r["status"] == "error" and r["error"]["code"] == "unknown_source" and src["id"] in r["error"]["fix"]
    assert result(env, tid, "project_refresh_page")["error"]["code"] == "not_a_page"


async def test_absent_from_a_plain_chat(env):
    await _setup(env)
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "project_search", "arguments": {"query": "x"}}]}, {"text": "ok"})
    await env.send(tid, "hi")
    assert not any(n.startswith("project_") for n in tool_names(env))
    r = result(env, tid, "project_search")
    assert r["status"] == "error" and r["error"]["code"] in ("not_a_project_chat", "unknown_tool")
