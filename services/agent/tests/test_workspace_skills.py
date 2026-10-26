"""skill-sources 2.2: a chat lists and reads other agents' skills in its workspace folders; none without folders."""

from __future__ import annotations

GAIFA = {"id": "gaifa", "name": "GAIFA", "path": "/home/u/Agents/GAIFA"}
WS = {"skills": [{"id": "gaifa:plan", "name": "plan", "description": "Write plans in GAIFA's format", "folder": GAIFA,
                  "model_invocable": True},
                 {"id": "gaifa:only-slash", "name": "only-slash", "description": "By slash only", "folder": GAIFA,
                  "model_invocable": False}],
      "instructions": [{"id": "gaifa:AGENTS.md", "file": "AGENTS.md", "folder": GAIFA, "also": ["CLAUDE.md"]}]}
DEFAULT = {"id": "default", "name": "Default", "folders": [{"id": "gaifa", "path": GAIFA["path"], "level": "read"}]}
NONE = {"id": "none", "name": "None", "folders": []}


def system_prompt(env) -> str:
    return env.model.received[-1]["messages"][0]["content"]


async def test_a_chat_lists_and_reads_its_folders_skills(env):
    env.hub.workspace = {"default": DEFAULT, "none": NONE}
    env.hub.ws_skills = {"default": WS}
    env.hub.ws_texts = {"gaifa:plan": {"id": "gaifa:plan", "kind": "skill", "text": "Plan body.",
                                       "files": [{"path": "planner.md", "size": 3000}]},
                        "gaifa:plan/planner.md": {"id": "gaifa:plan/planner.md", "kind": "file", "text": "The format."},
                        "gaifa:AGENTS.md": {"id": "gaifa:AGENTS.md", "kind": "instructions", "text": "# Rules"}}
    names = ("gaifa:plan", "gaifa:plan/planner.md", "gaifa:AGENTS.md", "gaifa:nope", "other:plan")
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": n}} for n in names]}, {"text": "read"})
    tid = await env.thread(settings={"environment": "default"})
    await env.send(tid, "plan the work")
    prompt = env.model.received[0]["messages"][0]["content"]
    assert "From the workspace folder GAIFA (/home/u/Agents/GAIFA):\n- gaifa:plan: Write plans in GAIFA's format" in prompt
    assert "only-slash" not in prompt
    assert "Before working in GAIFA, read its instructions with read_skill: gaifa:AGENTS.md" in prompt
    by = {r["id"]: r for r in env.payloads(tid, "tool_result")}
    body, f, docs, nope, other = (by[c["id"]] for c in env.payloads(tid, "tool_call"))
    assert body["content"].startswith("Plan body.") and "read_skill('gaifa:plan/<path>')" in body["content"]
    assert f["content"] == "The format." and docs["content"] == "# Rules"
    assert nope["error"]["code"] == "not_found" and other["error"]["code"] == "unknown_folder"


async def test_no_folders_or_no_workspace_means_no_workspace_skills(env):
    env.hub.ws_skills = {"default": WS}
    tid = await env.thread(settings={"environment": "none"})          # the workspace mod isn't running
    await env.send(tid, "hi")
    assert "From the workspace folder" not in system_prompt(env)
    env.hub.workspace = {"default": DEFAULT, "none": NONE}
    await env.send(tid, "again")                                        # running, but None has no folders
    assert "From the workspace folder" not in system_prompt(env)
    tid2 = await env.thread(settings={"environment": "default", "disabled": ["workspace"]})
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "gaifa:plan"}}]}, {"text": "ok"})
    await env.send(tid2, "use it")
    assert "From the workspace folder" not in env.model.received[-2]["messages"][0]["content"]
    res = env.payloads(tid2, "tool_result")[0]
    assert res["status"] == "error" and res["error"]["code"] == "disabled"
