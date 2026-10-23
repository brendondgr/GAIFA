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
    assert len(TASKS) == 60 and len({t.id for t in TASKS}) == 60
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


def test_grounding_tasks_grade_what_they_should():
    """A real-world question: passes when search ran, a page it found was fetched without a card and the
    reply cites it with a fact only that page has; a fetch that asked, a URL the search didn't return, an
    answer from memory, or a search for chit-chat fails."""
    import json as _json

    from evals.harness import Run

    task = next(t for t in TASKS if t.id == "ground_product_fact")
    specs = "https://brightfield-lights.example/k7/specs"

    def ev(t, **p):
        return {"type": t, "payload": p}

    def run(fetch_url=specs, card=False, search=True, text=f"Yes, with the BF-S18 sleeve ([#1]({specs})).") -> Run:
        events = []
        if search:
            events += [ev("tool_call", id="c1", name="web_search", by="model", arguments={"query": "Brightfield K7 18650"}),
                       ev("tool_result", id="c1", name="web_search", status="done",
                          content=_json.dumps({"results": [{"title": "K7", "url": specs}]}))]
        if fetch_url:
            events.append(ev("tool_call", id="c2", name="web_fetch", by="model", arguments={"url": fetch_url}))
            if card:
                events.append(ev("approval", id="c2", approval_id="ap2", tool="web_fetch", risk="network"))
            events.append(ev("tool_result", id="c2", name="web_fetch", status="done", outputs=[{"n": 1, "kind": "text"}]))
        events.append(ev("assistant", text=text))
        return Run(task=task.id, model="m", events=events)

    def failed(r: Run, t=task) -> list[str]:
        return [c["check"] for c in grade(t, r)["checks"] if not c["ok"]]

    assert failed(run()) == []
    assert failed(run(card=True)) == ["fetched a search result without a card"]
    assert failed(run(fetch_url="https://elsewhere.example/k7", text="Yes, BF-S18 (elsewhere.example).")) == ["fetched a search result without a card"]
    assert "cites a fetched page" in failed(run(fetch_url=None, text="Yes, with the BF-S18 sleeve."))
    assert set(failed(run(search=False, fetch_url=None, text="Probably not."))) >= {"web_search ran without a card", "reply mentions BF-S18"}
    trek = next(t for t in TASKS if t.id == "ground_trek_gear")
    assert failed(run(), trek) == [n for n, _ in trek.checks if n.startswith("reply mentions")]   # only its own pages' facts
    quiet = next(t for t in TASKS if t.id == "no_search_needed")
    assert failed(run(search=False, fetch_url=None, text="Use xs.reverse()."), quiet) == []
    assert failed(run(text="Use xs.reverse()."), quiet) == ["never called web_search, web_fetch"]


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

    def ranked(*titles):            # one search whose hits come in this order
        res = {"results": [{"output": f"output:{i:012x}", "title": t, "kind": "image"} for i, t in enumerate(titles)]}
        return {k: ok for k, ok in ((c["check"], c["ok"]) for c in grade(car, Run("library_red_car", "m", events=[
            ev("tool_call", id="1", name="embed_library_search", arguments={"query": "red car"}, by="model"),
            ev("tool_result", id="1", name="embed_library_search", status="done", content=_json.dumps({"result": res})),
            ev("assistant", text="IMG_2041.png")]))["checks"])}
    first = "the search ranks IMG_2041 above the other seeds"
    assert ranked("A glossy red sports car", "IMG_2041.png", "IMG_2042.png")[first]   # another real red car first: fine
    assert not ranked("IMG_2042.png", "IMG_2041.png")[first]                          # a seed above the car: not
    answer = Run("library_ten_docs", "m", events=[
        ev("user", text="…", docs=[{"ref": f"#{i}", "id": f"d{i}"} for i in range(1, 11)]),
        ev("tool_call", id="1", name="embed_library_search", arguments={"query": "pet", "thread_only": True}, by="model"),
        ev("tool_result", id="1", name="embed_library_search", status="done", content="{}"),
        ev("assistant", text=f"Yes: {STATIONS[ANSWER_DOC - 1]} keeps a ginger cat called Saffron (#{ANSWER_DOC} p.{ANSWER_PAGE}).")])
    assert grade(docs, answer)["ok"]
    assert b"Saffron" not in station_report(1) and len(station_report(ANSWER_DOC)) > 40_000


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


