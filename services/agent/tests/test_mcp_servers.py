"""mcp-client 4.1: an MCP server's tools stay out of a chat until a skill that names the server is read, the query
names it, or the composer pins it; turned off, never."""

from __future__ import annotations

import json

from tests.fakehub import T


def add_blender(env):
    for name, risk in (("blender_get_scene_info", "read"), ("blender_execute_blender_code", "execute")):
        t = T(f"mcp_{name}", "mcp", risk, {"code": {"type": "string"}}, desc=f"Blender (MCP server): {name}")
        env.hub.tools[t["name"]] = {**t, "group": "mcp:blender"}
    env.hub.skills[("mcp", "blender")] = {"description": "Working in Blender through its MCP server", "body": "Look at the scene first.",
                                          "meta": {"metadata": {"mcp-servers": "blender"}}}


def system(env) -> str:
    return env.model.received[-1]["messages"][0]["content"]


def tool_names(env) -> set[str]:
    return {t["function"]["name"] for t in env.model.received[-1].get("tools") or []}


async def test_hidden_until_a_skill_turns_it_on(env):
    add_blender(env)
    tid = await env.thread()
    await env.send(tid, "hi")
    assert "mcp_blender" not in system(env) and not any(n.startswith("mcp_") for n in tool_names(env))
    env.model.queue({"tool_calls": [{"name": "find_tools", "arguments": {"query": "scene code"}}]}, {"text": "none"})
    await env.send(tid, "can you look at my 3D scene?")
    found = json.loads(env.payloads(tid, "tool_result")[-1]["content"]) if env.payloads(tid, "tool_result")[-1]["content"].startswith("{") else {}
    assert not any(t["name"].startswith("mcp_") for t in found.get("tools", []))          # hidden: not found
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "mcp/blender"}}]}, {"text": "ready"})
    await env.send(tid, "make a scene in Blender")
    r = env.payloads(tid, "tool_result")[-1]["content"]
    assert r.startswith("Look at the scene first.") and "The MCP server blender's tools are loaded: mcp_blender_get_scene_info, mcp_blender_execute_blender_code" in r
    assert env.agent.store.thread(tid)["settings"]["mcp_on"] == ["mcp:blender"]
    await env.send(tid, "go on")
    assert {"mcp_blender_get_scene_info", "mcp_blender_execute_blender_code"} <= tool_names(env)


async def test_a_query_that_names_the_server_finds_it(env):
    add_blender(env)
    env.model.queue({"tool_calls": [{"name": "find_tools", "arguments": {"query": "blender scene"}}]}, {"text": "found"})
    tid = await env.thread()
    await env.send(tid, "use blender")
    found = json.loads(env.payloads(tid, "tool_result")[-1]["content"])
    assert "mcp_blender_get_scene_info" in {t["name"] for t in found["tools"]}


async def test_pinned_shows_it_and_off_keeps_it_out(env):
    add_blender(env)
    tid = await env.thread(settings={"pinned": ["mcp:blender"]})
    await env.send(tid, "hi")
    assert "mcp_blender_get_scene_info" in tool_names(env)
    t2 = await env.thread(settings={"disabled": ["mcp:blender"]})
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "mcp/blender"}}]}, {"text": "ok"})
    await env.send(t2, "blender please")
    assert "turned off in this chat" in env.payloads(t2, "tool_result")[-1]["content"]
    assert not any(n.startswith("mcp_") for n in tool_names(env))


async def test_a_skill_for_a_server_not_set_up(env):
    env.hub.skills[("fake", "unity")] = {"description": "Unity", "body": "Steps.", "meta": {"metadata": {"mcp-servers": "unity"}}}
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "fake/unity"}}]}, {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "unity")
    assert "isn't set up and approved in GAIFA" in env.payloads(tid, "tool_result")[-1]["content"]


async def test_a_mention_pins_the_server(env):
    add_blender(env)
    tid = await env.thread()
    await env.send(tid, "@mcp:blender what's in the scene?", mentions=[{"kind": "mcp", "id": "blender", "label": "Blender", "fills": []}])
    assert "mcp:blender" in env.agent.store.thread(tid)["settings"]["pinned"]
    assert "mcp_blender_get_scene_info" in tool_names(env)
