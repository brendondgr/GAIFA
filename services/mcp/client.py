"""Sessions with MCP servers (plan mcp-client 1.2), through the `mcp` SDK's Client.

One session per server for the whole machine (not per chat): started on first use, kept while it's used, stopped
after `idle_s` without a call. A stdio server runs with a minimal environment (the SDK's: HOME, LOGNAME, PATH,
SHELL, TERM, USER, plus LANG) and its own variables, its stderr in `<logs>/mcp-<id>.log`; an HTTP server gets its
headers. Each session lives in one task (the SDK's context must be entered and left in the same task); calls come
from any task. A session that breaks is stopped and starts again at the next call; a call is never sent twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mcp
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from servers import expand

log = logging.getLogger("mcp.client")
START_S = 60.0            # a server has this long to start and answer
CALL_S = 120.0            # a tool call's default limit
IDLE_S = 15 * 60


class ServerError(Exception):
    def __init__(self, code: str, detail: str, status: int = 502) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


@dataclass
class Conn:
    sid: str
    task: asyncio.Task[Any] | None = None
    client: Any = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    error: str | None = None
    started: float = 0.0
    last_used: float = 0.0
    restarts: int = 0
    tools: list[dict[str, Any]] | None = None
    listed: float = 0.0
    asked: str | None = None             # what the server last asked for (an elicitation, declined)


def target(spec: dict[str, Any], secrets_: dict[str, str], logs: Path | None) -> tuple[Any, list[str]]:
    """What mcp.Client connects to for this server, and the ${NAMES} its config uses that aren't set."""
    if spec.get("transport") == "http":
        headers, missing = expand(spec.get("headers") or {}, secrets_)
        return streamable_http_client(spec["url"], http_client=create_mcp_http_client(headers=headers or None)), missing
    env, missing = expand(spec.get("env") or {}, secrets_)
    if os.environ.get("LANG"):
        env.setdefault("LANG", os.environ["LANG"])
    params = StdioServerParameters(command=spec["command"], args=list(spec.get("args") or []), env=env or None,
                                   cwd=spec.get("cwd") or None)
    errlog = None
    if logs is not None:
        logs.mkdir(parents=True, exist_ok=True)
        errlog = open(logs / f"mcp-{spec['id']}.log", "a", buffering=1)     # noqa: SIM115: kept for the session's life
    return (stdio_client(params, errlog=errlog) if errlog else stdio_client(params)), missing


def listening(host: str, port: int) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


