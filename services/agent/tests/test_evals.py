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
    assert len(TASKS) == 47 and len({t.id for t in TASKS}) == 47
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


async def test_attach_uploads_to_the_hub_and_attaches_to_the_first_turn(env):
    """plan 24.5: the pdf_page7 task's file goes to the hub's upload route and rides on the first message."""
    task = next(t for t in TASKS if t.id == "pdf_page7")
    h = Harness("http://agent", "main", dry_run=True, transport=httpx.ASGITransport(app=env.app), hub=env.hub_url)
    env.model.queue({"tool_calls": [{"name": "hub_search_document", "arguments": {"ref": "#1", "query": "cat"}}]},
                    {"text": "The cat is called Biscuit (#1 p.7)."})
    run = await h.run(task)
    [user] = run.of("user")
    assert user["docs"][0]["name"] == "north-rock-inspection.pdf" and user["attachments"] == [user["docs"][0]["id"]]
    row = grade(task, run)
    assert row["ok"], row["checks"]
    await h.close()


def test_the_eval_report_has_the_cat_only_on_page_7():
    import io
    import re

    from evals.docs import TOPICS, lighthouse_report
    data = lighthouse_report()
    assert data.startswith(b"%PDF-1.4") and data.count(b"/Type /Page ") == len(TOPICS) == 20
    streams = re.findall(rb"stream\n(.*?)\nendstream", data, re.S)
    assert [i for i, s in enumerate(streams) if b"Biscuit" in s] == [6]
    assert io.BytesIO(data).getbuffer().nbytes > 20 * 1500
