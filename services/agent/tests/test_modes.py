"""27.4: the five chat modes in the agent: old names mapped (and stored threads migrated), the mode
sent to the hub, the turn and the files the user named in each call's origin, the mode's note in
the prompt, and the card's limits passed through."""

from __future__ import annotations

import sqlite3

from agent import prompts
from agent.context import named_files
from agent.store import MODES, Store, mode_of


def test_modes_and_old_names():
    assert MODES == ("plan", "manual", "accept_edits", "auto", "bypass")
    assert mode_of("ask") == "manual" and mode_of("read_only") == "plan" and mode_of("auto") == "auto"
    assert mode_of("junk") == "manual" and mode_of(None) == "manual"


def test_stored_threads_are_migrated_once(tmp_path):
    db = tmp_path / "agent.db"
    s = Store(db)
    ids = {m: s.create_thread(mode="manual")["id"] for m in ("ask", "auto", "read_only", "manual")}
    s.close()
    c = sqlite3.connect(db)
    for old, tid in ids.items():
        c.execute("UPDATE threads SET mode = ? WHERE id = ?", (old, tid))
    c.execute("PRAGMA user_version = 0")
    c.commit()
    c.close()
    s = Store(db)
    got = {old: s.thread(tid)["mode"] for old, tid in ids.items()}
    assert got == {"ask": "manual", "auto": "accept_edits", "read_only": "plan", "manual": "manual"}
    t = s.create_thread(mode="auto")
    s.close()
    s = Store(db)                                                       # a second start leaves the new Auto alone
    assert s.thread(t["id"])["mode"] == "auto"
    assert s.update_thread(t["id"], mode="read_only")["mode"] == "plan"


def test_named_files_come_from_the_users_words():
    assert named_files("open the .env and `config/secrets.yaml`, and id_rsa.pub; not README.md") == [
        ".env", "config/secrets.yaml", "id_rsa.pub"]
    assert named_files("what's in the repo?") == []


def test_mode_notes():
    assert "Plan mode" in prompts.mode_note("plan") and prompts.mode_note("manual") == ""
    assert "undo" in prompts.mode_note("accept_edits") and "Bypass" in prompts.mode_note("bypass")


async def test_the_mode_turn_and_named_files_reach_the_hub(env):
    tid = await env.thread(mode="read_only")
    assert env.agent.store.thread(tid)["mode"] == "plan"
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "x"}}]}, {"text": "can't"})
    await env.send(tid, "use the .env please")
    a = env.hub.attempts[-1]
    assert a["mode"] == "plan" and a["origin"]["named"] == [".env"]
    user_seq = [e["seq"] for e in env.agent.store.events(tid) if e["type"] == "user"][-1]
    assert a["origin"]["turn"] == user_seq and a["origin"]["thread"] == tid
    system = env.model.received[0]["messages"][0]["content"]
    assert "Plan mode" in system
    for mode in ("accept_edits", "bypass"):
        r = await env.client.patch(f"/v1/threads/{tid}", json={"mode": mode})
        assert r.status_code == 200 and r.json()["mode"] == mode
