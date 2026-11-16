"""The `setup` area (plan capability-enablement 3.1): set mods up from the app, the same `gaifa setup` a person runs.

`GET /api/setup/plan?ids=` (everything to see before saying yes), `POST /api/setup {ids, answers}` (202: the job, one at a
time, `409 setup_busy`), `GET /api/setup/job` (the current or last job), `DELETE /api/setup/job` (stop it),
`POST /api/setup/test?id=` (the mod's test on this machine). Progress comes as `{type: "setup", job}` events. Writes are
refused from a device on the network (utils/lan/limits.py).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["setup"])


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupStart(_Model):
    ids: list[str] = Field(description="Mod or setup ids, as `gaifa setup` takes them")
    answers: dict[str, Any] = Field(default_factory=dict, description="As `gaifa setup --answers`: accept, decline, done, models, values")


class SetupJob(_Model):
    id: str
    ids: list[str]
    state: Literal["running", "done", "failed", "needs_you", "cancelled"]
    started_ts: float
    finished_ts: float | None = None
    lines: list[str] = Field(default_factory=list, description="The last progress lines (gaifa setup's stderr)")
    report: Any = Field(None, description="gaifa setup's JSON report once it ends")
    needs: dict[str, Any] | None = Field(None, description="needs_you: the questions, the steps for the person, host problems")
    error: str | None = None
    started: list[dict[str, Any]] = Field(default_factory=list, description="done: each mod started after setup, {id, state, error?}")


class SetupJobView(_Model):
    job: SetupJob | None = Field(description="The running or last job; null before the first")


class SetupAbout(_Model):
    id: str
    name: str
    provides: str
    description: str
    folder: str
    port: int | None
    recommended: bool
    installed: bool
    last_test: dict[str, Any] | None = Field(None, description="capability-enablement 7.2: the mod's last test on this machine (its sentence, numbers and advice)")


class SetupPlan(BaseModel):
    """`gaifa setup --plan --json`'s object as it is (its keys can grow with the CLI), plus `about`."""
    model_config = ConfigDict(extra="allow")
    stage: str
    about: list[SetupAbout]


class SetupTest(_Model):
    id: str
    passed: bool
    seconds: float
    device: str | None = None
    run: str
    log: str
    output: str = ""
    sentence: str = Field("", description="capability-enablement 7.2: what it measured, in one sentence")
    measured: dict[str, Any] = Field(default_factory=dict, description="The mod's own numbers (its /v1/selftest)")
    advice: list[str] = Field(default_factory=list, description="When it failed or ran on the CPU though a GPU was expected: what could help")
    at: float | None = Field(None, description="When it ran")


def _jobs(request: Request) -> Any:
    return request.app.state.hub.setup


@router.get("/api/setup/plan", summary="What setting these mods up would do (gaifa setup --plan --json)", response_model=SetupPlan)
async def get_plan(request: Request, ids: str) -> dict[str, Any]:
    return await _jobs(request).plan(ids.split(","))


@router.post("/api/setup", summary="Set mods up (a job: progress as setup events)", status_code=202, response_model=SetupJob)
async def start_setup(body: SetupStart, request: Request) -> dict[str, Any]:
    return await _jobs(request).start(body.ids, body.answers)


@router.get("/api/setup/job", summary="The running or last setup job", response_model=SetupJobView)
async def get_job(request: Request) -> dict[str, Any]:
    return {"job": _jobs(request).public()}


@router.delete("/api/setup/job", summary="Stop the running setup", response_model=SetupJobView)
async def cancel_job(request: Request) -> dict[str, Any]:
    return {"job": await _jobs(request).cancel()}


class SetupPrompt(_Model):
    text: str = Field(description="The prompt to paste into your own coding agent, with this clone's path and the mods")


@router.get("/api/setup/prompt", summary="A prompt for your own coding agent to set these mods up", response_model=SetupPrompt)
async def get_prompt(request: Request, ids: str = "") -> dict[str, Any]:
    from utils.setup_jobs import check_ids
    from utils.setup_prompt import coding_agent_prompt

    return {"text": coding_agent_prompt(request.app.state.hub.paths.root, check_ids(ids.split(",")) if ids else [])}


@router.post("/api/setup/test", summary="Run a mod's test on this machine (its setup doc's smoke)", response_model=SetupTest)
async def test_mod(request: Request, id: str) -> dict[str, Any]:
    return await _jobs(request).test(id)
