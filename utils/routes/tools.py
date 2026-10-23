"""The `tools` area (plan 13.1–13.2): the catalog, calls and approvals.

- `GET /api/tools[?names=a,b][?q=words]`, `GET /api/tools/index`
- `POST /api/tools/{name}/call {arguments, origin, mode}?wait=` → `ToolCallResult`
- `GET /api/tools/calls/{id}?wait=`, `GET /api/tools/calls/{id}/result?offset=&limit=`, `POST …/cancel`
- `GET /api/approvals[?state=]`, `GET /api/approvals/{id}`, `POST /api/approvals/{id} {approve, arguments?, remember?, confirm?}`
- `GET /api/grants[?thread=][?tool=]`, `DELETE /api/grants/{id}`, `DELETE /api/grants?thread=` (plan 25.2)
- `GET /api/judge/recent[?thread=]`, `GET /api/judge/status` (the Auto mode's judge, plan 30.3, 30.5)
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from utils.tools.api import (Approval, CallRequest, Decision, Grant, JudgedCall, JudgeStatus, ResultPage, Tool, ToolCallResult,
                             ToolIndexItem)

router = APIRouter(tags=["tools"])
WAIT_MAX = 3600


def _hub(request: Request) -> Any:
    return request.app.state.hub


@router.get("/api/tools", summary="The agent's tools with full schemas; ?names=a,b picks some, ?q=words searches (best 8)",
            response_model=list[Tool], response_model_exclude_none=True)
async def list_tools(request: Request, names: str | None = None, q: str | None = None,
                     view: Literal["full", "model"] = Query("full", description="model: x-options rendered into the descriptions (what a model reads)")) -> list[dict[str, Any]]:
    from utils.server import HubError

    cat = _hub(request).tools
    if q is not None:
        return [t.public(view=view) for t in await cat.search(q)]
    tools = await cat.tools()
    if names:
        want = [n.strip() for n in names.split(",") if n.strip()]
        by = {t.name: t for t in tools}
        missing = [n for n in want if n not in by]
        if missing:
            close = {n: await cat.close_matches(n) for n in missing}
            raise HubError(404, "unknown_tool", f"no tool {', '.join(missing)}", {"close": close})
        return [by[n].public(view=view) for n in want]
    return [t.public(view=view) for t in tools]


@router.get("/api/tools/index", summary="Every tool's name, mod, risk and one-line summary (the deferred list)",
            response_model=list[ToolIndexItem], response_model_exclude_none=True)
async def tools_index(request: Request) -> list[dict[str, Any]]:
    return [t.public(full=False) for t in await _hub(request).tools.tools()]


@router.post("/api/tools/{name}/call", summary="Call a tool: validated, checked against permissions; asks for approval when needed",
             response_model=ToolCallResult, response_model_exclude_none=True)
async def call_tool(name: str, body: CallRequest, request: Request,
                    wait: float = Query(1800, ge=0, le=WAIT_MAX, description="Seconds to wait for the result")) -> dict[str, Any]:
    return await _hub(request).calls.call(name, body.arguments, body.origin, body.mode, wait)


@router.get("/api/tools/calls/{call_id}", summary="A call's state, and its result when done", response_model=ToolCallResult,
            response_model_exclude_none=True)
async def get_call(call_id: str, request: Request, wait: float = Query(0, ge=0, le=WAIT_MAX),
                   changed: bool = Query(False, description="With wait: return at the call's next progress, not only at its end (plan 44.2)")) -> dict[str, Any]:
    from utils.server import HubError

    out = await _hub(request).calls.status(call_id, wait, changed)
    if (out.get("error") or {}).get("code") == "unknown_call":
        raise HubError(404, "not_found", out["error"]["detail"])
    return out


@router.get("/api/tools/calls/{call_id}/result", summary="A finished call's full result as text, a page at a time",
            response_model=ResultPage)
async def call_result(call_id: str, request: Request, offset: int = Query(0, ge=0),
                      limit: int = Query(8000, ge=1, le=100_000)) -> dict[str, Any]:
    from utils.server import HubError

    res = await _hub(request).calls.full_result(call_id)
    if res is None:
        raise HubError(404, "not_found", f"no finished result for {call_id!r}")
    text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=1, default=str)
    return {"call_id": call_id, "offset": offset, "limit": limit, "total": len(text), "text": text[offset:offset + limit]}


@router.post("/api/tools/calls/{call_id}/cancel", summary="Cancel a running call (and its job at the mod)",
             response_model=ToolCallResult, response_model_exclude_none=True)
async def cancel_call(call_id: str, request: Request) -> dict[str, Any]:
    return await _hub(request).calls.cancel(call_id)


async def _with_schema(hub: Any, a: dict[str, Any]) -> dict[str, Any]:
    t = await hub.tools.get(a["tool"])
    if t is not None:
        a["schema"], a["description"] = t.parameters, t.description
        if t.grant_key:
            a["grant_key"] = t.grant_key
    return a


class ToolUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    calls: int
    errors: int
    refused: int
    cards: int
    edited: int
    denied: int
    mean_ms: int | None = None


@router.get("/api/tools/usage", summary="Per tool over the last ?days= (30): calls, errors, refusals, cards, cards the user changed, "
            "denials and the mean time; real calls only (plan 21.7)", response_model=list[ToolUsage])
async def tool_usage(request: Request, days: float = Query(30, gt=0, le=400)) -> list[dict[str, Any]]:
    import time

    from utils.tools.records import usage

    return await usage(_hub(request).db, time.time() - days * 86400)


@router.get("/api/approvals", summary="Approvals: pending by default; ?state=all for every one",
            response_model=list[Approval], response_model_exclude_none=True)
async def list_approvals(request: Request, state: str = "pending", limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
    hub = _hub(request)
    rows = await hub.approvals.list(None if state == "all" else state, limit)
    return [await _with_schema(hub, a) for a in rows]


@router.get("/api/approvals/{approval_id}", summary="One approval, with its tool's schema (the parameter card)",
            response_model=Approval, response_model_exclude_none=True)
async def get_approval(approval_id: str, request: Request) -> dict[str, Any]:
    from utils.server import HubError

    hub = _hub(request)
    a = await hub.approvals.get(approval_id)
    if a is None:
        raise HubError(404, "not_found", f"no approval {approval_id!r}")
    return await _with_schema(hub, a)


@router.post("/api/approvals/{approval_id}", summary="Approve (optionally with edited arguments, which are what runs; "
             "remember: thread | always also writes a grant) or deny", response_model=ToolCallResult, response_model_exclude_none=True)
async def decide_approval(approval_id: str, body: Decision, request: Request,
                          wait: float = Query(0, ge=0, le=WAIT_MAX, description="Seconds to wait for the result")) -> dict[str, Any]:
    return await _hub(request).calls.decide(approval_id, body.approve, body.arguments, body.reason, wait,
                                            body.remember, body.confirm, body.grant_hours)


class GrantsDeleted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: int


@router.get("/api/grants", summary="Grants: tools the user allowed in a chat or always (plan 25.2), newest first; ?thread=, ?tool=",
            response_model=list[Grant], response_model_exclude_none=True)
async def list_grants(request: Request, thread: str | None = None, tool: str | None = None) -> list[dict[str, Any]]:
    return await _hub(request).grants.list(thread, tool)


@router.delete("/api/grants/{grant_id}", summary="Revoke a grant: its calls ask again", response_model=GrantsDeleted)
async def revoke_grant(grant_id: str, request: Request) -> dict[str, Any]:
    from utils.server import HubError

    if not await _hub(request).grants.revoke(grant_id):
        raise HubError(404, "not_found", f"no grant {grant_id!r}")
    return {"deleted": 1}


@router.delete("/api/grants", summary="Revoke a chat's grants (?thread=, required): the agent calls it when it deletes a chat",
               response_model=GrantsDeleted)
async def revoke_thread_grants(request: Request, thread: str = Query(..., min_length=1)) -> dict[str, Any]:
    return {"deleted": await _hub(request).grants.end_thread(thread)}


@router.get("/api/judge/recent", summary="Calls the Auto mode's judge decided, newest first (plan 30.5): what ran and what asked, "
            "with the reason; ?thread=", response_model=list[JudgedCall], response_model_exclude_none=True)
async def judged_recent(request: Request, thread: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    where, args = ("WHERE thread = ?", (thread,)) if thread else ("", ())
    from utils.tools.judge_user import suggest

    rows = await _hub(request).db.fetchall(f"SELECT * FROM judged {where} ORDER BY ts DESC, id DESC LIMIT ?", (*args, limit))
    out = [dict(r) for r in rows]
    for r in out:     # asked by the model (the rules weren't sure): your allow rule could cover it
        prefix = f"{r['tool']}: "
        if r["verdict"] == "ask" and r["source"] in ("model", "fail-closed") and r["tool"] in ("workspace_run", "workspace_shell") \
                and r["summary"].startswith(prefix) and "… (cut:" not in r["summary"]:
            r["suggest"] = suggest(r["summary"][len(prefix):]) or None
    return out


@router.get("/api/judge/status", summary="Whether the judge's model answers (Auto is offered only when it does)",
            response_model=JudgeStatus)
async def judge_status(request: Request) -> dict[str, Any]:
    from utils.tools.judge import status

    return await status(_hub(request).config)
