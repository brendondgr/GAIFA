"""Projects' routes (plan projects 1.2): projects, their chats and, in later phases, their folders, sources and memory.

    GET    /v1/projects                         ?q=&sort=activity|name|created; pinned first
    POST   /v1/projects                         {name, description?, instructions?, environments?, defaults?}
    GET    /v1/projects/{pid}                   the project with its `sources`
    PATCH  /v1/projects/{pid}                   {name?, description?, instructions?, environments?, defaults?, pinned?}
    DELETE /v1/projects/{pid}                   its chats become ordinary chats; what goes and what stays: `delete_project`
    GET    /v1/projects/{pid}/threads           the project's chats (the same query as /v1/threads)

A chat joins a project through `POST /v1/threads` or `PATCH /v1/threads/{id}` with `settings.project` (`new_chat` and
`move_chat`, which server.py calls). Every change is published as `{type: "project", id, project}` (project None once
deleted) to the streams opened with `watch=projects`.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .projects.store import DESCRIPTION_MAX, INSTRUCTIONS_MAX, NAME_MAX, ProjectError

log = logging.getLogger("agent.projects")
THREAD_KEYS = ("disabled", "pinned", "mcp_on")       # the defaults that are thread settings


class Defaults(BaseModel):
    model: str | None = Field(None, max_length=200)
    mode: Literal["plan", "manual", "accept_edits", "auto", "bypass"] | None = None
    disabled: list[str] | None = Field(None, max_length=64, description="tool groups turned off in its chats")
    pinned: list[str] | None = Field(None, max_length=64, description="tool groups always loaded")
    mcp_on: list[str] | None = Field(None, max_length=64, description="MCP servers on")
    skills: list[str] | None = Field(None, max_length=32, description="skills always in its chats' prompts")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str = Field("", max_length=DESCRIPTION_MAX)
    instructions: str = Field("", max_length=INSTRUCTIONS_MAX)
    environments: list[str] = Field(default_factory=list, max_length=16, description="workspace environments, primary first")
    defaults: Defaults = Field(default_factory=Defaults)


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=NAME_MAX)
    description: str | None = Field(None, max_length=DESCRIPTION_MAX)
    instructions: str | None = Field(None, max_length=INSTRUCTIONS_MAX)
    environments: list[str] | None = Field(None, max_length=16)
    defaults: Defaults | None = None
    pinned: bool | None = None


def A(request: Request) -> Any:
    return request.app.state.agent


def project_or_404(agent: Any, pid: str) -> dict[str, Any]:
    p = agent.projects.get(pid)
    if p is None:
        raise HTTPException(404, {"code": "unknown_project", "detail": f"no project {pid!r}"})
    return p


def refused(e: ProjectError) -> JSONResponse:
    return JSONResponse({"detail": {"code": e.code, "detail": e.detail}}, status_code=e.status)


def primary(p: dict[str, Any]) -> str | None:
    """The project's primary environment: the first in its list (None when it lists none)."""
    return (p.get("environments") or [None])[0]


def publish(agent: Any, pid: str, project: dict[str, Any] | None = None) -> None:
    """`{type: "project", id, project}` to every stream watching projects (None: it was deleted)."""
    agent.live.broadcast({"type": "project", "thread_id": None, "seq": None, "ts": time.time(), "id": pid,
                          "payload": {"id": pid, "project": project}, "project": project})


def full(agent: Any, p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "sources": agent.projects.sources(p["id"])}


