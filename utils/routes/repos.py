"""The `repos` area (plan mod-repos 3.3): the mods that are their own repositories.

`GET /api/repos` (each submodule's state and problems, the settings, the last update),
`POST /api/repos/fetch`, `GET /api/repos/{id}/incoming` (what an update would bring in), `POST /api/repos/{id}/update` (in the background: progress as
`{type: "repos"}` events, the result on `GET /api/repos`), `POST /api/repos/{id}/pin`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from utils import repos, repos_update
from utils.services.model import ServiceError

router = APIRouter(tags=["repos"])


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepoProblem(_Model):
    code: str = Field(description="not_checked_out, dirty, untracked, unpushed, pin_not_on_remote, checkout_behind_pin, "
                                  "checkout_ahead_of_pin, diverged, updates_available, fetch_failed, wrong_remote, git_error")
    level: Literal["info", "warn", "error"]
    title: str
    detail: str = ""
    fix: str = ""


class RepoState(_Model):
    id: str
    path: str
    url: str
    branch: str
    initialized: bool
    pinned: str | None = Field(description="The commit GAIFA's HEAD records for the folder")
    staged_pin: str | None = Field(description="A different pin staged in GAIFA's index, not committed yet")
    head: str | None
    on_branch: str | None = Field(description="The branch checked out, or null when detached")
    dirty: int
    untracked: int
    ahead: int
    behind: int = Field(description="Commits on the branch on GitHub (as of the last fetch) the pin doesn't have")
    unpushed: int
    pinned_on_remote: bool | None
    checkout_vs_pin: Literal["same", "ahead", "behind", "diverged", "unknown"]
    remote_url: str | None
    last_fetch_ts: float | None
    fetch_error: str | None
    problems: list[RepoProblem]
    level: Literal["info", "warn", "error"] | None


class RepoStep(_Model):
    ts: float
    text: str


class RepoUpdate(_Model):
    id: str
    running: bool
    started: float
    steps: list[RepoStep]
    result: dict[str, Any] | None = Field(description="When it's done: {ok, old, new, commits, refused, installed, restarted, "
                                                     "checked, rolled_back, staged, committed, message}")


class ReposSettings(_Model):
    fetch_every_h: float
    notify: Literal["warnings", "all", "off"]
    check_on_start: bool


class Repos(_Model):
    repos: list[RepoState]
    settings: ReposSettings
    last_fetch_ts: float | None = Field(description="The oldest of the last fetches; null when never")
    update: RepoUpdate | None


class UpdateBody(_Model):
    to: str | None = Field(None, description="A commit, tag or branch instead of the branch's head")
    commit: bool = Field(False, description="Run GAIFA's tests and commit the pin (else it's staged)")
    force_busy: bool = Field(False, description="Update even while the mod runs jobs")


class PinResult(_Model):
    id: str
    ok: bool
    old: str | None = None
    new: str | None = None
    commits: list[str] = []
    refused: list[str] = []
    staged: bool = False
    committed: str | None = None
    message: str = ""


def _watch(request: Request) -> Any:
    return request.app.state.hub.repos


def _body(w: Any) -> dict[str, Any]:
    return {"repos": [s.to_dict() for s in w.states], "settings": w.cfg.model_dump(), "last_fetch_ts": w.last_fetch(),
            "update": w.job_view()}


def _known(w: Any, sid: str) -> None:
    if sid not in [s[0] for s in repos.submodules(w.root)]:
        raise ServiceError(404, "repo_not_found", f"{sid} isn't a mod with its own repository (.gitmodules)")


@router.get("/api/repos", summary="The mods that are their own repositories: each one's pin, checkout and problems", response_model=Repos)
async def get_repos(request: Request, refresh: bool = False) -> dict[str, Any]:
    w = _watch(request)
    if refresh or not w.states:
        await w.refresh()
    return _body(w)


@router.post("/api/repos/fetch", summary="Ask GitHub what's new (one mod with ?id=, else all)", response_model=Repos)
async def fetch_repos(request: Request, id: str | None = None) -> dict[str, Any]:
    w = _watch(request)
    if id:
        _known(w, id)
    await w.fetch(id)
    return _body(w)


class Incoming(_Model):
    id: str
    ok: bool
    commits: list[str] = Field(description="`<short sha> <subject>`, newest first")
    refused: list[str]
    message: str


@router.get("/api/repos/{sid}/incoming", summary="What an update would bring in: fetches, then lists the new commits (changes nothing)",
            response_model=Incoming)
async def repo_incoming(sid: str, request: Request) -> dict[str, Any]:
    w = _watch(request)
    _known(w, sid)
    r = await asyncio.to_thread(repos_update.update, w.root, sid, None, True)
    await w.refresh()
    return {"id": sid, "ok": r.ok, "commits": r.commits, "refused": r.refused, "message": r.message}


@router.post("/api/repos/{sid}/update", status_code=202, response_model=RepoUpdate,
             summary="Move a mod to its branch's head: install, restart, check, roll back on failure (in the background)")
async def update_repo(sid: str, request: Request, body: UpdateBody | None = None) -> dict[str, Any]:
    w = _watch(request)
    _known(w, sid)
    b = body or UpdateBody()
    if w.busy_updating():
        raise ServiceError(409, "repo_update_running", f"{w.update_job['id']} is being updated; wait for it")
    st = await asyncio.to_thread(repos.repo_state, w.root, sid)
    refused = [p.code for p in st.problems if p.code in repos_update.REFUSE]
    if refused:
        raise ServiceError(409, "repo_refused", "; ".join(f"{p.title} (fix: {p.fix})" for p in st.problems if p.code in refused),
                           {"refused": refused})
    return await w.update(sid, to=b.to, commit=b.commit, force_busy=b.force_busy)


@router.post("/api/repos/{sid}/pin", summary="Record a mod's checkout (committed and pushed) as GAIFA's pin, staged", response_model=PinResult)
async def pin_repo(sid: str, request: Request) -> dict[str, Any]:
    w = _watch(request)
    _known(w, sid)
    r = await w.pin(sid)
    if r["refused"]:
        raise ServiceError(409, "repo_refused", r["message"], {"refused": r["refused"]})
    return {k: r[k] for k in PinResult.model_fields}
