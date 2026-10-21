"""Links in the prompt are read directly: the agent sends the http(s) links of the user's own messages with a
web_fetch call (`origin.links`, never tool results, attachments or quoted parts) and the user's message as
`origin.question`; the result's `cite` gets the output's real #n; an attached web page's doc carries its URL."""

from __future__ import annotations

import json

from agent import links
from agent.docs import _page_url
from tests.fakehub import T


def test_links_in_what_the_user_typed():
    text = ("Compare https://example.org/a, the docs at <https://docs.example.com/x?y=1#z> and "
            "[this](https://en.wikipedia.org/wiki/Foo_(bar)). Also (see https://example.net/p). And http://x.org/q!")
    assert links.links_in(text) == ["https://example.org/a", "https://docs.example.com/x?y=1#z",
                                    "https://en.wikipedia.org/wiki/Foo_(bar)", "https://example.net/p", "http://x.org/q"]
    assert links.links_in("no links, ftp://example.org/ or example.org") == []
    assert links.user_links(["https://a.org/1", "https://b.org/2 https://a.org/1"]) == ["https://b.org/2", "https://a.org/1"]


async def test_web_fetch_carries_the_users_links_and_question(env):
    env.hub.tools["web_fetch"] = T("web_fetch", "web", "network", {"url": {"type": "string"}}, ["url"], core=True, desc="Fetch a page")
    tid = await env.thread(mode="manual")
    env.model.queue({"text": "ok"}, {"tool_calls": [{"name": "web_fetch", "arguments": {"url": "https://example.org/a"}}]})
    await env.send(tid, "read https://example.net/old please")
    await env.send(tid, "What does https://example.org/a say about gaiters?",
                   quotes=[{"text": "quoted https://quoted.example.com/x", "reply": "and https://reply.example.com/y"}])
    o = env.hub.attempts[-1]["origin"]
    assert env.hub.attempts[-1]["name"] == "web_fetch"
    assert o["links"] == ["https://reply.example.com/y", "https://example.org/a", "https://example.net/old"]   # never the quoted part
    assert o["question"].endswith("What does https://example.org/a say about gaiters?") and "quoted.example" not in o["question"]
    other = await env.thread(mode="manual")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "x"}}]}, {"text": "made"})
    await env.send(other, "make one like https://example.org/pic")
    assert env.hub.attempts[-1]["name"] == "fake_make_image"
    assert "links" not in (env.hub.attempts[-1]["origin"] or {})              # only web_fetch carries them


async def test_cite_gets_the_outputs_ref(env):
    tid = await env.thread()
    res = {"status": "done", "result": {"content": "<untrusted>…</untrusted>",
                                        "cite": "Cite this page as [example.org](https://example.org/a); cite a passage by its line as #n:12 (the numbers on the left)."},
           "outputs": [{"output_id": "o_1", "kind": "text", "title": "A", "summary": "A"}]}
    ev = env.agent._result(tid, "c1", "web_fetch", res)
    body = json.loads(ev["payload"]["content"])
    n = ev["payload"]["outputs"][0]["n"]
    assert f"#{n}:12 (the numbers" in body["result"]["cite"] and "#n:" not in body["result"]["cite"]
    assert res["result"]["cite"].count("#n:12") == 1                          # the hub's result isn't changed


def test_an_attached_web_page_keeps_its_url():
    assert _page_url({"service": "web", "meta": {"url": "https://a.org/x", "final_url": "https://www.a.org/x"}}) == "https://www.a.org/x"
    assert _page_url({"service": "web", "meta": {"source": {"service": "web", "url": "https://a.org/y"}}}) == "https://a.org/y"
    assert _page_url({"service": "uploads", "meta": {"url": "https://a.org/x"}}) is None
    assert _page_url({"service": "web", "meta": {"url": "javascript:alert(1)"}}) is None
