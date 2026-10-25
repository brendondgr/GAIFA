"""`/mcp` (plan 13.4): the agent's tools over MCP, streamable HTTP, stateless (`utils/tools/mcp.py`).

- `POST /mcp`: one JSON-RPC message → one `application/json` response (202 for a notification)
- `GET`/`DELETE /mcp`: 405 (no server-initiated stream, no sessions)

Add it to Claude Code with `claude mcp add --transport http gaifa http://127.0.0.1:7000/mcp`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter(tags=["mcp"])

RPC = {"content": {"application/json": {"schema": {"type": "object"}}}}


def _server(request: Request) -> Any:
    from utils.tools.mcp import McpServer

    srv = getattr(request.app.state, "mcp", None)
    if srv is None:
        srv = request.app.state.mcp = McpServer(request.app.state.hub)
    return srv


@router.post("/mcp", summary="MCP endpoint (streamable HTTP, stateless): GAIFA's tools for Claude Code and other MCP clients",
             response_class=JSONResponse,
             responses={200: {"description": "A JSON-RPC response", **RPC},
                        202: {"description": "A notification, accepted"},
                        400: {"description": "Parse error, invalid request or params, header mismatch, unsupported version", **RPC},
                        403: {"description": "The Origin header isn't a loopback page", **RPC},
                        404: {"description": "Unknown method (2026-07-28 requests)", **RPC}})
async def mcp_post(request: Request) -> Response:
    base = f"{request.url.scheme}://{request.url.netloc}"
    status, body = await _server(request).handle(await request.body(), request.headers, base)
    if body is None:
        return Response(status_code=status)
    return JSONResponse(body, status_code=status)


@router.api_route("/mcp", methods=["GET", "DELETE"], include_in_schema=False)
async def mcp_other() -> Response:
    return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Method Not Allowed: POST JSON-RPC to /mcp"}},
                        status_code=405, headers={"Allow": "POST"})
