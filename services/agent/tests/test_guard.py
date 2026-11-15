"""capability-enablement 2.3: a guard for failures, not only repeats. A mod refused once is out for the rest of the turn
(answered locally with the first error); error results in a row end the turn's tools; a success resets the count; a
mod turned on mid-turn is callable again."""

from __future__ import annotations

from agent import guard

from .fakehub import T

NOT_SET_UP = {"code": "capability_unavailable", "detail": "I can't search the web and read pages: Web isn't set up on this machine",
              "fix": "tell the user what is missing and offer to set it up; don't retry", "state": "not_set_up", "service": "web"}


def add_web(env):
    env.hub.tools["web_search"] = T("web_search", "web", "read", {"query": {"type": "string"}}, ["query"], core=True, desc="Search the web")
    env.hub.tools["hub_enable_service"] = T("hub_enable_service", "hub", "write", {"id": {"type": "string"}}, ["id"], core=True, desc="Turn a mod on")


def calls(*items):
    return [{"tool_calls": [{"name": n, "arguments": a}]} for n, a in items]


def results(env, tid):
    return [p for p in env.payloads(tid, "tool_result")]


async def test_five_different_queries_are_refused_once_by_the_hub_then_locally(env):
    add_web(env)
    env.hub.refuse["web_search"] = NOT_SET_UP
    tid = await env.thread(mode="bypass")
    env.model.queue(*calls(*[("web_search", {"query": f"weather {i}"}) for i in range(5)]), {"text": "Web isn't set up."})
    await env.send(tid, "weather this weekend?")
    rs = results(env, tid)
    assert len([a for a in env.hub.attempts if a["name"] == "web_search"]) == 1
    assert [r["error"]["code"] for r in rs] == ["capability_unavailable"] * 4
    assert rs[1]["error"]["fix"] == guard.ALREADY and rs[1]["error"]["detail"].startswith("web_search: I can't search the web")
    assert env.model.received[-1].get("tool_choice") == "none"          # the fifth step answers without tools
    assert len(env.model.received) == 5
    notes = [n["text"] for n in env.payloads(tid, "note")]
    assert any("several tool calls failed in a row" in n for n in notes)
    assert "your last tool calls all failed" in env.model.received[-1]["messages"][-1]["content"]


async def test_four_different_failing_tools_end_the_turn(env):
    for n in ("fake_get", "fake_render", "tts_speak"):
        env.hub.refuse[n] = {"code": "upstream_error", "detail": f"{n} broke"}
    tid = await env.thread(mode="bypass")
    env.model.queue(*calls(("fake_fail", {}), ("fake_get", {"id": "a"}), ("fake_render", {"prompt": "x"}), ("tts_speak", {"text": "x"}),
                           ("fake_fail", {})), {"text": "unused"})
    await env.send(tid, "do things")
    assert len(results(env, tid)) == 4 and env.model.received[-1].get("tool_choice") == "none"
    assert env.payloads(tid, "assistant")[-1]["text"]


async def test_a_success_resets_the_count(env):
    tid = await env.thread(mode="bypass")
    env.model.queue(*calls(("fake_fail", {}), ("fake_fail", {"x": 1}), ("fake_fail", {"x": 2}), ("fake_get", {"id": "a"}),
                           ("fake_fail", {"x": 3})), {"text": "done"})     # 4 failures, but not in a row
    await env.send(tid, "go")
    assert all(r.get("tool_choice") != "none" for r in env.model.received)
    assert env.payloads(tid, "assistant")[-1]["text"] == "done"


async def test_a_mod_turned_on_mid_turn_is_callable_again(env):
    add_web(env)
    env.hub.refuse["web_search"] = {**NOT_SET_UP, "code": "capability_unavailable", "state": "off"}
    tid = await env.thread(mode="bypass")
    env.model.queue(*calls(("web_search", {"query": "a"}), ("hub_enable_service", {"id": "web"}), ("web_search", {"query": "b"})),
                    {"text": "ok"})
    await env.send(tid, "search for a")
    tries = [a for a in env.hub.attempts if a["name"] == "web_search"]
    assert len(tries) == 2                                              # the second went to the hub again


def test_out_for_turn_from_events():
    def ev(seq, t, **p):
        return {"seq": seq, "type": t, "payload": p}
    evs = [ev(1, "user", text="x"), ev(2, "tool_call", id="c1", name="web_search", arguments={}),
           ev(3, "tool_result", id="c1", name="web_search", status="error", error={"code": "tool_unavailable", "detail": "no route"}),
           ev(4, "tool_call", id="c2", name="hub_start_service", arguments={"id": "web"}),
           ev(5, "tool_result", id="c2", name="hub_start_service", status="error", error={"code": "service_failed"})]
    mod_of = {"web_search": "web"}.get
    assert set(guard.out_for_turn(evs, mod_of)) == {"web"}               # a failed start doesn't turn it on
    evs[-1]["payload"].update(status="done", error=None)
    assert guard.out_for_turn(evs, mod_of) == {}
    assert guard.failing(evs[:3], 1) == ["web_search: tool_unavailable"] and guard.failing(evs, 4) == []


async def test_a_turned_off_mod_is_turned_on_by_its_call(env):
    """2.4: the hub refuses a turned-off mod's tool with turn_on hub_enable_service; the agent turns it on and runs it again."""
    add_web(env)
    env.hub.refuse["web_search"] = {**NOT_SET_UP, "state": "off", "detail": "I can't search the web: Web is turned off",
                                    "turn_on": {"tool": "hub_enable_service", "arguments": {"id": "web"}, "command": ""}}
    tid = await env.thread()
    env.model.queue(*calls(("web_search", {"query": "a"})), {"text": "Found it."})
    await env.send(tid, "search for a")
    names = [a["name"] for a in env.hub.attempts]
    assert names == ["web_search", "hub_enable_service", "web_search"]
    assert env.payloads(tid, "tool_result")[0]["status"] != "error"
    assert any("turned on web to run web_search" in n["text"] for n in env.payloads(tid, "note"))


async def test_not_in_an_unattended_run(env):
    add_web(env)
    env.hub.refuse["web_search"] = {**NOT_SET_UP, "state": "off",
                                    "turn_on": {"tool": "hub_enable_service", "arguments": {"id": "web"}, "command": ""}}
    tid = await env.thread(settings={"unattended": True})
    env.model.queue(*calls(("web_search", {"query": "a"})), {"text": "Off."})
    await env.send(tid, "search for a")
    assert [a["name"] for a in env.hub.attempts] == ["web_search"]


async def test_a_tool_the_mod_turned_off_is_out_alone(env):
    """2.4: web_search off by the mod (no SearXNG) doesn't take web_fetch out of the turn."""
    add_web(env)
    env.hub.tools["web_fetch"] = T("web_fetch", "web", "read", {"url": {"type": "string"}}, ["url"], core=True, desc="Fetch a page")
    env.hub.refuse["web_search"] = {"code": "capability_unavailable", "detail": "web_search is off right now: no SearXNG answers",
                                    "state": "off_by_mod", "service": "web"}
    tid = await env.thread(mode="bypass")
    env.model.queue(*calls(("web_search", {"query": "a"}), ("web_fetch", {"url": "https://example.org/"}), ("web_search", {"query": "b"})),
                    {"text": "ok"})
    await env.send(tid, "look it up")
    assert [a["name"] for a in env.hub.attempts] == ["web_search", "web_fetch"]      # the second search is answered locally
