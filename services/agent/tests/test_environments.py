"""Plan 34: a chat's environment reaches every call's origin, and the system prompt lists the folders the chat can
use (its environment's, then those the user allowed in this chat), with how to ask for another."""

from __future__ import annotations

from agent import prompts

GRANTS = {"id": "grants", "name": "Grants", "folders": [{"id": "mycelium", "path": "/home/u/Agents/Mycelium", "level": "read"}]}
DEFAULT = {"id": "default", "name": "Default", "folders": [{"id": "aihub", "path": "/home/u/Agents/AIHub", "level": "read"},
                                                            {"id": "site", "path": "/srv/site", "level": "run_net"}]}


def test_the_note_lists_the_environment_and_the_chats_own_folders():
    data = {"environment": {"id": "grants", "name": "Grants"},
            "folders": [{**GRANTS["folders"][0]}, {"id": "notes", "path": "/home/u/notes", "level": "read", "granted": True}]}
    note = prompts.folders_note(data, "/home/u")
    assert "Folders this chat can use (environment Grants): ~/Agents/Mycelium (Read, id mycelium)" in note
    assert "Allowed in this chat by the user: ~/notes (Read, id notes)" in note
    assert "pass its full path as `folder`" in note and "If they deny it, tell them; don't retry it." in note
    d = prompts.folders_note({"environment": {"name": "Default"}, "folders": DEFAULT["folders"]}, "/home/u")
    assert "~/Agents/AIHub (Read, id aihub); /srv/site (Run + network, id site)" in d and "Allowed in" not in d
    empty = prompts.folders_note({"environment": {"name": "Empty"}, "folders": []})
    assert "This chat's environment (Empty) has no workspace folders." in empty
    assert prompts.folders_note(None) == ""
    assert prompts._home("/home/user2/x", "/home/u") == "/home/user2/x"


def system_prompt(env) -> str:
    sent = [r for r in env.model.received if any(m.get("role") == "system" for m in r.get("messages") or [])]
    return next(m["content"] for m in sent[-1]["messages"] if m["role"] == "system")


async def test_the_chats_environment_reaches_the_hub_and_the_prompt(env):
    env.hub.workspace = {"default": DEFAULT, "grants": GRANTS}
    tid = await env.thread(settings={"environment": "grants"})
    env.hub.grants = [{"id": "gr_1", "kind": "folder", "key": "folder:/home/u/notes", "thread": tid, "tool": "workspace_*"},
                      {"id": "gr_2", "kind": "arg:folder", "key": "x", "thread": tid, "tool": "fake_get"}]
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"q": "x"}}]}, {"text": "done"})
    await env.send(tid, "look around")
    assert env.hub.attempts[-1]["origin"]["environment"] == "grants"
    o = env.hub.folder_origins[-1]
    assert o["environment"] == "grants" and o["folders"] == [{"path": "/home/u/notes", "level": "read"}] and o["thread"] == tid
    p = system_prompt(env)
    assert "(environment Grants): /home/u/Agents/Mycelium (Read, id mycelium)" in p or "Agents/Mycelium (Read, id mycelium)" in p
    assert "Allowed in this chat by the user:" in p and "notes (Read, id notes)" in p


async def test_no_environment_means_default_and_no_workspace_means_no_note(env):
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"q": "x"}}]}, {"text": "done"})
    await env.send(tid, "hi")
    assert "environment" not in env.hub.attempts[-1]["origin"]
    assert "Folders this chat can use" not in system_prompt(env) and env.hub.folder_origins == []
    env.hub.workspace = {"default": DEFAULT}
    await env.send(tid, "again")
    assert "(environment Default)" in system_prompt(env) and "environment" not in env.hub.folder_origins[-1]
