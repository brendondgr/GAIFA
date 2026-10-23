"""Plan 44.2: a job's live progress reaches the chat as it changes, not every 15 s."""

from __future__ import annotations

import time


async def test_live_progress_reaches_the_chat_at_each_step(env):
    seen: list[tuple[float, dict]] = []
    orig = env.agent.transient

    def spy(tid, type_, payload):
        if type_ == "progress":
            seen.append((time.monotonic(), payload))
        return orig(tid, type_, payload)

    env.agent.transient = spy
    env.model.queue({"tool_calls": [{"name": "fake_live", "arguments": {"prompt": "fox"}}]}, {"text": "Done: #1."})
    tid = await env.thread(mode="auto")
    t0 = time.monotonic()
    await env.send(tid, "make a fox")
    steps = [p["live"]["step"] for _, p in seen if p.get("live")]
    assert steps[-2:] == [2, 3] and steps == sorted(set(steps))   # the call's first 2 s cover step 1
    assert seen[-1][1]["live"]["preview"] == {"url": "/api/s/fake/v1/p", "seq": 3}
    assert seen[-1][0] - t0 < 6          # each step as it happened (the poll waits 15 s without `changed`)
