"""14.5: questions (an option, "Other", multi-select, a form), parameter cards (edited, denied,
decided in the hub's popover), action buttons with no model call, and the ask modes."""

from __future__ import annotations

import asyncio
import json

import httpx

Q = {"questions": [{"question": "Which style?", "header": "Style", "options": [{"label": "Photo", "description": "realistic"},
                                                                                {"label": "Ink"}]}]}


async def ask(env, tid, args=Q, then="Got it."):
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": args}]}, *([{"text": then}] if then else []))
    await env.send(tid, "make me a picture")
    assert env.agent.store.thread(tid)["state"] == "waiting"
    return env.payloads(tid, "question")[-1]


async def test_question_answered_with_an_option(env):
    tid = await env.thread()
    q = await ask(env, tid)
    assert q["questions"][0]["options"][0] == {"label": "Photo", "description": "realistic"}
    r = await env.client.post(f"/v1/threads/{tid}/answer", json={"question_id": q["id"], "answers": {"Which style?": "Photo"}})
    assert r.status_code == 202
    await env.settle(tid)
    assert env.agent.store.thread(tid)["state"] == "idle"
    res = env.payloads(tid, "tool_result")[-1]
    assert res["name"] == "ask_user" and json.loads(res["content"]) == {"answers": {"Which style?": "Photo"}}
    assert env.payloads(tid, "assistant")[-1]["text"] == "Got it."
    again = await env.client.post(f"/v1/threads/{tid}/answer", json={"question_id": q["id"], "answers": {"x": "y"}})
    assert again.status_code == 409


async def test_other_text_multi_select_and_a_form(env):
    tid = await env.thread()
    args = {"questions": [{"question": "Which animals?", "options": [{"label": "Fox"}, {"label": "Owl"}, {"label": "Cat"}], "multi_select": True},
                          {"question": "Where?", "options": [{"label": "Forest"}, {"label": "City"}]}]}
    q = await ask(env, tid, args)
    answers = {"Which animals?": ["Fox", "Owl"], "Where?": "On the moon"}     # "Other": typed text
    await env.client.post(f"/v1/threads/{tid}/answer", json={"question_id": q["id"], "answers": answers})
    await env.settle(tid)
    assert json.loads(env.payloads(tid, "tool_result")[-1]["content"])["answers"] == answers
    tid2 = await env.thread()
    form = {"questions": [{"question": "Details?", "options": [{"label": "Defaults"}, {"label": "Custom"}],
                           "schema": {"type": "object", "properties": {"width": {"type": "integer"}}}}]}
    q2 = await ask(env, tid2, form)
    assert q2["questions"][0]["schema"]["properties"]["width"]["type"] == "integer"


async def test_invalid_question_is_an_error_the_model_can_fix(env):
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": {"questions": [{"question": "x?", "options": [{"label": "only one"}]}]}}]},
                    {"text": "Let me just ask plainly: which one?"})
    await env.send(tid, "hm")
    res = env.payloads(tid, "tool_result")[0]
    assert res["status"] == "error" and "2–4 options" in res["error"]["detail"]
    assert env.agent.store.thread(tid)["state"] == "idle"


async def test_typing_instead_of_answering_dismisses_the_question(env):
    tid = await env.thread()
    await ask(env, tid, then=None)
    env.model.queue({"text": "Understood, a watercolor then."})
    await env.send(tid, "actually watercolor")
    res = env.payloads(tid, "tool_result")[-1]
    assert res["status"] == "skipped"
    assert env.payloads(tid, "assistant")[-1]["text"] == "Understood, a watercolor then."


async def test_parameter_card_edited_then_run(env):
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "a fox", "aspect": "1:1"}}]},
                    {"text": "Here's your fox (#1)."})
    await env.send(tid, "a fox image")
    assert env.agent.store.thread(tid)["state"] == "waiting"
    ap = env.payloads(tid, "approval")[-1]
    assert ap["ask_fields"] == ["aspect"] and ap["arguments"] == {"prompt": "a fox", "aspect": "1:1"} and ap["schema"]["properties"]
    assert not env.hub.calls     # nothing ran yet
    bad = await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True,
                                                                      "arguments": {"prompt": "a fox", "aspect": "5:4"}})
    assert bad.status_code == 422 and env.agent.store.thread(tid)["state"] == "waiting"
    r = await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True,
                                                                    "arguments": {"prompt": "a fox", "aspect": "16:9"}})
    assert r.status_code == 202
    await env.settle(tid)
    assert env.hub.calls[-1]["arguments"]["aspect"] == "16:9"
    res = env.payloads(tid, "tool_result")[-1]
    assert res["status"] == "done" and res["outputs"][0]["n"] == 1 and res["outputs"][0]["kind"] == "image"
    assert "#1" in res["content"]
    assert env.payloads(tid, "assistant")[-1]["text"] == "Here's your fox (#1)."


async def test_allow_in_this_chat_reaches_the_hub_and_ends_with_the_chat(env):
    """Plan 25.2: the card's "Allow in this chat" is `remember: thread` on the hub's approval, the decision
    names the grant, and deleting the chat ends its grants."""
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "a fox"}}]}, {"text": "Done (#1)."})
    await env.send(tid, "a fox image")
    ap = env.payloads(tid, "approval")[-1]
    r = await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True, "remember": "thread"})
    assert r.status_code == 202
    await env.settle(tid)
    assert env.hub.decisions[-1]["remember"] == "thread" and env.hub.decisions[-1]["confirm"] is False
    d = env.payloads(tid, "decision")[-1]
    assert d["remember"] == "thread" and d["grant"] == "gr_" + ap["approval_id"]
    assert (await env.client.delete(f"/v1/threads/{tid}")).status_code == 200
    assert env.hub.ended_grants == [tid]


