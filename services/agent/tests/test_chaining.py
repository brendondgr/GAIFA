"""14.8: references (#n) and view_output: image → 3D by description, an image as an input, a
description from view_output, the non-vision fallback, and a deleted output."""

from __future__ import annotations

import json


async def make_image(env, tid, prompt="a red fox"):
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": prompt}}]}, {"text": "Made #1."})
    await env.send(tid, f"make {prompt}")
    return env.payloads(tid, "tool_result")[-1]["outputs"][0]


async def test_outputs_table_and_image_as_input(env):
    tid = await env.thread(mode="auto")
    o = await make_image(env, tid)
    assert o["n"] == 1 and o["kind"] == "image"
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "same fox at night", "image": f"output:{o['output_id']}"}}]},
                    {"text": "Here it is at night (#2)."})
    await env.send(tid, "now make that fox at night")
    sys_prompt = env.model.received[-2]["messages"][0]["content"]
    assert f"#1 image via fake_make_image: a red fox → output:{o['output_id']}" in sys_prompt
    assert env.hub.calls[-1]["arguments"]["image"] == f"output:{o['output_id']}"
    assert env.payloads(tid, "tool_result")[-1]["outputs"][0]["n"] == 2


async def test_image_to_3d_through_a_description(env):
    tid = await env.thread(mode="auto")
    o = await make_image(env, tid)
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": "#1"}}]},
                    {"tool_calls": [{"name": "gen3d_make_3d", "arguments": {"prompt": "a low-poly red fox sitting"}}]},
                    {"text": "Your 3D fox is ready (#2)."})
    await env.send(tid, "turn that into a 3D model")
    msgs = env.model.received[-2]["messages"]
    img = [m for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert img and img[-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    view = json.loads(env.payloads(tid, "tool_result")[-2]["content"])
    assert view["kind"] == "image" and view["meta"]["prompt"] == "a red fox"
    made = env.payloads(tid, "tool_result")[-1]
    assert made["name"] == "gen3d_make_3d" and made["outputs"][0]["kind"] == "model3d" and made["outputs"][0]["n"] == 2


async def test_view_output_without_vision_returns_details(env):
    tid = await env.thread(mode="auto", model="blind")
    await make_image(env, tid, "a blue owl")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": "#1"}}]}, {"text": "It's an owl."})
    await env.send(tid, "describe #1")
    res = json.loads(env.payloads(tid, "tool_result")[-1]["content"])
    assert "can't see images" in res["note"] and res["meta"]["prompt"] == "a blue owl"
    assert not any(isinstance(m["content"], list) for m in env.model.received[-1]["messages"])


async def test_deleted_or_unknown_reference(env):
    tid = await env.thread(mode="auto")
    o = await make_image(env, tid)
    env.hub.outputs.pop(o["output_id"])
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": "#1"}}, {"name": "view_output", "arguments": {"ref": "#9"}}]},
                    {"text": "That image is gone."})
    await env.send(tid, "look at it")
    res = env.payloads(tid, "tool_result")[-2:]     # read-only calls run in parallel: any order
    assert {r["error"]["code"] for r in res} == {"unknown_output"}
    assert any("gone" in r["error"]["detail"] for r in res) and any("isn't an output" in r["error"]["detail"] for r in res)


async def test_describe_then_speak(env):
    tid = await env.thread(mode="auto")
    await make_image(env, tid)
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": "#1"}}]},
                    {"tool_calls": [{"name": "tts_speak", "arguments": {"text": "A red fox sits in the snow.", "name": "af_heart"}}]},
                    {"text": "Spoken (#2)."})
    await env.send(tid, "describe the image, then say it out loud")
    spoke = env.payloads(tid, "tool_result")[-1]
    assert spoke["name"] == "tts_speak" and spoke["outputs"][0]["kind"] == "audio"