async def test_a_task_that_cant_run_here_is_skipped_not_failed(env):
    """Overnight 2026-10-21: tasks whose tools or workflows aren't offered (models removed) are skipped
    and kept out of the pass rates."""
    from evals.harness import summary

    h = Harness("http://agent", "main", dry_run=True, transport=httpx.ASGITransport(app=env.app))

    async def missing(task):
        return "comfy_animate_image isn't in the catalog here" if task.needs else None
    h.missing = missing
    skip = await h.run(Task("v1", "single", ["animate it"], [], needs=("comfy_animate_image",)))
    row = grade(Task("v1", "single", ["animate it"], []), skip)
    assert row["ok"] is None and "catalog" in row["skipped"] and not skip.events
    s = summary([row, {"task": "t2", "group": "single", "ok": True, "checks": [], "seconds": 1.0}], 1)
    assert s["tasks"] == 1 and s["pass_k"] == 1 and s["skipped"] == [{"task": "v1", "why": row["skipped"]}]
    await h.close()


def test_a_chart_drawn_with_show_counts_and_pdf_page7_goes_as_a_card():
    """ws_csv_chart takes a chart image from the sandbox or a `show` chart (plan 47.1); pdf_page7 sends its PDF
    as a card on every machine, so reading it with tools is what it tests (here inline_tokens may be "window")."""
    from evals.harness import Run
    from evals.workspace import made_chart

    def ev(t, **p):
        return {"type": t, "payload": p}
    _, check = made_chart()
    shown = Run("ws_csv_chart", "m", events=[ev("tool_call", id="1", name="show", arguments={"view": "bar", "x": ["Jan"]}, by="model"),
                                             ev("tool_result", id="1", name="show", status="done", content="{}")])
    assert check(shown)[0]
    table = Run("ws_csv_chart", "m", events=[ev("tool_call", id="1", name="show", arguments={"view": "table"}, by="model"),
                                             ev("tool_result", id="1", name="show", status="done", content="{}")])
    assert not check(table)[0] and not check(Run("ws_csv_chart", "m"))[0]
    assert {t.id: t for t in TASKS}["pdf_page7"].settings == {"doc_mode": "card"}



async def test_the_runner_runs_gpu_tasks_one_at_a_time(monkeypatch, tmp_path):
    """`--concurrency` is for the tasks that only need the LLM; those that reach this machine's GPU never overlap."""
    import argparse
    import asyncio

    import evals.run as er
    from evals.harness import Run, reaches_gpu

    now, most = {True: 0, False: 0}, {True: 0, False: 0}

    class FakeHarness:
        glitches: list = []

        def __init__(self, *a, **k):
            pass

        async def run(self, t):
            g = reaches_gpu(t)
            now[g] += 1
            most[g] = max(most[g], now[g])
            await asyncio.sleep(0.005)
            now[g] -= 1
            return Run(t.id, "m")

        async def close(self):
            pass

    monkeypatch.setattr(er, "Harness", FakeHarness)
    monkeypatch.setattr(er, "grade", lambda t, run: {"task": t.id, "group": t.group, "ok": True, "checks": [], "seconds": 0, "tools": []})
    a = argparse.Namespace(only=None, base="x", model="m", live=False, all_tools=False, keep=False, concurrency=16, runs=1,
                           out=str(tmp_path / "o.json"))
    assert await er.main(a) == 0
    assert most[True] == 1 and most[False] > 1
