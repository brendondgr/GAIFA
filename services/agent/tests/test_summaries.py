"""Plan 28.5, conversations you can look up: a chat quiet for `idle_min` is summarised (never with a document's
text), sent to the embed mod's `chats`, rewritten when it continues, skipped for dry runs and `no_learn`, forgotten
when deleted, and found by `GET /v1/chats/search` and the `chat_search` tool."""

from __future__ import annotations

import json

from agent.summaries import Summaries, chat_text

SECRET = "The vault combination is 31-7-22."


class Clock:
    def __init__(self) -> None:
        import time
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


def summaries(env, idle_min: float = 30) -> tuple[Summaries, Clock]:
    clock = Clock()
    s = Summaries(env.agent, idle_min, clock=clock)
    env.agent.summaries = s                                         # the routes and the tool use this one
    return s, clock


async def chat(env, text: str, reply: str, **kw) -> str:
    tid = await env.thread(mode="auto", **kw)
    env.model.queue({"text": reply})
    await env.send(tid, text)
    return tid


async def test_quiet_chats_are_summarised_and_sent(env):
    s, clock = summaries(env)
    tid = await chat(env, "Make me a picture of a fox in the snow", "Here is your fox picture.")
    assert s.due() == []                                            # it was just active
    clock.t += 31 * 60
    assert [t["id"] for t in s.due()] == [tid]
    env.model.queue({"text": "The user asked for a fox picture in snow; the agent made one."})
    assert await s.check() == 1
    got = s.get(tid)
    assert got["summary"].startswith("The user asked for a fox") and got["sent"] == 1
    assert env.hub.chats[tid]["summary"] == got["summary"]
    prompt = env.model.received[-1]["messages"][0]["content"]
    assert "Summarise this chat" in prompt and "USER: Make me a picture of a fox" in prompt
    assert s.due() == []                                            # nothing new since
    r = await env.client.get(f"/v1/threads/{tid}/summary")
    assert r.status_code == 200 and r.json()["summary"] == got["summary"]


async def test_a_chat_that_continues_is_summarised_again(env):
    s, clock = summaries(env)
    tid = await chat(env, "Plan a trip to Lisbon", "Here's a plan.")
    clock.t += 31 * 60
    env.model.queue({"text": "Planned a Lisbon trip."})
    await s.check()
    env.model.queue({"text": "Added a day in Sintra."})
    await env.send(tid, "Add a day trip to Sintra")
    clock.t = env.agent.store.events(tid)[-1]["ts"] + 5 * 60        # five minutes after the new message
    assert s.due() == []                                            # changed, but not quiet long enough
    clock.t += 30 * 60
    env.model.queue({"text": "Planned a Lisbon trip with a day in Sintra."})
    assert await s.check() == 1
    assert s.get(tid)["summary"] == "Planned a Lisbon trip with a day in Sintra."
    assert env.hub.chats[tid]["summary"] == "Planned a Lisbon trip with a day in Sintra."


async def test_documents_appear_by_name_only(env):
    s, clock = summaries(env)
    doc = env.hub.doc("vault-notes.txt", text=SECRET + "\n" + "filler line\n" * 5, kind="text", subtype="plain")
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "hub_read_document", "arguments": {"ref": "#1"}}]}, {"text": "Read it."})
    await env.send(tid, "What does the note say?", attachments=[doc])
    text = chat_text(env.agent.store.events(tid))
    assert "vault-notes.txt" in text and "31-7-22" not in text      # inline text and the read result stay out
    clock.t += 31 * 60
    env.model.queue({"text": "The user asked about an attached note, vault-notes.txt."})
    await s.check()
    assert "31-7-22" not in env.model.received[-1]["messages"][0]["content"]


async def test_dry_runs_no_learn_and_empty_chats_are_skipped(env):
    s, clock = summaries(env)
    await chat(env, "eval task", "ok", settings={"dry_run": True})
    await chat(env, "private", "ok", settings={"no_learn": True})
    await env.thread(mode="auto")                                   # never used
    clock.t += 31 * 60
    assert s.due() == []


async def test_deleting_a_chat_forgets_its_summary(env):
    s, clock = summaries(env)
    tid = await chat(env, "Make a song about rain", "Here it is.")
    clock.t += 31 * 60
    env.model.queue({"text": "Wrote a song about rain."})
    await s.check()
    assert tid in env.hub.chats
    assert (await env.client.delete(f"/v1/threads/{tid}")).status_code == 200
    assert s.get(tid) is None and tid not in env.hub.chats and tid in env.hub.chat_deletes


async def test_unsent_summaries_are_retried(env):
    s, clock = summaries(env)
    env.hub.embed_up = False
    tid = await chat(env, "Make a logo", "Done.")
    clock.t += 31 * 60
    env.model.queue({"text": "Made a logo."})
    await s.check()
    assert s.get(tid)["sent"] == 0
    env.hub.embed_up = True
    await s.check()                                                 # nothing due, but the unsent one goes
    assert s.get(tid)["sent"] == 1 and env.hub.chats[tid]["summary"] == "Made a logo."


async def test_search_route_and_the_chat_search_tool(env):
    s, clock = summaries(env)
    old = await chat(env, "Help me with the quarterly tax estimate", "Here's the estimate.")
    clock.t += 31 * 60
    env.model.queue({"text": "Worked out the quarterly tax estimate for the user."})
    await s.check()
    r = (await env.client.get("/v1/chats/search", params={"q": "tax estimate"})).json()["results"]
    assert r[0]["thread_id"] == old and r[0]["link"] == f"#/chat/{old}" and r[0]["date"]
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "chat_search", "arguments": {"query": "tax estimate"}}]},
                    {"text": "You did that in an earlier chat."})
    await env.send(tid, "Where did we do the taxes?")
    [res] = [p for p in env.payloads(tid, "tool_result") if p["name"] == "chat_search"]
    body = json.loads(res["content"])
    assert res["status"] == "done" and body["chats"][0]["thread_id"] == old
    assert "quarterly tax estimate" in body["chats"][0]["summary"]
    env.hub.embed_up = False
    assert (await env.client.get("/v1/chats/search", params={"q": "x"})).status_code == 503
