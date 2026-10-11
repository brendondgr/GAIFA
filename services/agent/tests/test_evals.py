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


def test_eval_tasks_in_six_groups():
    assert len(TASKS) == 32 and len({t.id for t in TASKS}) == 32
    assert {t.group for t in TASKS} == {"single", "chain", "must-ask", "no-ask", "safety", "context"}
