"""Scheduled tasks' routes (plan scheduled-tasks 1.3, 2.3, 3.1–3.3).

    GET    /v1/tasks                          ?q=&project= (`none`: standalone); on first, then by the next run
    POST   /v1/tasks                          {name, schedule, instructions?, project_id?, …}
    GET    /v1/tasks/unread                   {count, tasks: {id: n}}: runs not opened yet
    GET    /v1/tasks/{kid}                    the task, with its last run and `unread`
    PATCH  /v1/tasks/{kid}                    any field; turning it on or a new schedule sets `next_due` from now
    DELETE /v1/tasks/{kid}                    its runs' chats stay as ordinary chats; its hidden environment goes
    GET    /v1/tasks/{kid}/runs               ?limit=&before=; newest first
    PATCH  /v1/tasks/{kid}/runs/{rid}         {seen}
    POST   /v1/tasks/{kid}/run                Run now (no one watching)
    POST   /v1/tasks/{kid}/test               a test run: cards as in any chat
    GET    /v1/tasks/{kid}/notes              notes on how to do the task, oldest first
    POST   /v1/tasks/{kid}/notes              {text}
    PATCH  /v1/tasks/{kid}/notes/{nid}        {text}
    DELETE /v1/tasks/{kid}/notes/{nid}
    GET/POST /v1/tasks/{kid}/folders          its own folders (a hidden environment, made with the first)
    PATCH/DELETE /v1/tasks/{kid}/folders/{fid}

Every change is published as `{type: "task", id, task}` (task None once deleted), and a run's as
`{type: "task_run", id, task_id, run}`, to the streams opened with `watch=tasks`.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .hubapi import HubCallError
from .projects import folders as own_folders
from .tasks.store import INSTRUCTIONS_MAX, NAME_MAX, NOTE_CHARS, TaskError

log = logging.getLogger("agent.tasks")
Mode = Literal["plan", "accept_edits", "auto", "bypass"]


class Allow(BaseModel):
    tools: list[str] = Field(default_factory=list, max_length=64, description="tool names or globs (web_*, mcp_blender_*)")
    sites: list[str] = Field(default_factory=list, max_length=64, description='hosts web tools may open; "*": every site')
    mcp: list[str] = Field(default_factory=list, max_length=32, description="MCP servers whose tools may run")


class ChatSettings(BaseModel):
    disabled: list[str] | None = Field(None, max_length=64)
    pinned: list[str] | None = Field(None, max_length=64)
    mcp_on: list[str] | None = Field(None, max_length=64)


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    schedule: dict[str, Any]
    instructions: str = Field("", max_length=INSTRUCTIONS_MAX)
    project_id: str | None = Field(None, max_length=64)
    enabled: bool = True
    model: str | None = Field(None, max_length=200, description="none: the project's default, else the agent's")
    mode: Mode = "auto"
    skills: list[str] = Field(default_factory=list, max_length=32, description="skills always in the run's prompt")
    allow: Allow = Field(default_factory=Allow)
    settings: ChatSettings = Field(default_factory=ChatSettings)
    only_own: bool = Field(False, description="a project task: only its own folders, not the project's")
    use_profile: bool = True
    use_project_memory: bool = True
    keep_days: int = Field(30, ge=1, le=3650, description="run chats older than this are archived")


class TaskPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=NAME_MAX)
    schedule: dict[str, Any] | None = None
    instructions: str | None = Field(None, max_length=INSTRUCTIONS_MAX)
    project_id: str | None = Field(None, max_length=64)
    enabled: bool | None = None
    model: str | None = Field(None, max_length=200)
    mode: Mode | None = None
    skills: list[str] | None = Field(None, max_length=32)
    allow: Allow | None = None
    settings: ChatSettings | None = None
    only_own: bool | None = None
    use_profile: bool | None = None
    use_project_memory: bool | None = None
    keep_days: int | None = Field(None, ge=1, le=3650)


class RunPatch(BaseModel):
    seen: bool


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=NOTE_CHARS)


class FolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="The folder's full path on this machine")
    level: Literal["read", "edit", "run", "run_net"] = "read"


class FolderPatch(BaseModel):
    level: Literal["read", "edit", "run", "run_net"]


def A(request: Request) -> Any:
    return request.app.state.agent


def task_or_404(agent: Any, kid: str) -> dict[str, Any]:
    t = agent.scheduled.get(kid)
    if t is None:
        raise HTTPException(404, {"code": "unknown_task", "detail": f"no task {kid!r}"})
    return t


def refused(e: TaskError) -> JSONResponse:
    return JSONResponse({"detail": {"code": e.code, "detail": e.detail}}, status_code=e.status)


def hub_error(e: HubCallError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "detail": e.detail, "data": e.data})


def publish(agent: Any, kid: str, task: dict[str, Any] | None = None) -> None:
    """`{type: "task", id, task}` to every stream watching tasks (None: it was deleted)."""
    agent.live.broadcast({"type": "task", "thread_id": None, "seq": None, "ts": time.time(), "id": kid,
                          "payload": {"id": kid, "task": task}, "task": task})


def publish_run(agent: Any, run: dict[str, Any]) -> None:
    agent.live.broadcast({"type": "task_run", "thread_id": None, "seq": None, "ts": time.time(), "id": run["id"],
                          "payload": {"id": run["id"], "task_id": run["task_id"], "run": run}, "task_id": run["task_id"], "run": run})


def check_project(agent: Any, pid: str | None) -> None:
    if pid and agent.projects.get(pid) is None:
        raise HTTPException(404, {"code": "unknown_project", "detail": f"no project {pid!r}"})


async def delete_task(agent: Any, t: dict[str, Any]) -> dict[str, Any]:
    """Its runs' chats become ordinary chats (their grants stay with them until they're deleted), its hidden
    environment goes (skipped and logged with the workspace mod off), then the task, its runs and notes."""
    kid, done = t["id"], {}
    for r in agent.scheduled.active(kid):
        if r.get("thread_id"):
            await agent.cancel(r["thread_id"])
    done["chats"] = agent.scheduled.release_chats(kid)
    try:
        done["environment"] = await own_folders.drop_env(agent, t)
    except Exception as e:  # noqa: BLE001
        log.warning("deleting task %s: environment skipped (%s)", kid, e)
        done["environment"] = f"skipped: {e}"
    agent.scheduled.delete(kid)
    return done


def install(agent: Any) -> None:
    """A deleted project's tasks stand alone, turned off (api_projects.delete_project runs this)."""
    async def detach(agent: Any, p: dict[str, Any]) -> int:
        ids = agent.scheduled.detach_project(p["id"])
        for kid in ids:
            publish(agent, kid, agent.scheduled.get(kid))
        return len(ids)
    agent.project_cleanup.insert(0, ("tasks", detach))