class Pool:
    def __init__(self, servers: Any, logs: Path | None = None, idle_s: float = IDLE_S) -> None:
        self.servers, self.logs, self.idle_s = servers, logs, idle_s
        self.conns: dict[str, Conn] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.companions: dict[str, asyncio.subprocess.Process] = {}     # the ones this mod started

    async def companion(self, spec: dict[str, Any]) -> None:
        """Start the server's companion (mcp-client 5.1) unless something already answers on its port."""
        c = spec.get("companion")
        if not c or listening(c.get("host", "localhost"), c["port"]):
            return
        proc = self.companions.get(spec["id"])
        if proc is None or proc.returncode is not None:
            if self.logs:
                self.logs.mkdir(parents=True, exist_ok=True)
            out = open(self.logs / f"mcp-{spec['id']}-companion.log", "a", buffering=1) if self.logs else asyncio.subprocess.DEVNULL   # noqa: SIM115
            proc = await asyncio.create_subprocess_exec(c["command"], *c.get("args", []), stdin=asyncio.subprocess.DEVNULL,
                                                        stdout=out, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            self.companions[spec["id"]] = proc
        deadline = time.time() + float(c.get("wait_s") or 60)
        while time.time() < deadline:
            if listening(c.get("host", "localhost"), c["port"]):
                return
            if proc.returncode is not None:
                raise ServerError("companion_failed", f"{spec['id']}'s companion ({c['command']}) exited with {proc.returncode}: "
                                  f"see data/logs/mcp-{spec['id']}-companion.log")
            await asyncio.sleep(0.25)
        raise ServerError("companion_timeout", f"{spec['id']}'s companion didn't listen on port {c['port']} in time", 504)

    async def stop_companion(self, sid: str) -> None:
        proc = self.companions.pop(sid, None)
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()

    async def _run(self, conn: Conn, tgt: Any) -> None:
        async def decline(_ctx: Any, params: Any) -> Any:      # plan mcp-client 2.2: no form to show; say what it asked
            conn.asked = getattr(params, "message", None) or str(params)[:400]
            return mcp.types.ElicitResult(action="decline")
        try:
            async with mcp.Client(tgt, read_timeout_seconds=CALL_S, elicitation_callback=decline) as c:
                conn.client, conn.error = c, None
                conn.ready.set()
                await conn.stop.wait()
        except BaseException as e:  # noqa: BLE001: the server failed to start, or died; the next call tries again
            if not isinstance(e, asyncio.CancelledError):
                conn.error = _why(e)
                log.warning("server %s: %s", conn.sid, conn.error)
        finally:
            conn.client = None
            conn.ready.set()

    async def get(self, sid: str) -> Any:
        """The server's live client, starting it if needed (and once more if it died)."""
        lock = self._locks.setdefault(sid, asyncio.Lock())
        async with lock:
            conn = self.conns.get(sid)
            if conn is not None and conn.client is not None and not conn.task.done():
                conn.last_used = time.time()
                return conn.client
            spec = self.servers.get(sid)
            if spec is None:
                raise ServerError("not_found", f"there is no MCP server {sid!r}", 404)
            if not spec.get("enabled", True):
                raise ServerError("disabled", f"the MCP server {sid} is turned off", 409)
            tgt, missing = target(spec, self.servers.secrets(), self.logs)
            if missing:
                raise ServerError("missing_secret", f"{sid} needs {', '.join(missing)} in services/mcp/.env", 409)
            await self.companion(spec)
            restarts = (conn.restarts + 1) if conn is not None else 0
            conn = Conn(sid, started=time.time(), last_used=time.time(), restarts=restarts)
            self.conns[sid] = conn
            conn.task = asyncio.create_task(self._run(conn, tgt))
            try:
                await asyncio.wait_for(conn.ready.wait(), timeout=START_S)
            except asyncio.TimeoutError:
                await self.stop(sid)
                raise ServerError("start_timeout", f"{sid} didn't answer within {START_S:.0f} s", 504) from None
            if conn.client is None:
                raise ServerError("start_failed", f"{sid} didn't start: {conn.error or 'it exited'}")
            return conn.client

    async def list_tools(self, sid: str, fresh: bool = False) -> list[dict[str, Any]]:
        conn = self.conns.get(sid)
        if conn is not None and conn.tools is not None and not fresh and conn.client is not None:
            return conn.tools
        c = await self.get(sid)
        out, cursor = [], None
        for _ in range(50):                      # pages
            r = await c.list_tools(cursor=cursor, cache_mode="refresh" if fresh else "use")
            out += [t.model_dump(mode="json", exclude_none=True, by_alias=True) for t in r.tools]
            cursor = getattr(r, "next_cursor", None) or getattr(r, "nextCursor", None)
            if not cursor:
                break
        conn = self.conns[sid]
        conn.tools, conn.listed = sorted(out, key=lambda t: t["name"]), time.time()
        return conn.tools

    async def call(self, sid: str, tool: str, args: dict[str, Any], timeout: float = CALL_S) -> Any:
        """One call. A call is never sent twice (it may have done something before the connection broke): a session
        that broke under it is stopped, so the next call starts a new one."""
        c = await self.get(sid)
        try:
            return await asyncio.wait_for(c.call_tool(tool, args), timeout=timeout)
        except asyncio.TimeoutError:
            raise ServerError("timeout", f"{sid}'s {tool} didn't finish within {timeout:.0f} s", 504) from None
        except Exception as e:  # noqa: BLE001
            conn = self.conns.get(sid)
            if conn is None or conn.task is None or conn.task.done() or conn.client is None or _closed(e):
                await self.stop(sid)
                raise ServerError("call_failed", f"{sid}'s {tool}: the server's connection closed ({_why(e)}); "
                                  "it starts again at the next call") from None
            raise ServerError("call_failed", f"{sid}'s {tool}: {_why(e)}") from None

    async def stop(self, sid: str) -> bool:
        conn = self.conns.pop(sid, None)
        await self.stop_companion(sid)
        if conn is None:
            return False
        conn.stop.set()
        if conn.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(conn.task), timeout=10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                conn.task.cancel()
        return True

    async def stop_all(self) -> None:
        for sid in list(self.conns):
            await self.stop(sid)

    async def reap(self, stop: asyncio.Event, every: float = 60) -> None:
        """Stop servers nobody called for `idle_s`."""
        while not stop.is_set():
            now = time.time()
            for sid, conn in list(self.conns.items()):
                if conn.client is not None and now - conn.last_used > self.idle_s:
                    log.info("server %s idle: stopping it", sid)
                    await self.stop(sid)
            try:
                await asyncio.wait_for(stop.wait(), timeout=every)
            except asyncio.TimeoutError:
                pass

    def state(self, sid: str) -> dict[str, Any]:
        conn = self.conns.get(sid)
        proc = self.companions.get(sid)
        if conn is None:
            return {"state": "stopped"}
        if proc is not None and proc.returncode is None:
            return {**self._state(conn), "companion": "running"}
        return self._state(conn)

    def _state(self, conn: Conn) -> dict[str, Any]:
        if conn.client is not None:
            return {"state": "running", "since": conn.started, "last_used": conn.last_used}
        return {"state": "failed" if conn.error else "starting", **({"error": conn.error} if conn.error else {})}


def _closed(e: BaseException) -> bool:
    """The session's connection is gone (the process ended, the socket closed)."""
    import anyio
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return isinstance(e, (anyio.ClosedResourceError, anyio.BrokenResourceError, EOFError, ConnectionError)) or \
        "connection closed" in str(e).lower()


def _why(e: BaseException) -> str:
    """The first useful line of an error, also out of an exception group."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return f"{type(e).__name__}: {e}"[:400]
