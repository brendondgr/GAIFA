"""Tool calls (plan 13.2): validate, check permissions, ask, run, follow jobs, shape results.

Every call answers with one shape, `{status, tool, …}`:

- `needs_approval`: `{approval_id, arguments, ask_fields, schema, risk, description}`; nothing ran
- `denied`: `{error: {code, detail, fix}}`
- `running`: `{call_id, progress, job_id}`: still going after `wait` seconds (`GET /api/tools/calls/{id}`)
- `done`: `{call_id, result, outputs}`; `outputs` are `{output_id, ref, url, kind, title, summary}`
- `error`: `{call_id?, error: {code, detail, fix}}`
- `cancelled`: `{call_id}`

A call runs as a task in the hub, so a client that disconnects doesn't stop it; its state and full
result are kept in `tool_calls`. Calls that were following a job when the hub stopped are picked up
again at the next start. A stopped mod is started first. Requests carry `X-AIHub-Make-Room: 1`
(when `agent.make_room`), so a model that needs memory unloads idle mods instead of failing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from utils.services import ServiceError
from utils.tools import results
from utils.tools.approvals import MODES, Approvals, decide
from utils.tools.catalog import Catalog, ToolDef
from utils.tools.modcall import ToolError, dry_run, mod_error
from utils.tools import edits, options
from utils.tools.schema import coerce, validate

if TYPE_CHECKING:
    from utils.server import Hub

log = logging.getLogger("aihub.tools")
DONE = {"done", "complete", "completed", "succeeded", "success", "finished"}
FAILED = {"failed", "error", "errored"}
CANCELLED = {"cancelled", "canceled"}
FOLLOW_MAX_S = 6 * 3600
POLL_S = 2.0
DEFAULT_WAIT_S = 1800.0
OUTPUT_ID = re.compile(r"^[0-9a-f]{12}$")
PLACEHOLDER = re.compile(r"\{[^}]+\}")


@dataclass
class Call:
    id: str
    tool: ToolDef
    arguments: dict[str, Any]
    origin: dict[str, Any]
    approval_id: str | None = None
    filled: dict[str, str] = field(default_factory=dict)   # field → "default" | "pref:<id>" | "carried" (21.1)
    state: str = "running"
    progress: float | None = None
    note: str | None = None
    job_id: str | None = None
    result: Any = None
    outputs: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    task: asyncio.Task[Any] | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.state, "call_id": self.id, "tool": self.tool.name}
        if self.state == "running":
            out["progress"] = self.progress
            if self.note:
                out["note"] = self.note
            if self.job_id:
                out["job_id"] = self.job_id
            out["elapsed_s"] = round(time.time() - self.started, 1)
        elif self.state == "done":
            out["result"] = results.cap(self.result, self.id)
            out["outputs"] = self.outputs
        elif self.state == "error":
            out["error"] = self.error
        if self.approval_id:
            out["approval_id"] = self.approval_id
        return out


def _id() -> str:
    return "call_" + secrets.token_hex(6)


def _state_of(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    for k in ("state", "status"):
        v = body.get(k)
        if isinstance(v, str):
            return v.lower()
    return None


def _progress(body: Any) -> float | None:
    if not isinstance(body, dict):
        return None
    p = body.get("progress")
    if isinstance(p, (int, float)) and not isinstance(p, bool):
        return float(p) if p <= 1 else float(p) / 100
    stages = body.get("stages")
    if isinstance(stages, dict) and stages:
        total, got = len(stages), 0.0
        for st in stages.values():
            if not isinstance(st, dict):
                continue
            if st.get("state") == "done":
                got += 1
            elif st.get("state") == "running" and st.get("total"):
                got += min(1.0, float(st.get("step") or 0) / float(st["total"]))
        return round(got / total, 3)
    return None


def _job_id(body: Any) -> str | None:
    if isinstance(body, dict):
        for k in ("job_id", "id", "jid", "run_id"):
            if isinstance(body.get(k), (str, int)):
                return str(body[k])
    return None


class Calls:
    def __init__(self, hub: Hub, catalog: Catalog, approvals: Approvals) -> None:
        self.hub, self.catalog, self.approvals = hub, catalog, approvals
        self.live: dict[str, Call] = {}
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(3600, connect=10))

    async def close(self) -> None:
        for c in list(self.live.values()):
            if c.task and not c.task.done():
                c.task.cancel()
        await asyncio.gather(*(c.task for c in self.live.values() if c.task), return_exceptions=True)
        await self.client.aclose()

    # ---- entry points ------------------------------------------------------------------------

    async def call(self, name: str, arguments: Any, origin: dict[str, Any] | None = None, mode: str = "ask",
                   wait: float = DEFAULT_WAIT_S) -> dict[str, Any]:
        tool = await self.catalog.get(name)
        if tool is None:
            close = await self.catalog.close_matches(name)
            out = {"status": "error", "tool": name, "error": {
                "code": "unknown_tool", "detail": f"there is no tool {name!r}",
                "fix": (f"did you mean {', '.join(close)}? " if close else "") + "find tools with find_tools or GET /api/tools?q="}}
            await self._refused(name, arguments, origin, out["error"])
            return out
        if mode not in MODES:
            mode = "ask"
        arguments = coerce(tool.parameters, arguments if arguments is not None else {})
        arguments, filled = options.fill_defaults(tool.parameters, arguments) if isinstance(arguments, dict) else (arguments, [])
        how = {k: "default" for k in filled}
        if self.hub.prefs is not None and isinstance(arguments, dict):          # the user's preferences (plan 21.3)
            arguments, mine = await self.hub.prefs.apply(tool, arguments, origin, filled)
            how.update(mine)
            filled = [*[k for k in filled if k not in mine], *mine]
        problems = validate(tool.parameters, arguments) or options.problems(tool.parameters, arguments)
        if problems:
            out = self._invalid(tool, await self._elsewhere(tool, arguments, problems))
            await self._refused(tool.name, arguments, origin, out["error"])
            return out
        verdict, why = decide(tool.name, tool.risk, self.hub.config, mode)
        if verdict == "deny":
            out = {"status": "denied", "tool": tool.name, "error": {"code": "denied", "detail": f"{tool.name}: {why}",
                                                                   "fix": "don't retry it; tell the user it's not allowed, or ask them to change the setting"}}
            await self._refused(tool.name, arguments, origin, out["error"])
            return out
        if verdict == "ask":
            a = await self.approvals.create(tool.name, arguments, tool.ask, tool.risk, origin or {}, how)
            return self._needs(tool, a, filled)
        return await self._launch(tool, arguments, origin or {}, None, wait, filled=how)

    async def decide(self, aid: str, approve: bool, arguments: dict[str, Any] | None = None,
                     reason: str | None = None, wait: float = DEFAULT_WAIT_S) -> dict[str, Any]:
        from utils.server import HubError

        a = await self.approvals.get(aid)
        if a is None:
            raise HubError(404, "not_found", f"no approval {aid!r}")
        if a["state"] != "pending":
            raise HubError(409, "already_decided", f"approval {aid} is already {a['state']}",
                           {"state": a["state"], "call_id": a.get("call_id")})
        if not approve:
            await self.approvals.close(aid, "denied", reason=reason or "denied by the user")
            return {"status": "denied", "tool": a["tool"], "approval_id": aid,
                    "error": {"code": "denied_by_user", "detail": reason or "the user said no",
                              "fix": "don't run it again unless the user asks; ask what they'd like instead"}}
        tool = await self.catalog.get(a["tool"])
        if tool is None:
            await self.approvals.close(aid, "denied", reason="the tool is gone")
            raise HubError(404, "unknown_tool", f"{a['tool']} is no longer in the catalog")
        args = coerce(tool.parameters, arguments if arguments is not None else a["arguments"])
        if isinstance(args, dict):
            args, _ = options.fill_defaults(tool.parameters, args)
        problems = validate(tool.parameters, args) or options.problems(tool.parameters, args)
        if problems:
            raise HubError(422, "invalid_arguments", problems[0]["detail"], {"problems": problems})
        call_id = _id()
        changed = edits.edited(tool.parameters, a["arguments"], args)
        if not await self.approvals.close(aid, "approved", final=args, call_id=call_id, edited=changed):
            raise HubError(409, "already_decided", f"approval {aid} was decided meanwhile")
        filled = {k: v for k, v in (a.get("filled") or {}).items() if k not in changed}
        if self.hub.prefs is not None:
            try:
                await self.hub.prefs.after_decision(tool, {**(a.get("origin") or {}), "approval_id": aid}, args, changed, a.get("filled") or {})
            except Exception:  # noqa: BLE001: learning never blocks a call
                log.exception("preferences after approval %s", aid)
        return await self._launch(tool, args, a["origin"], aid, wait, call_id, filled=filled)

    async def status(self, call_id: str, wait: float = 0) -> dict[str, Any]:
        c = self.live.get(call_id)
        if c is not None:
            if wait and c.state == "running":
                try:
                    await asyncio.wait_for(asyncio.shield(c.done.wait()), timeout=wait)
                except asyncio.TimeoutError:
                    pass
            return c.public()
        row = await self.hub.db.fetchone("SELECT * FROM tool_calls WHERE id = ?", (call_id,))
        if row is None:
            return {"status": "error", "tool": None, "error": {"code": "unknown_call", "detail": f"no call {call_id!r}"}}
        stored = json.loads(row["result"]) if row["result"] else {}
        out = {"status": row["state"], "call_id": call_id, "tool": row["tool"]}
        if row["state"] == "done":
            out["result"] = results.cap(stored.get("result"), call_id)
            out["outputs"] = stored.get("outputs") or []
        elif row["state"] == "error":
            out["error"] = stored.get("error")
        return out

    async def full_result(self, call_id: str) -> Any:
        c = self.live.get(call_id)
        if c is not None and c.state == "done":
            return c.result
        row = await self.hub.db.fetchone("SELECT result FROM tool_calls WHERE id = ?", (call_id,))
        return json.loads(row["result"]).get("result") if row and row["result"] else None

    async def cancel(self, call_id: str) -> dict[str, Any]:
        c = self.live.get(call_id)
        if c is None or c.state != "running" or c.task is None:
            return await self.status(call_id)
        c.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(c.done.wait()), timeout=30)
        except asyncio.TimeoutError:
            pass
        return c.public()

    async def resume(self) -> int:
        """At startup: calls that were following a job pick it up again; the rest are marked failed."""
        rows = await self.hub.db.fetchall("SELECT * FROM tool_calls WHERE state = 'running'")
        n = 0
        for r in rows:
            job = json.loads(r["job"]) if r["job"] else None
            tool = await self.catalog.get(r["tool"])
            if job and tool and tool.job:
                c = Call(r["id"], tool, json.loads(r["arguments"]), json.loads(r["origin"]), r["approval_id"],
                         job_id=job.get("id"), started=r["created_ts"])
                self.live[c.id] = c
                c.task = asyncio.create_task(self._run(c, resume_job=job.get("id")))
                n += 1
            else:
                await self._store_end(r["id"], "error", {"error": {"code": "interrupted", "detail": "the hub restarted while this call ran",
                                                                 "fix": "check the mod's outputs, then call it again if needed"}})
        return n

    # ---- running -----------------------------------------------------------------------------

    def _invalid(self, tool: ToolDef, problems: list[dict[str, str]]) -> dict[str, Any]:
        detail = "; ".join(p["detail"] for p in problems[:5])
        fix = "; ".join(p["fix"] for p in problems[:5])
        return {"status": "error", "tool": tool.name, "error": {"code": "invalid_arguments", "detail": detail, "fix": fix,
                                                                "problems": problems[:10]}}

    def _needs(self, tool: ToolDef, a: dict[str, Any], filled: list[str] | None = None) -> dict[str, Any]:
        out = {"status": "needs_approval", "tool": tool.name, "approval_id": a["id"], "arguments": a["arguments"],
               "ask_fields": tool.ask, "risk": tool.risk, "schema": tool.parameters, "description": tool.description}
        if filled:
            out["filled"] = filled
        return out

    async def _elsewhere(self, tool: ToolDef, args: Any, problems: list[dict[str, str]]) -> list[dict[str, str]]:
        """An enum value this tool refuses but another tool of the same mod takes for the same
        parameter: say to call that tool (an edit workflow passed to the text-to-image tool)."""
        if not isinstance(args, dict) or not tool.mod:
            return problems
        others = [t for t in await self.catalog.tools() if t.mod == tool.mod and t.name != tool.name]
        out = []
        for p in problems:
            v, field = args.get(p.get("field", "")), p.get("field", "")
            mine = (tool.parameters.get("properties") or {}).get(field) or {}
            if isinstance(v, (str, int)) and "enum" in mine and v not in mine["enum"]:
                hit = next((t for t in others if v in (((t.parameters.get("properties") or {}).get(field) or {}).get("enum") or [])), None)
                if hit:
                    p = {**p, "fix": f"{v!r} is a {field} of {hit.name}, not of {tool.name}: call {hit.name} instead"}
            out.append(p)
        return out

    async def _launch(self, tool: ToolDef, args: dict[str, Any], origin: dict[str, Any], aid: str | None,
                      wait: float, call_id: str | None = None, filled: dict[str, str] | None = None) -> dict[str, Any]:
        c = Call(call_id or _id(), tool, args, origin, aid, filled=dict(filled or {}))
        await self.hub.db.execute(
            "INSERT INTO tool_calls (id, tool, arguments, origin, state, approval_id, created_ts, filled) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)",
            (c.id, tool.name, json.dumps(args), json.dumps(origin), aid, c.started, json.dumps(c.filled) if c.filled else None))
        self.live[c.id] = c
        c.task = asyncio.create_task(self._run(c))
        self._publish(c)
        if wait > 0:
            try:
                await asyncio.wait_for(asyncio.shield(c.done.wait()), timeout=wait)
            except asyncio.TimeoutError:
                pass
        return c.public()

    def _publish(self, c: Call) -> None:
        ev = {k: v for k, v in c.public().items() if k != "result"}
        ev["origin"] = c.origin
        self.hub.bus.publish({"type": "tool_call", "call": ev})

    async def _store_end(self, call_id: str, state: str, payload: dict[str, Any]) -> None:
        now = time.time()
        await self.hub.db.execute("UPDATE tool_calls SET state = ?, result = ?, finished_ts = ?, "
                                  "duration_ms = CAST((? - created_ts) * 1000 AS INTEGER) WHERE id = ?",
                                  (state, json.dumps(payload, default=str), now, now, call_id))

    async def _refused(self, tool: str, arguments: Any, origin: dict[str, Any] | None, error: dict[str, Any]) -> None:
        """A call refused before it ran (unknown tool, bad arguments, a choice that doesn't fit, a rule): kept for the records."""
        try:
            await self.hub.db.execute(
                "INSERT INTO tool_refusals (id, tool, arguments, origin, code, detail, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("ref_" + secrets.token_hex(6), tool, json.dumps(arguments, default=str)[:20000], json.dumps(origin or {}),
                 error.get("code", "error"), str(error.get("detail", ""))[:2000], time.time()))
        except Exception:  # noqa: BLE001: records never break a call
            log.exception("recording a refused call")

    async def _run(self, c: Call, resume_job: str | None = None) -> None:
        try:
            if c.tool.handler is not None and c.origin.get("dry_run") and c.tool.risk != "read":
                c.result = {"dry_run": True, "arguments": c.arguments}   # an eval never changes the hub (plan 21.6, 22.4)
            elif c.tool.handler is not None:
                c.result = await c.tool.handler(self.hub, c.arguments)
            else:
                await self._mod_call(c, resume_job)
            c.state = "done"
        except asyncio.CancelledError:
            c.state = "cancelled"
            await self._cancel_job(c)
        except ToolError as e:
            c.state, c.error = "error", e.body()
        except ServiceError as e:
            c.state = "error"
            c.error = {"code": e.code, "detail": e.detail}
            if e.code == "needs_room":
                c.error["fix"] = "free memory first (hub_unload_service, or stop an LLM), or turn on agent.make_room"
        except httpx.HTTPError as e:
            c.state, c.error = "error", {"code": "upstream_error", "detail": f"{type(e).__name__}: {e}"[:400],
                                         "fix": "the mod didn't answer; check its Logs tab, then try again"}
        except Exception as e:  # noqa: BLE001
            log.exception("tool call %s failed", c.id)
            c.state, c.error = "error", {"code": "hub_error", "detail": f"{type(e).__name__}: {e}"[:400]}
        finally:
            c.finished = time.time()
            payload: dict[str, Any] = {"result": c.result, "outputs": c.outputs} if c.state == "done" else {"error": c.error}
            try:
                await asyncio.shield(self._store_end(c.id, c.state if c.state != "running" else "error", payload))
            except Exception:  # noqa: BLE001
                log.exception("storing call %s", c.id)
            c.done.set()
            self._publish(c)
            asyncio.get_running_loop().call_later(600, self.live.pop, c.id, None)

    async def _ensure_up(self, c: Call) -> Any:
        mgr = self.hub.services
        try:
            svc = mgr.get(c.tool.mod or "")
        except ServiceError:
            raise ToolError("service_not_found", f"the mod {c.tool.mod!r} is gone") from None
        if not svc.up:
            if not svc.startable or not svc.eff.enabled:
                raise ToolError("service_not_running", f"{svc.mod.name} is {svc.state} and can't be started",
                                f"fix it on its page (aihub check {svc.id})")
            c.note = f"starting {svc.mod.name}"
            self._publish(c)
            svc = await mgr.start(svc.id, wait=True)
            if not svc.up:
                raise ToolError("service_not_running", f"{svc.mod.name} didn't start: {svc.last_error or svc.state}",
                                f"see its Logs tab (aihub logs {svc.id})")
            c.note = None
            await self.catalog.tools()  # its schemas may have changed with the new process
        return svc

    async def _file_value(self, value: Any, multipart: bool) -> Any:
        """`{"$file": "output:<id>"}`, `output:<id>` or a bare id → what the mod takes."""
        v = value.get("$file") if isinstance(value, dict) and "$file" in value else value
        if isinstance(v, list):
            return [await self._file_value(x, multipart) for x in v]
        if not isinstance(v, str):
            return v
        oid = v[len("output:"):] if v.startswith("output:") else (v if OUTPUT_ID.match(v) else None)
        if oid is None:
            return v
        try:
            path = await self.hub.outputs.file(oid)
        except Exception:  # noqa: BLE001
            raise ToolError("unknown_output", f"there is no output {oid!r} (it may have been deleted)",
                            "use hub_search_outputs to find it, or ask the user") from None
        if not multipart:
            return f"output:{oid}"
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return (path.name, await asyncio.to_thread(path.read_bytes), mime)

    async def _mod_call(self, c: Call, resume_job: str | None) -> None:
        if await dry_run(self.hub, c):
            return
        tool, route = c.tool, c.tool.route
        if resume_job:
            svc = await self._ensure_up(c)
            await self._follow(c, svc, resume_job)
            return
        if route is None:
            raise ToolError("tool_unavailable", f"{tool.name} has no route", tool.why)
        svc = await self._ensure_up(c)
        path, _, fixed_q = route.path.partition("?")
        query: dict[str, Any] = dict(x.split("=", 1) for x in fixed_q.split("&") if "=" in x)
        body: dict[str, Any] = {}
        files: dict[str, Any] = {}
        whole: Any = None
        props = tool.parameters.get("properties") or {}
        for k, v in {**c.arguments, **route.fixed}.items():
            if (props.get(k) or {}).get("x-kind"):
                v = await self._file_value(v, route.body == "multipart" and k in route.files)
            loc = route.params.get(k)
            if loc == "path":
                path = path.replace("{" + k + "}", quote(str(v), safe=""))
            elif loc == "query":
                query[k] = ("true" if v else "false") if isinstance(v, bool) else v
            elif k == route.body_key:
                whole = v
            elif isinstance(v, tuple):
                files[k] = v
            else:
                body[k] = v
        if PLACEHOLDER.search(path):
            raise ToolError("invalid_arguments", f"missing path value(s): {', '.join(PLACEHOLDER.findall(path))}",
                            "add them to the arguments")
        headers = {"X-AIHub-Origin": json.dumps({"tool_call": c.id, **c.origin})[:500]}
        if self.hub.config.agent.make_room:
            headers["X-AIHub-Make-Room"] = "1"
        for hook in self.hub.services.before_proxy:       # the memory triggers read headers case-insensitively
            await hook(svc, route.method, path, httpx.Headers(headers))
        kw: dict[str, Any] = {"params": query, "headers": headers}
        if route.body == "multipart":
            kw["data"] = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in body.items()}
            kw["files"] = files or None
        elif route.body == "json" or body or whole is not None:
            kw["json"] = whole if route.body_key else ({route.wrap: body} if route.wrap else body)
        svc.in_flight += 1
        try:
            r = await self.client.request(route.method, svc.url + path, **kw)
        finally:
            svc.in_flight -= 1
            svc.last_request_ts = time.time()
        if r.status_code >= 400:
            raise mod_error(svc, r)
        ctype = r.headers.get("content-type", "")
        if "json" in ctype or not r.content:
            data = r.json() if r.content else None
            if tool.job:
                jid = _job_id(data)
                if jid is None:
                    c.result = data
                    c.outputs = await results.outputs_for(self.hub, results.candidates(self.hub, svc.id, data))
                    return
                await self._follow(c, svc, jid, data)
                return
            c.result = data
            c.outputs = await results.outputs_for(self.hub, results.candidates(self.hub, svc.id, data))
            return
        rel = results.saved_path(r.headers)
        rels = results.candidates(self.hub, svc.id, [rel]) if rel else []
        if not rels:
            meta = {k: v for k, v in c.arguments.items() if isinstance(v, (str, int, float, bool))}
            rels = [await asyncio.to_thread(results.save_bytes, self.hub, svc.id, r.content, ctype, tool.tool, meta)]
        c.outputs = await results.outputs_for(self.hub, rels)
        c.result = {"content_type": ctype.split(";")[0], "bytes": len(r.content),
                    "saved": [o["title"] for o in c.outputs]}

    async def _follow(self, c: Call, svc: Any, jid: str, first: Any = None) -> None:
        assert c.tool.job
        c.job_id = jid
        await self.hub.db.execute("UPDATE tool_calls SET job = ? WHERE id = ?", (json.dumps({"id": jid}), c.id))
        self._publish(c)
        method, op = c.tool.job["status"].split(" ", 1)
        path, _, q = op.partition("?")
        path = PLACEHOLDER.sub(quote(jid, safe=""), path, count=1)
        long_poll = "wait=" in q
        deadline = time.time() + FOLLOW_MAX_S
        body = first
        last_progress: float | None = None
        while True:
            st = _state_of(body) if body is not None and body is not first else None
            if st in DONE | FAILED | CANCELLED:
                break
            if time.time() > deadline:
                raise ToolError("job_timeout", f"job {jid} is still running after {FOLLOW_MAX_S // 3600} h",
                                "check it with the mod's page")
            if body is not None and not long_poll:
                await asyncio.sleep(POLL_S)
            r = await self.client.request(method, svc.url + path + (f"?{q}" if q else ""), timeout=httpx.Timeout(120, connect=10))
            if r.status_code >= 400:
                raise mod_error(svc, r)
            body = r.json()
            p = _progress(body)
            if p != last_progress:
                c.progress, last_progress = p, p
                self._publish(c)
        if st in FAILED:
            err = body.get("error") if isinstance(body, dict) else None
            raise ToolError("job_failed", f"the job failed: {err or st}"[:600], "read the error; change the inputs or try again")
        if st in CANCELLED:
            raise asyncio.CancelledError
        c.result = _job_summary(body)
        c.outputs = await results.outputs_for(self.hub, results.candidates(self.hub, svc.id, body))

    async def _cancel_job(self, c: Call) -> None:
        if not c.job_id or not c.tool.job or not c.tool.job.get("cancel"):
            return
        try:
            svc = self.hub.services.get(c.tool.mod or "")
            method, op = c.tool.job["cancel"].split(" ", 1)
            path = PLACEHOLDER.sub(quote(c.job_id, safe=""), op.partition("?")[0], count=1)
            await self.client.request(method, svc.url + path, timeout=15)
        except Exception as e:  # noqa: BLE001
            log.warning("cancelling job %s of %s: %s", c.job_id, c.tool.name, e)


def _job_summary(body: Any) -> Any:
    """A finished job, without the bulky parts (stage timings, inputs echoed back)."""
    if not isinstance(body, dict):
        return body
    keep = ("id", "state", "status", "title", "label", "workflow", "error", "outputs", "files", "dir", "seconds", "peak_gb")
    return {k: body[k] for k in keep if k in body}
