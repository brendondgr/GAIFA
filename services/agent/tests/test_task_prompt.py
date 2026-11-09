"""Plan scheduled-tasks 2.4: a run's Scheduled task part and its notes in the prompt, the task's skills always on,
`task_note` (in runs only, with its limits), `ask_user` answered at once when no one is there, the memory switches,
and the memory learner skipping runs."""

from __future__ import annotations

import json

from agent.memory import profile
from agent.projects.memory import entity_of
from agent.tasks.store import NOTES_MAX

from .test_environments import system_prompt

DAILY = {"kind": "daily", "time": "07:00"}


async def _task(c, **kw):
    r = await c.post("/v1/tasks", json={"name": "Digest", "schedule": DAILY, "instructions": "Summarise the feed.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def _run(env, kid, test=False):
    run = (await env.client.post(f"/v1/tasks/{kid}/{'test' if test else 'run'}")).json()
    await env.settle(run["thread_id"])
    return env.agent.scheduled.run(run["id"])


def tool_names(env) -> set[str]:
    return {t["function"]["name"] for t in env.model.received[-1].get("tools") or []}


async def test_the_prompt_part_and_notes(env):
    t = await _task(env.client)
    env.agent.scheduled.add_note(t["id"], "The feed is at /srv/feed.xml.")
    await _run(env, t["id"])
    sp = system_prompt(env)
    assert "## Scheduled task" in sp and "run of the scheduled task **Digest** (Every day at 07:00)" in sp
    assert "no one is watching" in sp and "The feed is at /srv/feed.xml." in sp
    assert "task_note" in tool_names(env)
    await _run(env, t["id"], test=True)
    assert "a test run" in system_prompt(env) and "no one is watching" not in system_prompt(env)
    plain = await env.thread()
    await env.send(plain, "hello")
    assert "Scheduled task" not in system_prompt(env) and "task_note" not in tool_names(env)


async def test_skills_always_on(env):
    (env.tmp / "data" / "agent" / "skills" / "digest").mkdir(parents=True, exist_ok=True)
    (env.tmp / "data" / "agent" / "skills" / "digest" / "SKILL.md").write_text(
        "---\nname: digest\ndescription: How to write a digest\n---\nThree bullets, newest first.\n")
    t = await _task(env.client, skills=["digest"])
    await _run(env, t["id"])
    sp = system_prompt(env)
    assert "Skills this scheduled task uses" in sp and "Three bullets, newest first." in sp


async def test_task_note(env):
    t = await _task(env.client)
    env.model.queue({"tool_calls": [{"name": "task_note", "arguments": {"action": "add", "text": "Use the RSS feed, not the page."}}]},
                    {"text": "Noted."})
    run = await _run(env, t["id"])
    notes = env.agent.scheduled.notes(t["id"])
    assert [n["text"] for n in notes] == ["Use the RSS feed, not the page."] and notes[0]["thread_id"] == run["thread_id"]
    nid = notes[0]["id"]
    env.model.queue({"tool_calls": [{"name": "task_note", "arguments": {"action": "replace", "id": nid, "text": "The feed moved."}}]},
                    {"tool_calls": [{"name": "task_note", "arguments": {"action": "remove", "id": "n_nope"}}]}, {"text": "ok"})
    run = await _run(env, t["id"])
    assert [n["text"] for n in env.agent.scheduled.notes(t["id"])] == ["The feed moved."]
    res = [e["payload"] for e in env.events(run["thread_id"], "tool_result")]
    assert res[0]["status"] == "done" and res[1]["error"]["code"] == "unknown_note"
    for i in range(NOTES_MAX - 1):
        env.agent.scheduled.add_note(t["id"], f"note {i}")
    env.model.queue({"tool_calls": [{"name": "task_note", "arguments": {"action": "add", "text": "one more"}}]}, {"text": "ok"})
    run = await _run(env, t["id"])
    assert env.events(run["thread_id"], "tool_result")[0]["payload"]["error"]["code"] == "too_many_notes"
    # a plain chat has no task_note: the call goes nowhere
    plain = await env.thread()
    env.model.queue({"tool_calls": [{"name": "task_note", "arguments": {"action": "add", "text": "x"}}]}, {"text": "ok"})
    await env.send(plain, "hello")
    assert env.events(plain, "tool_result")[0]["payload"]["error"]["code"] == "not_a_task_run"


async def test_ask_user_unattended(env):
    t = await _task(env.client)
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": {"questions": [{"question": "Which feed?", "options": [
        {"label": "A"}, {"label": "B"}]}]}}]}, {"text": "I picked A."})
    run = await _run(env, t["id"])
    assert run["state"] == "done" and run["refused"] == 1
    res = env.events(run["thread_id"], "tool_result")[0]["payload"]
    assert res["error"]["code"] == "unattended" and not env.events(run["thread_id"], "question")


async def test_memory_switches(env):
    m = env.agent.memory
    m.add_fact("The user likes short digests.", about=["user"], kind="preference", source="stated", by="user")
    p = (await env.client.post("/v1/projects", json={"name": "Glacier thesis"})).json()
    e = entity_of(m, p["id"])
    m.add_fact("The thesis draft is due on December 1.", about=[e["id"]], kind="fact", source="stated", by="user")
    text, _ = profile.build(m, None, project=p["id"])
    assert "short digests" in text and "December 1" in text
    text, shown = profile.build(m, None, project=p["id"], user=False)
    assert "short digests" not in text and "Projects:" not in text and "December 1" in text
    text, shown = profile.build(m, None, project=p["id"], own_project=False)
    assert "short digests" in text and "December 1" not in text and "Glacier" not in text
    got = await profile.recall(m, env.agent.hub, "when is the thesis draft due", set(), project=p["id"], own_project=False)
    assert all("December" not in r["text"] for r in got)
    got = await profile.recall(m, env.agent.hub, "what kind of digests does the user like", set(), project=p["id"], user=False)
    assert all("digests" not in r["text"] for r in got)
    # through a run
    t = await _task(env.client, project_id=p["id"], use_profile=False)
    run = await _run(env, t["id"])
    sp = system_prompt(env)
    assert "short digests" not in sp and "December 1" in sp
    s = env.agent.store.thread(run["thread_id"])["settings"]
    assert s["use_profile"] is False and s["use_project_memory"] is True


async def test_the_memory_learner_skips_runs(env):
    t = await _task(env.client)
    run = await _run(env, t["id"])
    env.agent.memory_learner.idle_s = 0
    due = [x["id"] for x in env.agent.memory_learner.due()]
    assert run["thread_id"] not in due
    assert json.dumps(env.agent.store.thread(run["thread_id"])["settings"]).count('"no_learn": true') == 1
