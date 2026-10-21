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
    assert len(TASKS) == 53 and len({t.id for t in TASKS}) == 53
    assert {t.group for t in TASKS} == {"single", "chain", "capability", "preference", "must-ask", "no-ask", "safety", "context"}


async def test_attachments_go_with_the_first_turn_only(env, monkeypatch):
    """plan 29.3: `attach` gets the hub's URL and returns output ids for the first message."""
    monkeypatch.setenv("AIHUB_URL", "http://127.0.0.1:7000")
    assert Harness("http://127.0.0.1:7000/api/s/agent", "m").hub_url() == "http://127.0.0.1:7000"
    h = Harness("http://agent", "main", dry_run=True, transport=httpx.ASGITransport(app=env.app))
    env.model.queue({"text": "ok"}, {"text": "ok again"})
    seen = []

    async def attach(hub):
        seen.append(hub)
        return ["rec1"]

    run = await h.run(Task("a1", "chain", ["summarise it", "thanks"], [], attach=attach))
    users = [e["payload"] for e in run.events if e["type"] == "user"]
    assert seen == ["http://127.0.0.1:7000"]
    assert users[0].get("attachments") == ["rec1"] and "attachments" not in users[1]
    await h.close()


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


def test_web_two_sources_grades_citations_and_the_search_card():
    """plan 26.2: passes when search ran on its grant (no card), both pages were fetched and the reply
    gives both facts with both sites; a search that showed a card fails it."""
    from evals.harness import Run
    from evals.tasks import FARES, WINTER

    task = next(t for t in TASKS if t.id == "web_two_sources")
    assert task.settings == {"dry_run": True}

    def ev(t, **p):
        return {"type": t, "payload": p}

    def run(search_card: bool) -> Run:
        events = [ev("tool_call", id="c1", name="web_search", by="model", arguments={"query": "kestrel ferry"})]
        if search_card:
            events.append(ev("approval", id="c1", approval_id="ap1", tool="web_search", risk="network"))
        events.append(ev("tool_result", id="c1", name="web_search", status="done"))
        for n, (cid, url) in enumerate((("c2", WINTER), ("c3", FARES)), 1):
            events += [ev("tool_call", id=cid, name="web_fetch", by="model", arguments={"url": url}),
                       ev("approval", id=cid, approval_id="ap" + cid, tool="web_fetch", risk="network"),
                       ev("tool_result", id=cid, name="web_fetch", status="done", outputs=[{"n": n, "kind": "text"}])]
        events.append(ev("assistant", text="The first Sunday ferry leaves at 08:40 ([#1](https://kestrel-ferries.example/timetables/winter-2026)); "
                                            "an adult return with a bike is £11.90 ([#2](https://harbour-council.example/transport/ferry-fares))."))
        return Run(task="web_two_sources", model="m", events=events)

    ok = grade(task, run(False))
    assert ok["ok"], ok["checks"]
    bad = grade(task, run(True))
    assert not bad["ok"] and [c["check"] for c in bad["checks"] if not c["ok"]] == ["web_search ran without a card"]


def test_library_cases_grade_what_they_should():
    """plan 28.3: the two library cases pass on a run that searched and answered, and fail on one that didn't."""
    import json as _json

    from evals.harness import Run
    from evals.library import ANSWER_DOC, ANSWER_PAGE, STATIONS, TASKS as LIB, station_report

    def ev(t, **p):
        return {"type": t, "payload": p}
    docs, car = {t.id: t for t in LIB}["library_ten_docs"], {t.id: t for t in LIB}["library_red_car"]
    hits = {"results": [{"output": "output:abc", "title": "IMG_2041.png", "kind": "image", "score": 0.75},
                        {"output": "output:def", "title": "IMG_2042.png", "kind": "image", "score": 0.6}]}
    good = Run("library_red_car", "m", events=[
        ev("tool_call", id="1", name="embed_library_search", arguments={"query": "red car"}, by="model"),
        ev("tool_result", id="1", name="embed_library_search", status="done",
           content=_json.dumps({"status": "done", "result": hits})),                # as the hub sends it
        ev("assistant", text="It's IMG_2041.png (output:abc).")])
    assert grade(car, good)["ok"]
    bad = Run("library_red_car", "m", events=[ev("assistant", text="I couldn't find it.")])
    assert not grade(car, bad)["ok"]
    answer = Run("library_ten_docs", "m", events=[
        ev("user", text="…", docs=[{"ref": f"#{i}", "id": f"d{i}"} for i in range(1, 11)]),
        ev("tool_call", id="1", name="embed_library_search", arguments={"query": "pet", "thread_only": True}, by="model"),
        ev("tool_result", id="1", name="embed_library_search", status="done", content="{}"),
        ev("assistant", text=f"Yes: {STATIONS[ANSWER_DOC - 1]} keeps a ginger cat called Saffron (#{ANSWER_DOC} p.{ANSWER_PAGE}).")])
    assert grade(docs, answer)["ok"]
    assert b"Saffron" not in station_report(1) and len(station_report(ANSWER_DOC)) > 40_000