def new_chat(agent: Any, settings: dict[str, Any], model: str | None, mode: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    """A new chat in `settings.project` takes the project's defaults (model, mode, tool groups, MCP servers) and its
    primary environment, under whatever the request sets itself (`model`/`mode` None: not set). 404 for an unknown
    project; a chat with no project comes back unchanged."""
    pid = settings.get("project")
    if not pid:
        settings.pop("project", None)
        return settings, model, mode
    p = project_or_404(agent, str(pid))
    d = p.get("defaults") or {}
    base = {k: list(d[k]) for k in THREAD_KEYS if d.get(k)}
    if primary(p):
        base["environment"] = primary(p)
    return {**base, **settings}, model or d.get("model"), mode or d.get("mode")


def move_chat(agent: Any, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """The chat's settings after a PATCH that names `project`: in (the project's primary environment; nothing else
    changes, not the model or mode) or out (null: the project goes, the environment stays)."""
    out = {**current, **patch}
    if "project" not in patch:
        return out
    if not patch["project"]:
        out.pop("project", None)
        return out
    p = project_or_404(agent, str(patch["project"]))
    if primary(p) and "environment" not in patch:
        out["environment"] = primary(p)
    return out


async def delete_project(agent: Any, p: dict[str, Any]) -> dict[str, Any]:
    """Its chats become ordinary chats (still in history, their environment kept), then the project record, its
    instructions, page links and sources go. Later phases add its embed collection (3.2), its hidden environment (2.3)
    and its memory entity's anchor (4.2); each step is skipped when its mod is off, and logged."""
    pid, done = p["id"], {}
    done["chats"] = agent.projects.release_chats(pid)
    for step, fn in agent.project_cleanup:
        try:
            done[step] = await fn(agent, p)
        except Exception as e:  # noqa: BLE001: one mod being off never keeps the project
            log.warning("deleting project %s: %s skipped (%s)", pid, step, e)
            done[step] = f"skipped: {e}"
    agent.projects.delete(pid)
    return done


def add_routes(app: FastAPI) -> None:
    @app.get("/v1/projects", summary="Projects, pinned first, then by recent activity (or name, or created); ?q= searches "
             "names and descriptions")
    def list_projects(request: Request, q: str | None = None,
                      sort: Literal["activity", "name", "created"] = "activity") -> list[dict]:
        return A(request).projects.list(q, sort)

    @app.post("/v1/projects", status_code=201, summary="Make a project")
    async def create_project(body: ProjectIn, request: Request) -> Any:
        agent = A(request)
        try:
            p = agent.projects.create(body.name, body.description, body.instructions, body.environments,
                                      body.defaults.model_dump(exclude_none=True))
        except ProjectError as e:
            return refused(e)
        for hook in agent.project_created:
            try:
                await hook(agent, p)
            except Exception:  # noqa: BLE001: the project stands without its extras
                log.exception("after creating project %s", p["id"])
        p = agent.projects.get(p["id"])
        publish(agent, p["id"], p)
        return full(agent, p)

    @app.get("/v1/projects/{pid}", summary="One project, with its files and pages")
    def get_project(pid: str, request: Request) -> dict:
        agent = A(request)
        return full(agent, project_or_404(agent, pid))

    @app.patch("/v1/projects/{pid}", summary="Rename, describe, instruct, set its environments (primary first), defaults or pin")
    async def patch_project(pid: str, body: ProjectPatch, request: Request) -> Any:
        agent = A(request)
        old = project_or_404(agent, pid)
        fields = body.model_dump(exclude_unset=True)
        if body.defaults is not None:
            fields["defaults"] = body.defaults.model_dump(exclude_none=True)
        try:
            p = agent.projects.update(pid, **fields)
        except ProjectError as e:
            return refused(e)
        if primary(p) and primary(p) != primary(old):              # its chats follow the new primary environment
            agent.projects.set_chats_environment(pid, primary(p))
        for hook in agent.project_changed:
            try:
                await hook(agent, old, p)
            except Exception:  # noqa: BLE001
                log.exception("after changing project %s", pid)
        p = agent.projects.get(pid)
        publish(agent, pid, p)
        return full(agent, p)

    @app.delete("/v1/projects/{pid}", summary="Delete a project: its chats stay as ordinary chats, its memory stays in "
                "Memory, its uploaded files stay in Outputs")
    async def remove_project(pid: str, request: Request) -> dict:
        agent = A(request)
        p = project_or_404(agent, pid)
        done = await delete_project(agent, p)
        publish(agent, pid, None)
        return {"deleted": pid, **done}

    @app.get("/v1/projects/{pid}/threads", summary="The project's chats, newest first (the same query as /v1/threads)")
    def project_threads(pid: str, request: Request, q: str | None = None, archived: bool = False,
                        limit: int = Query(200, ge=1, le=1000), sort: Literal["updated", "created", "title"] = "updated",
                        offset: int = Query(0, ge=0)) -> list[dict]:
        agent = A(request)
        project_or_404(agent, pid)
        return agent.store.threads(q, archived, limit, sort=sort, offset=offset, project=[pid])
