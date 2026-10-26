"""MCP servers: GAIFA's MCP client (plan mcp-client). Other MCP servers' tools in GAIFA's chats.

GAIFA runs this as `.venv/bin/python server.py` with GAIFA_PORT, GAIFA_ROOT, GAIFA_OUTPUTS and GAIFA_URL set
(architecture §4.4). MCP_STATE (default `$GAIFA_ROOT/data/state/mcp`) holds `servers.json`; secrets a server's config
names as `${NAME}` are in this folder's `.env`.

- **Servers** (`servers.py`): stdio programs or Streamable HTTP endpoints; one session each (`client.py`).
- **Approval** (2.1): a server's tools are listed, screened by the hub's fixed patterns and fingerprinted; only then do
  they reach the hub, from the approved list (`GET /v1/tools`, the hub's `tools_source`). A server whose tools change
  is held until approved again; `tools_rev` in the status tells the hub to read the tools again.
- **Calls** (`POST /v1/call/{server}/{tool}`): the hub's permissions decided first; results as text, outputs
  (pictures, sound) and structured content (`tools.py`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import tools as T
from client import Pool, ServerError
from servers import ServerIn, ServerPatch, Servers, public

HERE = Path(__file__).resolve().parent


class Approve(BaseModel):
    hash: str = Field(description="The fingerprint the user looked at (GET /v1/servers/{id}?tools=true): a newer list isn't approved unseen")


def rev(servers: list[dict[str, Any]], held: set[str]) -> str:
    key = [(s["id"], (s.get("approved") or {}).get("hash"), s.get("enabled"), sorted(s.get("deny") or []),
            sorted((s.get("risks") or {}).items()), s["id"] in held) for s in servers]
    return hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()[:12]


def create_app(state: Path, outputs: Path, hub_url: str = "", logs: Path | None = None, env_file: Path | None = None,
               idle_s: float = 15 * 60) -> FastAPI:
    servers = Servers(state, env_file or HERE / ".env")
    pool = Pool(servers, logs, idle_s)
    held: dict[str, dict[str, Any]] = {}          # server → {hash, diff}: its live tools no longer match the approved ones
    counts = {"calls": 0, "errors": 0}

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        stop = asyncio.Event()
        reaper = asyncio.create_task(pool.reap(stop))
        try:
            yield
        finally:
            stop.set()
            reaper.cancel()
            await pool.stop_all()

    app = FastAPI(title="MCP servers", version="0.1.0", lifespan=lifespan,
                  description="Other MCP servers' tools for GAIFA's chats: approved, fingerprinted, called through the hub.")
    app.state.pool, app.state.servers = pool, servers

    def need(sid: str) -> dict[str, Any]:
        s = servers.get(sid)
        if s is None:
            raise ServerError("not_found", f"there is no MCP server {sid!r}", 404)
        return s

    @app.exception_handler(ServerError)
    async def server_error(_: Request, e: ServerError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code}, e.status)

    async def live(sid: str, fresh: bool = True) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
        """The server's tools now, their fingerprint, and whether that holds the server (it changed since approval)."""
        tl = await pool.list_tools(sid, fresh=fresh)
        h, per = T.fingerprint(tl)
        appr = (servers.get(sid) or {}).get("approved")
        if appr and appr.get("hash") != h:
            held[sid] = {"hash": h, "diff": T.diff(appr.get("tools"), per)}
        else:
            held.pop(sid, None)
        return tl, h, per

    def approval(s: dict[str, Any]) -> dict[str, Any]:
        if s["id"] in held:
            return {"state": "changed", **held[s["id"]]}
        if not s.get("approved"):
            return {"state": "needs_approval"}
        return {"state": "approved", "at": s["approved"].get("at"), "tools": len(s["approved"].get("tools") or {})}

    def row(s: dict[str, Any]) -> dict[str, Any]:
        return {**public(s), "approved": None if not s.get("approved") else {k: v for k, v in s["approved"].items() if k != "list"},
                "approval": approval(s), "session": pool.state(s["id"])}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/status", summary="Servers, the running ones, the tools offered; tools_rev changes when they do")
    def status() -> dict:
        rows = servers.list()
        offered = sum(len(T.rows(s, (s.get("approved") or {}).get("list") or [])) for s in rows
                      if s.get("enabled", True) and s.get("approved") and s["id"] not in held)
        running = [sid for sid, c in pool.conns.items() if c.client is not None]
        return {"loaded": None, "busy": False, "tools_rev": rev(rows, set(held)),
                "stats": [{"label": "Servers", "value": len(rows)}, {"label": "Running", "value": len(running)},
                          {"label": "Tools offered", "value": offered}, {"label": "Calls", "value": counts["calls"]}],
                "jobs": []}

    @app.get("/v1/servers", summary="The configured MCP servers, each with its approval and session state")
    def list_servers() -> list:
        return [row(s) for s in servers.list()]

    @app.post("/v1/servers", status_code=201, summary="Add an MCP server (its tools wait for approval)")
    def add(body: ServerIn) -> Any:
        try:
            return row(servers.add(body))
        except KeyError:
            return JSONResponse({"detail": f"there is already a server {body.id!r}", "code": "exists"}, 409)

    @app.get("/v1/servers/{sid}", summary="One server; ?tools=true starts it and lists its tools now, with their fingerprint")
    async def get(sid: str, tools: bool = False) -> dict:
        s = need(sid)
        if not tools:
            return row(s)
        tl, h, per = await live(sid)
        out = row(s)
        if tools:
            out.update(tools=[{**t, "risk": T.risk_of(t, s.get("risks")), "hash": per[t["name"]],
                               "denied": t["name"] in (s.get("deny") or [])} for t in tl], hash=h, approval=approval(s))
        return out

    @app.patch("/v1/servers/{sid}", summary="Change a server: its launch (its tools are approved again), on or off, risks, denied tools")
    async def patch(sid: str, body: ServerPatch) -> dict:
        need(sid)
        changed = servers.update(sid, body.model_dump(exclude_unset=True))
        if any(k in body.model_fields_set for k in ("command", "args", "cwd", "env", "url", "headers", "enabled")):
            await pool.stop(sid)
            held.pop(sid, None)
        return row(changed)

    @app.delete("/v1/servers/{sid}", summary="Remove a server (stops it)")
    async def delete(sid: str) -> Any:
        await pool.stop(sid)
        held.pop(sid, None)
        if not servers.remove(sid):
            return JSONResponse({"detail": f"there is no MCP server {sid!r}", "code": "not_found"}, 404)
        return {"deleted": sid}

    @app.post("/v1/servers/{sid}/start", summary="Start a server now (otherwise it starts at its first call)")
    async def start(sid: str) -> dict:
        need(sid)
        await live(sid)
        return row(need(sid))

    @app.post("/v1/servers/{sid}/stop", summary="Stop a server's session")
    async def stop(sid: str) -> dict:
        need(sid)
        await pool.stop(sid)
        return row(need(sid))

    @app.post("/v1/servers/{sid}/approve", summary="Approve the server's tools as they are now (the fingerprint you looked at)")
    async def approve(sid: str, body: Approve) -> Any:
        s = need(sid)
        tl, h, per = await live(sid)
        if h != body.hash:
            return JSONResponse({"detail": "the server's tools changed since you looked: look again", "code": "changed",
                                 "data": {"hash": h, "diff": T.diff((s.get("approved") or {}).get("tools"), per)}}, 409)
        findings = await screen(tl)
        deny = sorted(set(s.get("deny") or []) | {f["tool"] for f in findings})
        servers.update(sid, {"approved": {"hash": h, "at": time.strftime("%Y-%m-%d %H:%M"), "tools": per, "list": tl,
                                          "findings": findings}, "deny": deny})
        held.pop(sid, None)
        return row(need(sid))

    async def screen(tl: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Each tool's description and schema text through the hub's fixed patterns (POST /api/screen)."""
        if not hub_url:
            return []
        out = []
        async with httpx.AsyncClient(timeout=30) as c:
            for t in tl:
                text = (t.get("description") or "") + "\n\n" + json.dumps(t.get("inputSchema") or {}, ensure_ascii=False)
                try:
                    r = await c.post(f"{hub_url.rstrip('/')}/api/screen", json={"text": text})
                    out += [{"tool": t["name"], "why": f["why"], "excerpt": f["excerpt"]} for f in r.json().get("findings") or []]
                except (httpx.HTTPError, ValueError):
                    out.append({"tool": t["name"], "why": "not checked (the hub didn't answer)", "excerpt": ""})
        return out

    @app.get("/v1/tools", summary="The agent's tools: every approved, enabled server's (its tools_source)")
    def agent_tools() -> dict:
        out = []
        for s in servers.list():
            if s.get("enabled", True) and s.get("approved") and s["id"] not in held:
                out += T.rows(s, s["approved"].get("list") or [])
        return {"tools": out}

    @app.post("/v1/call/{sid}/{tool}", summary="Call one of a server's tools (the hub decides permissions first)")
    async def call(sid: str, tool: str, body: dict[str, Any] = Body(default_factory=dict)) -> Any:
        s = need(sid)
        if not s.get("approved") or tool not in (s["approved"].get("tools") or {}):
            return JSONResponse({"detail": f"{sid}'s {tool} isn't approved", "code": "not_approved",
                                 "fix": "the user approves the server's tools on the MCP servers page"}, 409)
        if tool in (s.get("deny") or []):
            return JSONResponse({"detail": f"{sid}'s {tool} is turned off", "code": "denied"}, 403)
        fresh = sid not in pool.conns or pool.conns[sid].client is None
        await live(sid, fresh=fresh)                  # a new session: check the tools still match what was approved
        if sid in held:
            return JSONResponse({"detail": f"{sid}'s tools changed since they were approved", "code": "changed",
                                 "fix": "the user looks at the change and approves it on the MCP servers page"}, 409)
        counts["calls"] += 1
        args = body.get("arguments") if isinstance(body.get("arguments"), dict) else body
        conn = pool.conns.get(sid)
        if conn is not None:
            conn.asked = None
        try:
            r = await pool.call(sid, tool, args)
            out = T.result(sid, tool, r, outputs)
        except ValueError as e:
            counts["errors"] += 1
            return JSONResponse({"detail": str(e), "code": "tool_error"}, 422)
        if conn is not None and conn.asked:
            out["asked"] = conn.asked
            out["note"] = ("the server asked for more (shown in asked), which GAIFA can't show as a form yet: ask the "
                           "user, then call again with the answer in the arguments")
        return out

    return app


if __name__ == "__main__":
    root = Path(os.environ.get("GAIFA_ROOT", HERE.parents[1]))
    app = create_app(Path(os.environ.get("MCP_STATE") or root / "data" / "state" / "mcp"),
                     Path(os.environ.get("GAIFA_OUTPUTS", "outputs")), os.environ.get("GAIFA_URL", ""),
                     root / "data" / "logs")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("GAIFA_PORT", "5108")), log_level="warning")
