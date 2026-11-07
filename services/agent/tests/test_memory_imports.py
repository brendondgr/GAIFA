"""memory-import 1.1–1.4: another assistant's memory read into lines, interpreted by the (scripted) model into facts
and entries, compared with what memory holds, previewed with a default choice and its reason, saved as imported
with each entry's date, and undone."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from agent.memory.sources import EXPORT_PROMPT, read_lines

EXPORT = (Path(__file__).parent / "fixtures" / "memory-export.md").read_text()
READ_MATCH = "moving a user's memory"


def test_reading_an_export():
    lines = read_lines(EXPORT)
    assert len(lines) == 10 and Counter(li["section"] for li in lines) == {
        "instructions": 3, "identity": 3, "career": 1, "projects": 2, "preferences": 1}
    assert lines[0] == {"n": 1, "section": "instructions", "date": "2026-05-02",
                        "text": "Commit after each step, but never push unless told to."}
    assert lines[5]["date"] is None and lines[5]["text"] == "Has a sister who lives in Lisbon."   # [unknown]
    assert not any("complete set" in li["text"] or "stored about you" in li["text"] for li in lines)
    plain = read_lines("Here's what I remember:\n- Likes tea\n* Works at Acme\n1. Lives in Oslo\n\nAnything else?")
    assert [(li["section"], li["date"], li["text"]) for li in plain] == [
        (None, None, "Likes tea"), (None, None, "Works at Acme"), (None, None, "Lives in Oslo")]
    assert [li["text"] for li in read_lines("Likes tea\nLikes tea\nWorks at Acme")] == ["Likes tea", "Works at Acme"]
    head = read_lines("1. **Instructions**: rules\n[2026-01-01] - Be brief.\n**Career**\n* [n/a] - Works at Acme")
    assert [(li["section"], li["date"]) for li in head] == [("instructions", "2026-01-01"), ("career", None)]
    assert "[YYYY-MM-DD] - Entry content here." in EXPORT_PROMPT


def fact(text, about=("you",), kind="fact", **kw):
    return {"text": text, "about": list(about), "kind": kind, "confidence": 0.95, **kw}


READ = {"lines": [
    {"n": 1, "facts": [fact("Commit after each step, but never push unless told to.", kind="preference")]},
    {"n": 2, "facts": [fact('Cover letters must show fit, not tell it ("no keyword lists").', ["topics/Cover letters"], "preference")]},
    {"n": 3, "facts": [fact("Never run sudo for me; give me the commands to run.", kind="preference")]},
    {"n": 4, "facts": [fact('The user goes by "Sam Rivera".')]},
    {"n": 5, "facts": [fact("The user is into woodworking and bouldering.", ["topics/Woodworking"], "interest")]},
    {"n": 6, "facts": [fact("The user has a sister who lives in Lisbon.", sensitive=True)]},
    {"n": 7, "facts": [fact("The user is a data engineer at Northwind Labs.", ["you", "organizations/Northwind Labs"])]},
    {"n": 8, "entity": {"name": "Lantern", "kind": "project", "aliases": ["Firefly"], "summary": "A reading-tracker app with offline sync"},
     "facts": [fact("Lantern is a reading-tracker app with offline sync.", ["projects/Lantern"]),
               fact("Lantern was pitched to an investor for $40k.", ["projects/Lantern"])]},
    {"n": 10, "facts": [fact("The user prefers dark themes and short answers.", kind="preference")]}]}     # 9 left out


def read_reply(body, **kw):
    return {"text": json.dumps(body), "match": READ_MATCH, **kw}


async def ready(c, iid, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = (await c.get(f"/v1/memory/imports/{iid}")).json()
        if r["state"] != "reading":
            return r
        await asyncio.sleep(0.05)
    raise TimeoutError(iid)


async def preview(env, text=EXPORT, source="claude"):
    r = await env.client.post("/v1/memory/imports", json={"text": text, "source": source})
    assert r.status_code == 202, r.text
    return await ready(env.client, r.json()["id"])


def by_key(p):
    return {f["key"]: f for li in p["lines"] for f in li["facts"]}


async def test_preview_save_and_import_again(env):
    m, c = env.agent.memory, env.client
    env.model.queue(read_reply(READ), {"text": json.dumps({"facts": ["Never run sudo for the user; give the user the commands to run."]}),
                                       "match": "Rewrite each sentence"})
    p = await preview(env)
    assert p["state"] == "ready" and p["total"] == 10 and p["done"] == 10
    f = by_key(p)
    assert f["3.1"]["text"] == "Never run sudo for the user; give the user the commands to run." and f["3.1"]["choice"] == "save"
    assert (f["6.1"]["choice"], f["6.1"]["why"]) == ("review", "sensitive: relationships")
    assert (f["8.2"]["choice"], f["8.2"]["why"]) == ("review", "sensitive: money")
    assert f["8.1"]["choice"] == "save" and f["5.1"]["about"] == ["topics/Woodworking", "you"]   # identity: the user's too
    assert f["2.1"]["about"] == ["topics/Cover letters"]                                         # a rule for one kind of work
    assert p["lines"][8]["error"] == "couldn't read this line" and p["counts"]["unread"] == 1
    assert p["lines"][7]["entity"]["aliases"] == ["Firefly"]
    assert m.facts() == []                                                                       # nothing saved yet

    s = (await c.post(f"/v1/memory/imports/{p['id']}/save", json={"choices": {"10.1": "skip"}})).json()
    assert s["state"] == "saved" and {k: s["saved"][k] for k in ("saved", "review", "skipped", "failed")} == \
        {"saved": 7, "review": 2, "skipped": 1, "failed": 0}
    lantern = m.resolve("Firefly")
    assert lantern["name"] == "Lantern" and lantern["kind"] == "project" and lantern["summary"] == "A reading-tracker app with offline sync"
    got = {x["text"]: x for x in (await c.get("/v1/memory/facts", params={"import": p["id"]})).json()}
    assert len(got) == 9
    pitch = got["Lantern was pitched to an investor for $40k."]
    assert pitch["state"] == "proposed" and pitch["evidence"][0]["why"] == "sensitive: money" and pitch["source"] == "imported"
    app = got["Lantern is a reading-tracker app with offline sync."]
    assert app["state"] == "active" and app["valid_from"] == "2026-02-14" and [e["path"] for e in app["entities"]] == ["projects/Lantern"]
    ev = app["evidence"][0]
    assert (ev["import"], ev["from"], ev["section"]) == (p["id"], "claude", "projects") and ev["line"].startswith("Lantern (formerly Firefly)")
    assert got['The user has a sister who lives in Lisbon.']["valid_from"] is None
    assert m.resolve("Woodworking")["kind"] == "topic" and m.resolve("Northwind Labs")["kind"] == "organization"

    env.model.received.clear()                       # again: only the two entries not saved are read
    env.model.queue(read_reply({"lines": [{"n": 9, "facts": [fact("Hearth is a home-automation dashboard.", ["projects/Hearth"])]},
                                          {"n": 10, "facts": [fact("The user prefers dark themes and short answers.", kind="preference")]}]}))
    again = await preview(env)
    reads = [r for r in env.model.received if READ_MATCH in json.dumps(r)]
    assert len(reads) == 1 and "Lantern" not in reads[0]["messages"][0]["content"].split("THE ENTRIES:")[1]
    assert again["counts"]["same"] == 9 and by_key(again)["8.1"]["why"] == "already known"
    await c.post(f"/v1/memory/imports/{again['id']}/save", json={})
    assert m.need_fact(app["id"])["seen"] == 2
    listed = (await c.get("/v1/memory/imports")).json()
    assert [x["id"] for x in listed] == [again["id"], p["id"]] and "lines" not in listed[0]


def test_a_name_with_a_slash_is_a_name():
    from agent.memory.imports import cands_of
    line = {"n": 1, "section": "projects", "date": None, "text": "ProQuest/Pivot-RP scraper: a Playwright scraper."}
    ent, cands = cands_of(line, {"entity": {"name": "ProQuest/Pivot-RP scraper", "kind": "project", "aliases": []},
                                 "facts": [fact("ProQuest/Pivot-RP scraper is a Playwright scraper.", ["projects/ProQuest/Pivot-RP scraper"])]})
    assert ent["name"] == "ProQuest Pivot-RP scraper" and ent["aliases"] == ["ProQuest/Pivot-RP scraper"]
    assert cands[0]["about"] == ["projects/ProQuest Pivot-RP scraper"]


async def test_changes_replace_and_undo_brings_them_back(env):
    m, c = env.agent.memory, env.client
    blender = m.add_fact("The user is into Blender.", kind="interest", source="inferred", by="learner")
    m.set_fact_state(blender["id"], "active", by="learner", op="fact_auto")
    light = m.add_fact("The user prefers light themes.", kind="preference")                       # stated
    await env.agent.memory_index.flush()
    text = "## Identity\n[2026-11-01] - Into Unity now, no longer Blender.\n## Preferences\n[2026-11-02] - Prefers dark themes."
    env.model.queue(read_reply({"lines": [
        {"n": 1, "facts": [fact("The user is into Unity now, no longer Blender.", kind="interest", ends=["Blender"])]},
        {"n": 2, "facts": [fact("The user prefers dark themes.", kind="preference")]}]}),
        {"text": json.dumps({"decisions": [{"n": 1, "op": "replaces", "id": light["id"]}]}), "match": "For each new fact below"})
    p = await preview(env, text)
    f = by_key(p)
    assert (f["1.1"]["op"], f["1.1"]["held"]["id"], f["1.1"]["choice"]) == ("replaces", blender["id"], "save")
    assert (f["2.1"]["op"], f["2.1"]["choice"], f["2.1"]["why"]) == ("replaces", "review", "would change something you said")
    await c.post(f"/v1/memory/imports/{p['id']}/save", json={})
    old = m.fact_public(m.need_fact(blender["id"]))
    assert old["state"] == "retired" and old["valid_until"] == "2026-11-01"
    dark = m.facts(state="proposed")[0]
    assert dark["replaces"] == light["id"] and m.fact_public(m.need_fact(light["id"]))["current"]

    m.update_fact(dark["id"], text="The user prefers dark themes at night.")                    # changed since: kept
    u = (await c.delete(f"/v1/memory/imports/{p['id']}")).json()
    assert u["state"] == "undone" and (u["undone"]["undone"], u["undone"]["kept"]) == (1, 1)
    assert m.fact_public(m.need_fact(blender["id"]))["current"]                                 # Blender is back
    assert not any("Unity" in x["text"] for x in m.facts())                                    # gone
    assert m.need_fact(dark["id"])["text"] == "The user prefers dark themes at night."
    assert (await c.delete(f"/v1/memory/imports/{p['id']}")).status_code == 409


async def test_an_answer_that_isnt_json_is_asked_again_then_reported(env):
    env.model.queue(read_reply({}, text="Sure! Here they are."), {"text": "still not JSON", "match": READ_MATCH})
    p = await preview(env, "- Likes tea\n- Works at Acme")
    reads = [r for r in env.model.received if READ_MATCH in json.dumps(r)]
    assert len(reads) == 2 and p["state"] == "ready" and p["counts"]["unread"] == 2
    assert [li["error"] for li in p["lines"]] == ["couldn't read this line"] * 2


async def test_limits_and_one_at_a_time(env):
    c = env.client
    big = await c.post("/v1/memory/imports", json={"text": "- x" * 70000, "source": "other"})
    assert big.status_code == 413 and big.json()["code"] == "too_big" and big.json()["fix"]
    empty = await c.post("/v1/memory/imports", json={"text": "```\n```", "source": "other"})
    assert empty.status_code == 422 and empty.json()["code"] == "nothing_to_import"
    env.model.queue(read_reply({"lines": [{"n": 1, "facts": [fact("The user likes tea.")]}]}, delay=1.0))
    first = await c.post("/v1/memory/imports", json={"text": "- Likes tea", "source": "chatgpt"})
    busy = await c.post("/v1/memory/imports", json={"text": "- Likes coffee", "source": "chatgpt"})
    assert busy.status_code == 409 and busy.json()["code"] == "busy"
    early = await c.post(f"/v1/memory/imports/{first.json()['id']}/save", json={})
    assert early.status_code == 409
    assert (await ready(c, first.json()["id"]))["state"] == "ready"
    bad = await c.post(f"/v1/memory/imports/{first.json()['id']}/save", json={"choices": {"1.1": "maybe"}})
    assert bad.status_code == 422
    assert (await c.get("/v1/memory/imports/prompt")).json()["prompt"].startswith("Export all of my stored memories")
