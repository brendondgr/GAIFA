"""13.5: the eval harness runs scripted conversations headless: it answers questions and cards from
the task's script and grades outcomes (here against the scripted model and the stand-in hub)."""

from __future__ import annotations

import httpx

from evals.harness import Harness, Task, grade, summary
from evals.tasks import TASKS, asked_before, kinds, not_asked, ran, typed


async def test_harness_answers_and_grades(env):
    h = Harness("http://agent", "main", dry_run=False, transport=httpx.ASGITransport(app=env.app))
    env.model.queue({"tool_calls": [{"name": "ask_user", "arguments": {"questions": [{"question": "What subject?", "options": [{"label": "A cat"}, {"label": "A dog"}]}]}}]},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "a lighthouse"}}]},
                    {"text": "Here is your lighthouse (#1)."})
    task = Task("t1", "single", ["Make me an image."], [asked_before("fake_make_image"), ran("fake_make_image"), kinds("image")],
                answer=typed("a lighthouse"))
    run = await h.run(task)
    row = grade(task, run)
    assert row["ok"], row
    assert run.of("answer")[0]["answers"] == {"What subject?": "a lighthouse"}
    # a reply that names an output that doesn't exist fails "no invented outputs"
    env.model.queue({"text": "Done, see #4."})
    bad = Task("t2", "single", ["hello"], [not_asked()])
    row2 = grade(bad, await h.run(bad))
    assert not row2["ok"] and [c for c in row2["checks"] if not c["ok"]][0]["check"] == "no invented outputs"
    s = summary([{**row, "run": 1}, {**row, "run": 2}, {**row2, "run": 1}], runs=2)
    assert s["tasks"] == 2 and s["pass_k"] == 1 and s["pass_1_rate"] == round(2 / 3, 3)
    await h.close()


def test_eval_tasks_in_eight_groups():
    assert len(TASKS) == 46 and len({t.id for t in TASKS}) == 46
    assert {t.group for t in TASKS} == {"single", "chain", "capability", "preference", "must-ask", "no-ask", "safety", "context"}


async def test_seeded_preferences_are_for_the_task_chat_and_removed(env):
    """plan 21.6: a task's preferences are seeded for its chat only (tasks run at once), then removed."""
    h = Harness("http://agent", "main", dry_run=True, transport=httpx.ASGITransport(app=env.app))
    env.model.queue({"text": "ok"})
    task = Task("p1", "preference", ["hi"], [], prefs=[{"value": "Answer in French.", "source": "stated"}])
    run = await h.run(task)
    assert "Answer in French." in env.model.received[-1]["messages"][0]["content"]
    assert env.hub.prefs == []
    await h.close()


async def test_runs_leave_no_chats_behind(env, tmp_path):
    """A run's chats are deleted when it ends (the grade reads the events it kept), with their turn
    records; `keep` leaves them. Seeds a task's setup wrote go when the harness closes."""
    from evals import cleanup

    t = httpx.ASGITransport(app=env.app)
    h = Harness("http://agent", "main", dry_run=True, transport=t)
    env.model.queue({"text": "ok"})
    run = await h.run(Task("c1", "single", ["hi"], []))
    tid = run.extra["thread"]
    assert run.events and (await h.c.get(f"/v1/threads/{tid}")).status_code == 404
    assert env.agent.store._all("SELECT * FROM turns WHERE thread_id = ?", [tid]) == []
    (tmp_path / "eval").mkdir()
    seed = tmp_path / "eval" / "120000-seed.png"
    seed.write_bytes(b"png")
    seed.with_name(seed.name + ".json").write_text("{}")
    cleanup.SEEDED.append(seed)
    await h.close()
    assert list((tmp_path / "eval").iterdir()) == [] and cleanup.SEEDED == []
    kept = Harness("http://agent", "main", dry_run=True, transport=t, keep=True)
    env.model.queue({"text": "ok"})
    run = await kept.run(Task("c2", "single", ["hi"], []))
    assert (await kept.c.get(f"/v1/threads/{run.extra['thread']}")).status_code == 200
    await kept.close()


def test_outputs_of_a_run_and_the_hub_behind_the_proxy():
    from evals import cleanup

    assert cleanup.hub_of("http://127.0.0.1:7000/api/s/agent/") == "http://127.0.0.1:7000"
    assert cleanup.hub_of("http://agent") is None
    evs = [{"type": "tool_result", "payload": {"outputs": [{"output_id": "a1"}, {"output_id": "a1"}, {"output_id": "b2"}]}},
           {"type": "assistant", "payload": {"text": "#1"}}]
    assert cleanup.output_ids(evs) == ["a1", "b2"]
