"""The `tools` area (plan 13.1–13.2): the catalog, calls and approvals.

- `GET /api/tools[?names=a,b][?q=words]`, `GET /api/tools/index`
- `POST /api/tools/{name}/call {arguments, origin, mode}?wait=` → `ToolCallResult`
- `GET /api/tools/calls/{id}?wait=`, `GET /api/tools/calls/{id}/result?offset=&limit=`, `POST …/cancel`
- `GET /api/approvals[?state=]`, `GET /api/approvals/{id}`, `POST /api/approvals/{id} {approve, arguments?}`
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from utils.tools.api import Approval, CallRequest, Decision, ResultPage, Tool, ToolCallResult, ToolIndexItem

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
async def get_call(call_id: str, request: Request, wait: float = Query(0, ge=0, le=WAIT_MAX)) -> dict[str, Any]:
    from utils.server import HubError

    out = await _hub(request).calls.status(call_id, wait)
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
    return a


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


@router.post("/api/approvals/{approval_id}", summary="Approve (optionally with edited arguments, which are what runs) or deny",
             response_model=ToolCallResult, response_model_exclude_none=True)
async def decide_approval(approval_id: str, body: Decision, request: Request,
                          wait: float = Query(0, ge=0, le=WAIT_MAX, description="Seconds to wait for the result")) -> dict[str, Any]:
    return await _hub(request).calls.decide(approval_id, body.approve, body.arguments, body.reason, wait)
