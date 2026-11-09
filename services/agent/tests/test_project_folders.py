"""Plan projects 2.2: a project chat's workspace calls carry every environment of its project (primary first) and its
own hidden one; a plain chat's are unchanged; the prompt's folders note names the project and its environments."""

from __future__ import annotations

from agent import prompts
from agent.projects.origin import chat_envs

from .test_environments import DEFAULT, GRANTS, system_prompt

THESIS = {"id": "thesis", "name": "Thesis", "folders": [{"id": "drafts", "path": "/home/u/drafts", "level": "edit"}]}
OWN = {"id": "proj-1", "name": "Thesis (project)", "folders": [{"id": "refs", "path": "/home/u/refs", "level": "read"}]}


class Projects:
    def __init__(self, **ps):
        self.ps = ps

    def get(self, pid):
        return self.ps.get(pid)


def test_chat_envs():
    ps = Projects(p_a={"id": "p_a", "environments": ["grants", "thesis"], "own_env": "proj-1"},
                  p_b={"id": "p_b", "environments": [], "own_env": None}, p_c={"id": "p_c", "environments": ["grants"]})
    assert chat_envs({"environment": "grants"}, ps) == {"environment": "grants"}
    assert chat_envs({}, ps) == {} and chat_envs(None, None) == {}
    assert chat_envs({"project": "p_a", "environment": "grants"}, ps) == {"environment": "grants",
                                                                          "environments": ["grants", "thesis", "proj-1"]}
    assert chat_envs({"project": "p_b", "environment": "notes"}, ps) == {"environment": "notes"}   # lends the chat's own
    assert chat_envs({"project": "p_c"}, ps) == {"environment": "grants"}
    assert chat_envs({"project": "p_gone", "environment": "x"}, ps) == {"environment": "x"}         # a deleted project


async def test_a_project_chats_origin_carries_every_environment(env):
    env.hub.workspace = {"default": DEFAULT, "grants": GRANTS, "thesis": THESIS, "proj-1": OWN}
    p = (await env.client.post("/v1/projects", json={"name": "Thesis", "environments": ["grants", "thesis"]})).json()
    env.agent.projects.update(p["id"], own_env="proj-1")
    tid = (await env.client.post("/v1/threads", json={"settings": {"project": p["id"]}})).json()["id"]
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "x"}}]}, {"text": "done"})
    await env.send(tid, "look around")
    o = env.hub.attempts[-1]["origin"]
    assert o["environment"] == "grants" and o["environments"] == ["grants", "thesis", "proj-1"]
    assert env.hub.folder_origins[-1]["environments"] == ["grants", "thesis", "proj-1"]
    note = system_prompt(env)
    assert "Folders this chat can use (project Thesis: environments Grants, Thesis and the project's own folders)" in note
    for f in ("Mycelium (Read, id mycelium)", "drafts (Edit, id drafts)", "refs (Read, id refs)"):
        assert f in note


async def test_a_plain_chat_is_unchanged(env):
    env.hub.workspace = {"default": DEFAULT, "grants": GRANTS}
    await env.client.post("/v1/projects", json={"name": "Other", "environments": ["grants"]})
    tid = await env.thread(settings={"environment": "grants"})
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "x"}}]}, {"text": "done"})
    await env.send(tid, "hi")
    o = env.hub.attempts[-1]["origin"]
    assert o["environment"] == "grants" and "environments" not in o
    assert "environments" not in env.hub.folder_origins[-1]
    assert "(environment Grants)" in system_prompt(env)


def test_the_note_for_a_project_without_folders():
    note = prompts.folders_note({"environment": {"id": "default", "name": "Default"}, "folders": []}, "", {"name": "Trip"})
    assert "This chat's project (Trip) has no workspace folders." in note
