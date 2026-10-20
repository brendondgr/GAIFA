"""21.4: turn records: one row per turn from the event log, with tokens and timing; usage events
carry seconds and the stored event its tokens."""


async def test_a_turn_row_with_tokens_and_timing(env):
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "a"}}]}, {"text": "done"})
    tid = await env.thread(settings={"pinned": ["fake"]})
    await env.send(tid, "get a")
    await env.send(tid, "thanks")
    rows = (await env.client.get(f"/v1/threads/{tid}/turns")).json()
    assert [r["turn"] for r in rows] == [1, 2]
    assert rows[0]["steps"] == 2 and rows[0]["tool_calls"] == 1 and rows[0]["outcome"] == "done"
    assert rows[0]["prompt_tokens"] > 0
    usage = env.payloads(tid, "usage")[0]
    assert "seconds" in usage
    stored = env.agent.store.events(tid, types=["usage"])
    assert all(e.get("tokens", 0) >= 0 for e in stored)


def test_summarize_counts_edits_and_denials():
    from agent.records import summarize
    ev = lambda t, p, ts=1.0: {"type": t, "payload": p, "ts": ts}  # noqa: E731
    rows = summarize([ev("user", {}), ev("tool_call", {"id": "a"}), ev("decision", {"id": "a", "approve": True, "arguments": {"x": 1}}),
                      ev("tool_call", {"id": "b"}), ev("decision", {"id": "b", "approve": False}), ev("state", {"state": "idle"}, 2.0)])
    assert rows[0]["edits"] == 1 and rows[0]["denials"] == 1 and rows[0]["ended"] == 2.0