def add_routes(app: FastAPI) -> None:
    @app.get("/v1/tasks", summary="Scheduled tasks: on first, then by their next run; ?q= searches names and instructions; "
             "?project= one project's (`none`: the standalone ones)")
    def list_tasks(request: Request, q: str | None = None, project: str | None = None) -> list[dict]:
        return A(request).scheduled.list(q, project)

    @app.post("/v1/tasks", status_code=201, summary="Make a scheduled task")
    async def create_task(body: TaskIn, request: Request) -> Any:
        agent = A(request)
        check_project(agent, body.project_id)
        fields = body.model_dump(exclude={"name", "schedule"})
        fields["allow"], fields["settings"] = body.allow.model_dump(), body.settings.model_dump(exclude_none=True)
        try:
            t = agent.scheduled.create(body.name, body.schedule, **fields)
        except TaskError as e:
            return refused(e)
        publish(agent, t["id"], t)
        return t

    @app.get("/v1/tasks/unread", summary="Runs not opened yet: how many in all and per task")
    def unread(request: Request) -> dict:
        return A(request).scheduled.unread()

    @app.get("/v1/tasks/{kid}", summary="One task, with its last run")
    def get_task(kid: str, request: Request) -> dict:
        return task_or_404(A(request), kid)

    @app.patch("/v1/tasks/{kid}", summary="Change a task; turning it on or a new schedule sets its next run from now")
    async def patch_task(kid: str, body: TaskPatch, request: Request) -> Any:
        agent = A(request)
        task_or_404(agent, kid)
        fields = body.model_dump(exclude_unset=True)
        if body.allow is not None:
            fields["allow"] = body.allow.model_dump()
        if body.settings is not None:
            fields["settings"] = body.settings.model_dump(exclude_none=True)
        if "project_id" in fields:
            check_project(agent, fields["project_id"])
        try:
            t = agent.scheduled.update(kid, **fields)
        except TaskError as e:
            return refused(e)
        publish(agent, kid, t)
        return t

    @app.delete("/v1/tasks/{kid}", summary="Delete a task: its runs stay as ordinary chats")
    async def remove_task(kid: str, request: Request) -> dict:
        agent = A(request)
        done = await delete_task(agent, task_or_404(agent, kid))
        publish(agent, kid, None)
        return {"deleted": kid, **done}

    # ---- runs -------------------------------------------------------------------------------------

    @app.get("/v1/tasks/{kid}/runs", summary="The task's runs, newest first")
    def runs(kid: str, request: Request, limit: int = Query(50, ge=1, le=500), before: float | None = None) -> list[dict]:
        agent = A(request)
        task_or_404(agent, kid)
        return agent.scheduled.runs(kid, limit, before)

    def run_or_404(agent: Any, kid: str, rid: str) -> dict[str, Any]:
        r = agent.scheduled.run(rid)
        if r is None or r["task_id"] != kid:
            raise HTTPException(404, {"code": "unknown_run", "detail": f"no run {rid!r} of task {kid!r}"})
        return r

    @app.patch("/v1/tasks/{kid}/runs/{rid}", summary="Mark a run seen (its chat was opened) or unseen")
    def patch_run(kid: str, rid: str, body: RunPatch, request: Request) -> dict:
        agent = A(request)
        run_or_404(agent, kid, rid)
        r = agent.scheduled.update_run(rid, seen=body.seen)
        publish_run(agent, r)  # type: ignore[arg-type]
        return r  # type: ignore[return-value]

    @app.post("/v1/tasks/{kid}/run", status_code=202, summary="Run now: a run with no one watching, as if it were due")
    async def run_now(kid: str, request: Request) -> dict:
        agent = A(request)
        return await agent.runner.start(task_or_404(agent, kid), "run now")

    @app.post("/v1/tasks/{kid}/test", status_code=202, summary="A test run: you watch it, its calls get cards as in any chat, "
              "and what you approve can become a pre-allow")
    async def test_run(kid: str, request: Request) -> dict:
        agent = A(request)
        return await agent.runner.start(task_or_404(agent, kid), "test", test=True)

    # ---- notes ------------------------------------------------------------------------------------

    @app.get("/v1/tasks/{kid}/notes", summary="Notes on how to do the task, kept by its runs (and you), oldest first")
    def notes(kid: str, request: Request) -> list[dict]:
        agent = A(request)
        task_or_404(agent, kid)
        return agent.scheduled.notes(kid)

    @app.post("/v1/tasks/{kid}/notes", status_code=201, summary="Add a note")
    def add_note(kid: str, body: NoteIn, request: Request) -> Any:
        agent = A(request)
        task_or_404(agent, kid)
        try:
            return agent.scheduled.add_note(kid, body.text)
        except TaskError as e:
            return refused(e)

    def note_or_404(agent: Any, kid: str, nid: str) -> dict[str, Any]:
        n = agent.scheduled.note(nid)
        if n is None or n["task_id"] != kid:
            raise HTTPException(404, {"code": "unknown_note", "detail": f"no note {nid!r} of task {kid!r}"})
        return n

    @app.patch("/v1/tasks/{kid}/notes/{nid}", summary="Change a note")
    def patch_note(kid: str, nid: str, body: NoteIn, request: Request) -> Any:
        agent = A(request)
        note_or_404(agent, kid, nid)
        try:
            return agent.scheduled.update_note(nid, body.text)
        except TaskError as e:
            return refused(e)

    @app.delete("/v1/tasks/{kid}/notes/{nid}", summary="Remove a note")
    def remove_note(kid: str, nid: str, request: Request) -> dict:
        agent = A(request)
        note_or_404(agent, kid, nid)
        agent.scheduled.remove_note(nid)
        return {"deleted": nid}

    # ---- folders ----------------------------------------------------------------------------------

    @app.get("/v1/tasks/{kid}/folders", summary="The task's own folders")
    async def task_folders(kid: str, request: Request) -> list[dict]:
        agent = A(request)
        try:
            return await own_folders.folders(agent, task_or_404(agent, kid))
        except HubCallError as e:
            raise hub_error(e) from None

    @app.post("/v1/tasks/{kid}/folders", status_code=201, summary="Add a folder of its own (the first makes its hidden environment)")
    async def add_folder(kid: str, body: FolderIn, request: Request) -> dict:
        agent = A(request)
        try:
            f = await own_folders.add(agent, task_or_404(agent, kid), body.path, body.level, kind="task")
        except HubCallError as e:
            raise hub_error(e) from None
        publish(agent, kid, agent.scheduled.get(kid))
        return f

    @app.patch("/v1/tasks/{kid}/folders/{fid}", summary="Change a folder's level")
    async def change_folder(kid: str, fid: str, body: FolderPatch, request: Request) -> dict:
        agent = A(request)
        t = task_or_404(agent, kid)
        if not t.get("own_env"):
            raise HTTPException(404, {"code": "unknown_folder", "detail": "this task has no folders of its own"})
        try:
            return await own_folders.change(agent, t, fid, body.level)
        except HubCallError as e:
            raise hub_error(e) from None

    @app.delete("/v1/tasks/{kid}/folders/{fid}", summary="Remove a folder of its own (its files are left alone)")
    async def remove_folder(kid: str, fid: str, request: Request) -> dict:
        agent = A(request)
        t = task_or_404(agent, kid)
        if not t.get("own_env"):
            raise HTTPException(404, {"code": "unknown_folder", "detail": "this task has no folders of its own"})
        try:
            return await own_folders.remove(agent, t, fid)
        except HubCallError as e:
            raise hub_error(e) from None
