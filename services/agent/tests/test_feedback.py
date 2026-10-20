"""21.4: thumbs on outputs and replies; a chat that opted out passes no_learn to the hub."""


async def test_thumbs_on_an_output_and_a_reply(env):
    env.model.queue({"text": "hello"})
    tid = await env.thread()
    await env.send(tid, "hi")
    seq = env.agent.store.events(tid, types=["assistant"])[-1]["seq"]
    r = await env.client.post(f"/v1/threads/{tid}/feedback", json={"value": "down", "seq": seq, "note": "too long"})
    assert r.status_code == 200 and r.json()["seq"]
    r = await env.client.post(f"/v1/threads/{tid}/feedback", json={"value": "up", "output_id": "output:abc123abc123"})
    assert r.status_code == 200
    fb = env.payloads(tid, "feedback")
    assert fb[0] == {"value": "down", "note": "too long", "seq": seq} and fb[1]["output_id"] == "abc123abc123"
    assert env.hub.feedback[-1]["output_id"] == "abc123abc123" and env.hub.feedback[-1]["value"] == "up"
    assert (await env.client.post(f"/v1/threads/{tid}/feedback", json={"value": "up"})).status_code == 422


async def test_no_learn_reaches_the_hub(env):
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "a"}}]}, {"text": "ok"})
    tid = await env.thread(settings={"pinned": ["fake"], "no_learn": True})
    await env.send(tid, "get a")
    assert env.hub.attempts[-1]["origin"]["no_learn"] is True