async def test_denied_card(env):
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "a fox"}}]},
                    {"text": "Okay, I won't make it. What would you like instead?", "match": "denied_by_user"})
    await env.send(tid, "a fox image")
    ap = env.payloads(tid, "approval")[-1]
    await env.client.post(f"/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": False, "reason": "not now"})
    await env.settle(tid)
    res = env.payloads(tid, "tool_result")[-1]
    assert res["status"] == "denied" and res["error"]["detail"] == "not now"
    assert not env.hub.calls
    assert "won't make it" in env.payloads(tid, "assistant")[-1]["text"]


async def test_card_decided_in_the_hub_popover_continues_the_thread(env):
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "an owl"}}]}, {"text": "Owl ready."})
    await env.send(tid, "an owl")
    ap = env.payloads(tid, "approval")[-1]
    await asyncio.sleep(0.3)   # the agent's hub event stream is connected
    async with httpx.AsyncClient(base_url=env.hub_url) as c:      # as the hub's popover would
        await c.post(f"/api/approvals/{ap['approval_id']}", json={"approve": True})
    for _ in range(200):
        if env.payloads(tid, "assistant"):
            break
        await asyncio.sleep(0.05)
    await env.settle(tid)
    assert env.payloads(tid, "decision")[-1]["approve"] is True
    assert env.payloads(tid, "assistant")[-1]["text"] == "Owl ready."


async def test_action_button_runs_without_a_model_call(env):
    tid = await env.thread()
    n = len(env.model.received)
    r = await env.client.post(f"/v1/threads/{tid}/action", json={"tool": "fake_make_image", "arguments": {"prompt": "button fox", "aspect": "16:9"}})
    assert r.status_code == 202
    await env.settle(tid)
    assert len(env.model.received) == n          # no model call
    assert env.hub.calls[-1] == {"name": "fake_make_image", "arguments": {"prompt": "button fox", "aspect": "16:9"}, "mode": "accept_edits",
                                 "call_id": env.hub.calls[-1]["call_id"]}
    assert env.payloads(tid, "tool_call")[-1]["by"] == "user"
    assert env.payloads(tid, "tool_result")[-1]["outputs"][0]["n"] == 1
    env.model.queue({"text": "I see you made a fox."})
    await env.send(tid, "nice, what next?")
    msgs = env.model.received[-1]["messages"]
    assert [m["role"] for m in msgs[1:]] == ["user", "assistant", "tool", "user"]    # the model sees the button's call
    assert "pressed a button" in msgs[1]["content"] and "fake_make_image" in msgs[1]["content"]


async def test_ask_modes(env):
    auto = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "x"}}]}, {"text": "made"},
                    {"tool_calls": [{"name": "fake_wipe", "arguments": {"id": "1"}}]})
    await env.send(auto, "make x")
    assert not env.payloads(auto, "approval") and env.hub.calls[-1]["mode"] == "auto"
    await env.send(auto, "wipe 1")
    assert env.payloads(auto, "approval")[-1]["risk"] == "destructive"     # destructive still asks
    ro = await env.thread(mode="read_only")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "y"}}]}, {"text": "I can't in read-only."})
    await env.send(ro, "make y")
    assert env.payloads(ro, "tool_result")[-1]["status"] == "denied"
    assert env.agent.store.thread(ro)["state"] == "idle"


async def test_stop_while_a_card_waits_stays_stopped(env):
    """Stop dismissed the card, then the hub's 'denied' event came back and restarted the turn
    (found on a live thread: the model carried on after the user's Stop)."""
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "an owl"}}]}, {"text": "Should not appear."})
    await env.send(tid, "an owl")
    assert env.agent.store.thread(tid)["state"] == "waiting"
    await asyncio.sleep(0.3)   # the agent's hub event stream is connected
    n = len(env.model.received)
    r = await env.client.post(f"/v1/threads/{tid}/cancel")
    assert r.status_code == 200
    await asyncio.sleep(0.6)   # the hub's approval event arrives
    await env.settle(tid)
    assert env.agent.store.thread(tid)["state"] == "idle"
    assert len(env.model.received) == n
    assert len(env.payloads(tid, "tool_result")) == 1
    assert not [a for a in env.payloads(tid, "assistant") if a["text"] == "Should not appear."]


async def test_auto_sends_the_users_own_words_for_the_judge(env):
    """Plan 30.3: in Auto the hub's judge reads only what the user typed; the agent sends it as origin.said."""
    auto = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "x"}}]}, {"text": "made"},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "y"}}]}, {"text": "made"})
    await env.send(auto, "make x")
    await env.send(auto, "now make y " + "z" * 3000)
    said = env.hub.attempts[-1]["origin"]["said"]
    assert said[0] == "make x" and said[1].startswith("now make y") and len(said[1]) == 2000
    manual = await env.thread(mode="manual")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "w"}}]}, {"text": "ok"})
    await env.send(manual, "make w")
    assert "said" not in (env.hub.attempts[-1]["origin"] or {})


async def test_the_judges_verdict_reaches_the_step(env):
    """Plan 30.5: the hub's `judge` on a result (or on a call that ran long) is kept on the tool_result event."""
    tid = await env.thread(mode="auto")
    j = {"verdict": "allow", "reason": "pytest runs the tests", "source": "rules", "why": "Auto: ran (judged safe: pytest runs the tests)"}
    ev = env.agent._result(tid, "c1", "workspace_run", {"status": "done", "result": {"exit_code": 0}, "judge": j})
    assert ev["payload"]["judge"] == j
    ev = env.agent._result(tid, "c2", "workspace_run", {"status": "done", "result": {}})
    assert "judge" not in ev["payload"]
