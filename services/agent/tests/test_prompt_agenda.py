"""calendar 5.2: today's calendar in the prompt: the part and its place (after Environment), absent when the mod is
off or turned off in the chat, a project's id passed, and kept 20 s."""

from __future__ import annotations

from agent import context as ctx

from .test_environments import system_prompt

AGENDA = "Today, Mon 9 Nov:\n- 15:00–16:00 Dentist (Personal) [c_1]\nTomorrow, Tue 10 Nov:\n- nothing"


async def test_the_part_and_its_place(env):
    ctx._AGENDA.clear()
    env.hub.calendar = AGENDA
    tid = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(tid, "am I free at 3?")
    sp = system_prompt(env)
    assert "## Your calendar (today and tomorrow" in sp and "15:00–16:00 Dentist" in sp
    assert sp.index("## Environment") < sp.index("## Your calendar")
    assert env.hub.agenda_calls[-1]["project"] is None


async def test_absent_when_off_or_turned_off(env):
    ctx._AGENDA.clear()
    tid = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(tid, "hi")
    assert "Your calendar" not in system_prompt(env)
    env.hub.calendar = AGENDA
    off = await env.thread(settings={"disabled": ["calendar"]})
    env.model.queue({"text": "ok"})
    await env.send(off, "hi")
    assert "Your calendar" not in system_prompt(env)
    env.hub.calendar = ""                                   # the setting off: an empty text
    ctx._AGENDA.clear()
    t3 = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(t3, "hi")
    assert "Your calendar" not in system_prompt(env)


async def test_a_projects_dates(env):
    ctx._AGENDA.clear()
    env.hub.calendar = AGENDA
    p = (await env.client.post("/v1/projects", json={"name": "Thesis"})).json()
    tid = (await env.client.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    env.model.queue({"text": "ok"})
    await env.send(tid, "what's due?")
    assert f"This project's dates: {p['id']}" in system_prompt(env)


async def test_kept_twenty_seconds():
    ctx._AGENDA.clear()

    class Hub:
        n = 0

        async def calendar_agenda(self, day, project):
            Hub.n += 1
            return {"text": f"v{Hub.n}"}

    svc = [{"id": "calendar", "state": "ready"}]
    assert await ctx.chat_agenda(Hub(), svc, set(), None, now=100.0) == "v1"
    assert await ctx.chat_agenda(Hub(), svc, set(), None, now=110.0) == "v1"
    assert await ctx.chat_agenda(Hub(), svc, set(), None, now=125.0) == "v2"
