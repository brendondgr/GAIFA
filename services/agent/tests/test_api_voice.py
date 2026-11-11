"""Plan voice-speech-model 2.3: a voice session's context, and its turns written into the chat."""

from __future__ import annotations

from agent.api_voice import history


async def test_a_voice_turn_is_in_the_chat_and_in_the_next_prompt(env):
    tid = await env.thread()
    r = await env.client.post(f"/v1/threads/{tid}/voice-turn", json={
        "user": "What is the capital of France?", "assistant": "Paris.", "model": "voice/lfm3-omni-2b", "first_audio_ms": 92})
    assert r.status_code == 201 and r.json()["assistant_seq"] > r.json()["user_seq"]
    assert env.types(tid)[-2:] == ["user", "assistant"]
    user, reply = env.payloads(tid, "user")[-1], env.payloads(tid, "assistant")[-1]
    assert user == {"text": "What is the capital of France?", "via": "voice"}
    assert reply["via"] == "voice" and reply["model"] == "voice/lfm3-omni-2b" and reply["first_audio_ms"] == 92
    assert env.agent.store.thread(tid)["title"] == "What is the capital of France?"
    assert not env.agent.running(tid) and env.model.received == []          # no model call was made for it

    env.model.queue({"text": "About two million."})
    await env.send(tid, "And how many people live there?")
    msgs = env.model.received[-1]["messages"]
    said = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert said[:2] == [("user", "What is the capital of France?"), ("assistant", "Paris.")]
    assert said[2][1].startswith("And how many people live there?")


async def test_an_interrupted_turn_and_one_with_no_answer(env):
    tid = await env.thread()
    await env.client.post(f"/v1/threads/{tid}/voice-turn", json={"user": "Tell me a story", "assistant": "Once upon a…",
                                                                  "interrupted": True})
    assert env.payloads(tid, "assistant")[-1]["interrupted"] is True
    r = await env.client.post(f"/v1/threads/{tid}/voice-turn", json={"user": "Never mind"})
    assert r.json()["assistant_seq"] is None and env.types(tid)[-1] == "user"
    assert (await env.client.post(f"/v1/threads/{tid}/voice-turn", json={"user": ""})).status_code == 422
    assert (await env.client.post("/v1/threads/t_nope/voice-turn", json={"user": "hi"})).status_code == 404


async def test_refused_while_the_chats_turn_runs(env):
    tid = await env.thread()
    env.model.queue({"text": "thinking about it", "delay": 0.5})
    await env.send(tid, "a typed question", wait=False)
    r = await env.client.post(f"/v1/threads/{tid}/voice-turn", json={"user": "hello", "assistant": "hi"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "turn_running"
    await env.settle(tid)


async def test_the_context(env):
    tid = await env.thread()
    env.model.queue({"text": "Biscuit is a lovely name."})
    await env.send(tid, "My dog is called Biscuit.")
    await env.client.post(f"/v1/threads/{tid}/voice-turn", json={"user": "And my cat is Pepper.", "assistant": "Noted."})
    c = (await env.client.get(f"/v1/threads/{tid}/voice-context")).json()
    assert [(t["role"], t["text"]) for t in c["history"]] == [
        ("user", "My dog is called Biscuit."), ("assistant", "Biscuit is a lovely name."),
        ("user", "And my cat is Pepper."), ("assistant", "Noted.")]
    assert isinstance(c["instructions"], str)
    assert (await env.client.get("/v1/threads/t_nope/voice-context")).status_code == 404


def test_the_history_keeps_the_newest_inside_its_budget():
    events = []
    for i in range(1, 201, 2):
        events.append({"seq": i, "type": "user", "payload": {"text": f"question {i} " + "x" * 300}})
        events.append({"seq": i + 1, "type": "assistant", "payload": {"text": f"answer {i} " + "y" * 300}})
    h = history(events)
    assert sum(len(t["text"]) for t in h) <= 24000 and h[-1]["text"].startswith("answer 199") and len(h) < 200
    steps = [{"seq": 1, "type": "user", "payload": {"text": "go"}},
             {"seq": 2, "type": "assistant", "payload": {"text": "First I look."}},
             {"seq": 3, "type": "tool_call", "payload": {"name": "x"}},
             {"seq": 4, "type": "assistant", "payload": {"text": "Then I answer."}}]
    assert history(steps) == [{"role": "user", "text": "go"}, {"role": "assistant", "text": "First I look. Then I answer."}]
