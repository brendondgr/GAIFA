"""The check on save (plan scheduled-tasks 3.1): what would break a run at 3 a.m., found while you're there.

`check(agent, task) -> {problems: [{field, detail, fix}], warnings: [{field, detail}]}`:
- **instructions:** not empty, and screened by the hub's fixed patterns (`POST /api/screen`); a finding is a problem,
  since a run reads them as your words;
- **model:** one the relay serves (a warning when the relay doesn't answer);
- **skills:** each found, the agent's own or one in the run's workspace folders (`<folder>:<skill>`);
- **pre-allows:** each tool glob matches a tool in the catalog, each MCP server has tools there;
- **folders:** each of its own folders exists;
- **an event** (calendar 6.2): a task before a calendar item needs the item to be there (`event_gone`); the calendar
  being down is a warning;
- **warnings:** Bypass (only the folders' levels limit it), pre-allowed `execute` or `destructive` tools, a folder capped
  below its level, and what couldn't be checked (a mod that's off).

Turning a task on, Run now and creating a task that's on all run it; problems answer `409 task_problems` (a new task is
saved turned off instead, with the check in its answer).
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

log = logging.getLogger("agent.tasks")
RISKY = ("execute", "destructive")


def _p(field: str, detail: str, fix: str) -> dict[str, str]:
    return {"field": field, "detail": detail, "fix": fix}


def _w(field: str, detail: str) -> dict[str, str]:
    return {"field": field, "detail": detail}


async def check(agent: Any, task: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    problems: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    hub = agent.hub
    text = (task.get("instructions") or "").strip()
    if not text:
        problems.append(_p("instructions", "the instructions are empty", "say what each run should do"))
    else:
        try:
            r = await hub._json("POST", "/api/screen", json={"text": text})
            for f in (r.get("findings") or [])[:5]:
                problems.append(_p("instructions", f"line {f.get('line', '?')}: {f.get('why') or 'flagged'}"
                                   + (f" ({f['excerpt']})" if f.get("excerpt") else ""),
                                   "reword that line: a run reads the instructions as your own words"))
        except Exception as e:  # noqa: BLE001
            warnings.append(_w("instructions", f"the instructions couldn't be screened ({getattr(e, 'detail', None) or type(e).__name__})"))
    await _model(agent, task, problems, warnings)
    try:
        index = await hub.index(max_age=0)
    except Exception:  # noqa: BLE001
        index = []
        warnings.append(_w("allow", "the tool catalog didn't answer, so the pre-allowed tools weren't checked"))
    if index:
        _allows(task, index, problems, warnings)
    await _skills(agent, task, problems, warnings)
    await _folders(agent, task, problems, warnings)
    await _event(agent, task, problems, warnings)
    if task.get("mode") == "bypass":
        warnings.append(_w("mode", "Bypass: the judge isn't asked; only the folders' levels limit what a run does"))
    return {"problems": problems, "warnings": warnings}


async def _model(agent: Any, task: dict[str, Any], problems: list, warnings: list) -> None:
    model = task.get("model")
    if not model:
        return
    from ..server import model_list
    try:
        ids = [m["id"] for m in model_list(await agent.llm.models(max_age=10))]
    except Exception:  # noqa: BLE001
        ids = []
    if not ids:
        warnings.append(_w("model", f"the relay didn't answer, so {model} wasn't checked"))
    elif model not in ids:
        problems.append(_p("model", f"the relay doesn't serve {model}", "pick a model from the list, or leave it to the default"))


def _allows(task: dict[str, Any], index: list[dict[str, Any]], problems: list, warnings: list) -> None:
    allow = task.get("allow") or {}
    for glob in allow.get("tools") or []:
        hits = [t for t in index if fnmatch.fnmatchcase(t["name"], glob)]
        if not hits:
            problems.append(_p("allow", f"no tool matches {glob}", "name a tool from the catalog, or a glob such as web_*"))
            continue
        risky = sorted({t["risk"] for t in hits} & set(RISKY))
        if risky:
            names = ", ".join(t["name"] for t in hits if t["risk"] in RISKY)[:200]
            warnings.append(_w("allow", f"{glob} pre-allows {' and '.join(risky)} tools ({names}): they run with no one asked"))
    groups = {t.get("group") for t in index if t.get("group")}
    for server in allow.get("mcp") or []:
        if f"mcp:{server}" not in groups:
            problems.append(_p("allow", f"the MCP server {server} has no tools in the catalog (unknown, off or not approved)",
                               "add or approve it on the MCP page, or take it out"))
    if allow.get("sites") and not any(t["name"] == "web_fetch" for t in index):
        warnings.append(_w("allow", "the web mod isn't in the catalog, so the pre-allowed sites can't be used now"))


async def _skills(agent: Any, task: dict[str, Any], problems: list, warnings: list) -> None:
    names = [s for s in task.get("skills") or [] if s.strip()]
    if not names:
        return
    from ..knowledge import Knowledge
    _, tree = agent.harness_of("")
    k = Knowledge(agent.cfg.data, agent.hub, tree, agent.memory)
    try:
        own = await k.skills()
    except Exception:  # noqa: BLE001: the hub's mod skills; the agent's own still count
        own = k.user_skills()
    workspace: list[str] | None = None
    for n in names:
        if ":" in n.split("/", 1)[0]:
            if workspace is None:
                workspace = await _workspace_skills(agent, task)
            if workspace is None:
                warnings.append(_w("skills", f"{n} wasn't checked: the workspace mod didn't answer"))
            elif n not in workspace:
                problems.append(_p("skills", f"no skill {n} in the run's folders", "check the folder, or pick another skill"))
        elif not any(s["name"] == n or s["id"] == n or s["id"].endswith("/" + n) for s in own):
            problems.append(_p("skills", f"no skill {n}", "pick one from Settings → Agent → Skills"))


async def _workspace_skills(agent: Any, task: dict[str, Any]) -> list[str] | None:
    from ..projects.origin import chat_envs
    settings, _, _ = agent.runner.chat_settings(task, {"id": "r_check", "test": False})
    try:
        r = await agent.hub.chat_skills("", chat_envs(settings, agent.projects) or None)
    except Exception:  # noqa: BLE001
        return None
    return [s["id"] for s in r.get("skills") or []]


async def _folders(agent: Any, task: dict[str, Any], problems: list, warnings: list) -> None:
    if not task.get("own_env"):
        return
    from ..projects import folders as own
    try:
        got = await own.folders(agent, task)
    except Exception:  # noqa: BLE001
        warnings.append(_w("folders", "the workspace mod didn't answer, so the task's folders weren't checked"))
        return
    for f in got:
        if f.get("exists") is False:
            problems.append(_p("folders", f"{f.get('path')} doesn't exist", "make it, or take it out of the task"))
        elif f.get("capped"):
            warnings.append(_w("folders", f"{f.get('path')}: {f['capped']}"))


async def _event(agent: Any, task: dict[str, Any], problems: list[dict[str, str]], warnings: list[dict[str, str]]) -> None:
    s = task.get("schedule") or {}
    if s.get("kind") != "event":
        return
    try:
        await agent.hub._json("GET", f"/api/s/calendar/v1/items/{s.get('item')}")
    except Exception as e:  # noqa: BLE001
        if getattr(e, "status", None) == 404:
            problems.append(_p("schedule", f"the calendar item {s.get('item')} is gone (event_gone)",
                               "pick another event, or delete this task"))
        else:
            warnings.append(_w("schedule", f"the calendar didn't answer, so its event wasn't checked ({getattr(e, 'detail', None) or type(e).__name__})"))

