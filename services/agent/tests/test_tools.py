"""14.6: tools on demand: the index in the prompt, find → load → call, pinned and disabled
groups, a refused disabled call."""

from __future__ import annotations


def tool_names(req):
    return {t["function"]["name"] for t in req.get("tools") or []}


async def test_core_and_local_loaded_rest_listed(env):
    tid = await env.thread()
    await env.send(tid, "hi")
    req = env.model.received[-1]
    names = tool_names(req)
    assert {"ask_user", "update_todos", "find_tools", "load_tools", "read_skill", "view_output", "read_result", "remember",
            "hub_list_services"} <= names
    assert "fake_make_image" not in names
    system = req["messages"][0]["content"]
    assert "## More tools" in system and "- fake: fake_get, fake_make_image" in system and "- gen3d: gen3d_make_3d" in system


async def test_find_load_call_in_one_turn(env):
    env.model.queue({"tool_calls": [{"name": "find_tools", "arguments": {"query": "image"}}]},
                    {"tool_calls": [{"name": "load_tools", "arguments": {"names": ["fake_make_image", "nope_tool"]}}]},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "fox"}}]}, {"text": "done"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "an image of a fox")
    found, loaded, made = env.payloads(tid, "tool_result")[:3]
    assert "fake_make_image" in found["content"]
    assert '"unknown": ["nope_tool"]' in loaded["content"]
    assert made["status"] == "done"
    assert "fake_make_image" in tool_names(env.model.received[-1])
    assert "fake_make_image" not in env.model.received[-1]["messages"][0]["content"].split("## More tools")[1].split("##")[0]
    # still loaded in the next turn (kept in the thread's settings)
    await env.send(tid, "again")
    assert "fake_make_image" in tool_names(env.model.received[-1])


async def test_load_a_group(env):
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"group": "fake"}}]}, {"text": "loaded"})
    tid = await env.thread()
    await env.send(tid, "load fake")
    assert {"fake_get", "fake_make_image", "fake_render", "fake_wipe", "fake_fail"} <= tool_names(env.model.received[-1])


async def test_pinned_and_disabled_groups(env):
    tid = await env.thread(settings={"pinned": ["tts"], "disabled": ["gen3d"]})
    env.model.queue({"tool_calls": [{"name": "gen3d_make_3d", "arguments": {"prompt": "cube"}}]}, {"text": "3D is off here."})
    await env.send(tid, "make a cube")
    req = env.model.received[0]
    assert "tts_speak" in tool_names(req) and "gen3d_make_3d" not in tool_names(req)
    assert "gen3d" not in req["messages"][0]["content"].split("## More tools")[1].split("##")[0]
    assert "Turned off in this chat: gen3d" in req["messages"][0]["content"]
    res = env.payloads(tid, "tool_result")[0]
    assert res["status"] == "denied" and res["error"]["code"] == "disabled"
    assert not [a for a in env.hub.attempts if a["name"] == "gen3d_make_3d"]     # never reached the hub
    r = await env.client.patch(f"/v1/threads/{tid}", json={"settings": {"disabled": []}})
    assert r.json()["settings"]["pinned"] == ["tts"] and r.json()["settings"]["disabled"] == []


async def test_unknown_tool_is_an_error_not_a_crash(env):
    env.model.queue({"tool_calls": [{"name": "made_up_tool", "arguments": {}}]}, {"text": "sorry"})
    tid = await env.thread()
    await env.send(tid, "x")
    res = env.payloads(tid, "tool_result")[0]
    assert res["status"] == "error" and res["error"]["code"] == "unknown_tool"
    assert env.agent.store.thread(tid)["state"] == "idle"


async def test_a_disabled_group_says_so_when_loaded_or_searched(env):
    """The 26B looped on load_tools(group=gen3d) when the replies only listed the tools as 'unknown'."""
    tid = await env.thread(settings={"disabled": ["gen3d"]})
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"group": "gen3d"}}]},
                    {"tool_calls": [{"name": "load_tools", "arguments": {"names": ["gen3d_make_3d", "fake_get"]}}]},
                    {"tool_calls": [{"name": "find_tools", "arguments": {"query": "gen3d"}}]}, {"text": "3D is off in this chat."})
    await env.send(tid, "make a 3D chair")
    by_group, by_name, found = env.payloads(tid, "tool_result")[:3]
    assert by_group["status"] == "error" and by_group["error"]["code"] == "disabled"
    assert "gen3d tools are turned off" in by_group["error"]["detail"]
    assert '"loaded": ["fake_get"]' in by_name["content"] and "turned off" in by_name["content"] and "unknown" not in by_name["content"]
    assert "gen3d tools are turned off" in found["content"]
    assert "gen3d" not in found["content"].split("The groups are:")[1]


async def test_a_disabled_mod_cant_be_started_from_the_chat(env):
    """With gen3d off, the 26B called hub_start_service(gen3d) instead."""
    tid = await env.thread(mode="auto", settings={"disabled": ["gen3d"]})
    env.model.queue({"tool_calls": [{"name": "hub_start_service", "arguments": {"id": "gen3d"}}]}, {"text": "3D is off here."})
    await env.send(tid, "start 3D")
    res = env.payloads(tid, "tool_result")[0]
    assert res["status"] == "denied" and res["error"]["code"] == "disabled" and "gen3d" in res["error"]["detail"]
    assert not [a for a in env.hub.attempts if a["name"] == "hub_start_service"]
