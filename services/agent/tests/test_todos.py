"""14.10: a three-step chain with its checklist states, and a failed step's question."""

from __future__ import annotations

ITEMS = ["Make the fox image", "Animate it", "Narrate it"]


def todos(states):
    return {"name": "update_todos", "arguments": {"items": [{"text": t, "state": s} for t, s in zip(ITEMS, states)]}}


async def test_three_step_chain_with_a_checklist(env):
    env.model.queue({"tool_calls": [todos(["in_progress", "pending", "pending"]), {"name": "fake_make_image", "arguments": {"prompt": "fox"}}]},
                    {"tool_calls": [todos(["done", "in_progress", "pending"]), {"name": "fake_render", "arguments": {"prompt": "fox moves", "seconds": 0.1}}]},
                    {"tool_calls": [todos(["done", "done", "in_progress"]), {"name": "tts_speak", "arguments": {"text": "A fox."}}]},
                    {"tool_calls": [todos(["done", "done", "done"])]}, {"text": "All three done: #1, #2, #3."})
    tid = await env.thread(mode="auto")
    await env.send(tid, "make a fox image, animate it, then narrate it")
    lists = [[i["state"] for i in p["items"]] for p in env.payloads(tid, "todos")]
    assert lists[0] == ["in_progress", "pending", "pending"] and lists[-1] == ["done", "done", "done"]
    kinds = [o["kind"] for p in env.payloads(tid, "tool_result") for o in p.get("outputs") or []]
    assert kinds == ["image", "video", "audio"]


async def test_failed_step_is_marked_and_the_user_is_asked(env):
    env.model.queue({"tool_calls": [todos(["in_progress", "pending", "pending"]), {"name": "fake_fail", "arguments": {}}]},
                    {"tool_calls": [todos(["failed", "pending", "pending"]),
                                    {"name": "ask_user", "arguments": {"questions": [{"question": "The first step failed. What now?",
                                                                                       "options": [{"label": "Retry"}, {"label": "Change it"}, {"label": "Skip"}]}]}}]})
    tid = await env.thread(mode="auto")
    await env.send(tid, "three steps please")
    assert env.payloads(tid, "tool_result")[1]["error"]["fix"] == "try later"
    assert env.payloads(tid, "todos")[-1]["items"][0]["state"] == "failed"
    assert env.agent.store.thread(tid)["state"] == "waiting"
    assert [o["label"] for o in env.payloads(tid, "question")[-1]["questions"][0]["options"]] == ["Retry", "Change it", "Skip"]
