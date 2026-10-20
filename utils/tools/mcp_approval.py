"""MCP tool results and approvals (plan 13.4): how a `ToolCallResult` becomes an MCP `CallToolResult`,
and how an `ask` call waits for the user.

- **Results:** `done` → the JSON of `{result, outputs}` as text, `structuredContent` and a
  `resource_link` per output (2025-06-18+); `error`/`denied`/`cancelled` → `isError` with the detail
  and the fix; `running` → the `call_id` to follow with `hub_job_status`.
- **Approvals:** nothing runs until the user decides. A 2026-07-28 client that declared the
  `elicitation` capability gets an `input_required` result (multi round-trip requests): an
  `elicitation/create` **form** of the tool's `ask` fields (the parameter card; accepting it approves
  with the values shown, declining denies), or, for a client that only opens URLs, a **url**
  elicitation pointing at AIHub, where the user decides. The retry echoes `requestState`, an HMAC-signed
  `{approval, tool, arguments digest, mode, expiry}`. Every other client gets a result that explains the
  approval is waiting in AIHub, with `_meta["aihub/approval"]`; `aihub_wait_approval` waits for the
  user's decision and then for the call's result. It never approves anything itself.
- The approval also shows in AIHub's Approvals popover; whichever side decides first wins.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import mimetypes
import secrets
import time
from typing import TYPE_CHECKING, Any

from utils.tools import options

if TYPE_CHECKING:
    from utils.server import Hub
    from utils.tools.mcp import Request

INVALID_PARAMS = -32602
POLL_S = 0.5
URL_WAIT_S = 120.0
WAIT_MAX_S = 3600.0
CALL_WAIT_S = 600.0
INPUT_KEY = "approval"
FORMATS = {"email", "uri", "date", "date-time"}
PRIMITIVE = {"string", "number", "integer", "boolean"}

WAIT_TOOL = (
    "aihub_wait_approval", "AIHub: wait for an approval",
    "Wait until the user decides an approval in AIHub (the approval_id from a tool call that needed approval), "
    "then wait for that call's result and return it. It never approves anything: only the user does, in AIHub's "
    "Approvals popover. If the user denies, it says so; if the approval is still pending after `wait` seconds, "
    "call it again.",
    {"type": "object", "properties": {
        "approval_id": {"type": "string", "description": "The approval_id (ap_…) from the tool call"},
        "wait": {"type": "number", "minimum": 0, "maximum": WAIT_MAX_S, "default": 600,
                 "description": "Seconds to wait in all (for the decision, then for the result)"}},
     "required": ["approval_id"], "additionalProperties": False},
    "read",
)


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def _text(s: str) -> dict[str, str]:
    return {"type": "text", "text": s}


def _digest(args: Any) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:32]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def form_schema(schema: dict[str, Any], ask: list[str], args: dict[str, Any]) -> dict[str, Any]:
    """The `ask` fields as an elicitation form: flat primitives only, current values as defaults."""
    props_in = schema.get("properties") or {}
    props: dict[str, Any] = {}
    for k in ask:
        p = props_in.get(k)
        if not isinstance(p, dict) or p.get("x-kind"):
            continue
        typ = p.get("type")
        if isinstance(typ, list):
            typ = next((t for t in typ if t in PRIMITIVE), None)
        if typ not in PRIMITIVE:
            continue
        out: dict[str, Any] = {"type": typ}
        for key in ("title", "description", "minimum", "maximum", "minLength", "maxLength"):
            if key in p:
                out[key] = p[key]
        if p.get("format") in FORMATS:
            out["format"] = p["format"]
        if typ == "string" and isinstance(p.get("enum"), list) and all(isinstance(e, str) for e in p["enum"]):
            out["enum"] = options.choices(schema, k, args)       # only the choices that fit the inputs (plan 20.1)
            o = options.options(p)
            if o:
                out["enumNames"] = [str((o.get(v) or {}).get("label") or v) for v in out["enum"]]
        default = args.get(k, p.get("default"))
        if default is not None:
            out["default"] = default
        props[k] = out
    return {"type": "object", "properties": props}


class Approver:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.key = secrets.token_bytes(32)   # per process: a state from before a restart is refused

    # ---- results -----------------------------------------------------------------------------

    def result(self, req: Request, out: dict[str, Any]) -> dict[str, Any]:
        """A `ToolCallResult` (calls.py) → an MCP `CallToolResult`."""
        st, tool = out.get("status"), out.get("tool")
        rich = req.modern or req.at_least("2025-06-18")
        if st == "done":
            payload = {"result": out.get("result"), "outputs": out.get("outputs") or []}
            res: dict[str, Any] = {"content": [_text(json.dumps(payload, ensure_ascii=False, default=str))], "isError": False}
            if rich:
                res["structuredContent"] = {**payload, "call_id": out.get("call_id")}
                res["content"] += [self._link(req, o) for o in payload["outputs"]]
            return res
        if st == "running":
            cid = out.get("call_id")
            pct = f" ({round(out['progress'] * 100)}% done)" if isinstance(out.get("progress"), (int, float)) else ""
            res = {"content": [_text(f"{tool} is still running{pct}: call_id {cid}. Get its result with hub_job_status "
                                     f"{{\"call_id\": \"{cid}\", \"wait\": 600}}.")], "isError": False}
            if rich:
                res["structuredContent"] = {k: out.get(k) for k in ("status", "call_id", "progress", "job_id")}
            return res
        if st == "cancelled":
            return {"content": [_text(f"{tool}: the call was cancelled (call_id {out.get('call_id')}).")], "isError": True}
        err = out.get("error") or {}
        lead = "Not run" if st == "denied" else f"{tool} failed"
        text = f"{lead} ({err.get('code', st)}): {err.get('detail', 'unknown error')}"
        if err.get("fix"):
            text += f"\nFix: {err['fix']}"
        res = {"content": [_text(text)], "isError": True}
        if rich:
            res["structuredContent"] = {"status": st, "error": err}
        return res

    def _link(self, req: Request, o: dict[str, Any]) -> dict[str, Any]:
        url = o.get("url") or ""
        link = {"type": "resource_link", "uri": req.base + url if url.startswith("/") else url,
                "name": o.get("title") or o.get("output_id") or "output"}
        if o.get("summary"):
            link["description"] = o["summary"]
        mime = mimetypes.guess_type(o.get("title") or "")[0]
        if mime:
            link["mimeType"] = mime
        return link

    def _approval_meta(self, req: Request, a: dict[str, Any]) -> dict[str, Any]:
        return {"approval_id": a["approval_id"], "tool": a["tool"], "arguments": a["arguments"],
                "ask_fields": a.get("ask_fields") or [], "risk": a.get("risk"), "approve_in": req.base + "/",
                "wait_with": WAIT_TOOL[0]}

    def _waiting(self, req: Request, a: dict[str, Any], lead: str = "Approval needed") -> dict[str, Any]:
        meta = self._approval_meta(req, a)
        fields = ", ".join(meta["ask_fields"]) or "none"
        text = (f"{lead}: {a['tool']} ({a.get('risk')}) has not run. It is waiting for the user in AIHub "
                f"({meta['approve_in']}, header → Approvals) as approval {a['approval_id']}.\n"
                f"Arguments: {json.dumps(a['arguments'], ensure_ascii=False, default=str)}\n"
                f"The user can change: {fields}.\n"
                f"Calling the tool again makes another approval; it doesn't skip this one. To get the result once the "
                f"user decides, call {WAIT_TOOL[0]} {{\"approval_id\": \"{a['approval_id']}\"}}.")
        res: dict[str, Any] = {"content": [_text(text)], "isError": False, "_meta": {"aihub/approval": meta}}
        if req.modern or req.at_least("2025-06-18"):
            res["structuredContent"] = {"status": "needs_approval", **meta}
        return res

    # ---- the approval flow -------------------------------------------------------------------

    def _elicit_mode(self, req: Request) -> str | None:
        if not req.modern:
            return None
        el = req.caps.get("elicitation")
        if not isinstance(el, dict):
            return None
        if not el or "form" in el:
            return "form"
        return "url" if "url" in el else None

    def _state(self, aid: str, tool: str, args: dict[str, Any], mode: str) -> str:
        ttl = self.hub.config.agent.approval_ttl_h * 3600
        body = _b64(json.dumps({"a": aid, "t": tool, "d": _digest(args), "m": mode, "e": int(time.time() + ttl)},
                               separators=(",", ":")).encode())
        return body + "." + _b64(hmac.new(self.key, body.encode(), hashlib.sha256).digest())

    def _read_state(self, state: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        bad = ProtocolError(INVALID_PARAMS, "requestState is invalid, expired or from before AIHub restarted; "
                                            "call the tool again without it")
        if not isinstance(state, str) or "." not in state:
            raise bad
        body, _, sig = state.partition(".")
        try:
            ok = hmac.compare_digest(_unb64(sig), hmac.new(self.key, body.encode(), hashlib.sha256).digest())
            data = json.loads(_unb64(body)) if ok else None
        except ValueError:
            raise bad from None
        if not isinstance(data, dict) or data.get("e", 0) < time.time() or data.get("t") != tool \
                or data.get("d") != _digest(args):
            raise bad
        return data

    def _input_required(self, req: Request, a: dict[str, Any], args: dict[str, Any], mode: str,
                        note: str | None = None) -> dict[str, Any]:
        tool = a["tool"]
        msg = (f"AIHub wants to run {tool} ({a.get('risk')}) with "
               f"{json.dumps(a['arguments'], ensure_ascii=False, default=str)}.")
        if mode == "form":
            params: dict[str, Any] = {"mode": "form", "requestedSchema": form_schema(a.get("schema") or {},
                                                                                      a.get("ask_fields") or [],
                                                                                      a["arguments"])}
            msg += " Accept to run it (change the fields first if you like); decline to say no."
        else:
            params = {"mode": "url", "url": req.base + "/"}
            msg += f" Open AIHub and approve or deny it in the header's Approvals ({a['approval_id']})."
        params["message"] = (note + "\n" if note else "") + msg
        return {"resultType": "input_required",
                "inputRequests": {INPUT_KEY: {"method": "elicitation/create", "params": params}},
                "requestState": self._state(a["approval_id"], tool, args, mode),
                "_meta": {"aihub/approval": self._approval_meta(req, a)}}

    async def needs(self, req: Request, out: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        """A `needs_approval` answer: an elicitation for clients that can show one, else the explanation."""
        mode = self._elicit_mode(req)
        if mode is None:
            return self._waiting(req, out)
        return self._input_required(req, out, args, mode)

    async def resume(self, req: Request, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """The retry of an `input_required` call: apply the user's answer, or report the approval's state."""
        from utils.server import HubError

        st = self._read_state(req.params.get("requestState"), name, args)
        aid, mode = st["a"], st["m"]
        a = await self.hub.approvals.get(aid)
        if a is None:
            raise ProtocolError(INVALID_PARAMS, f"no approval {aid!r}; call the tool again")
        view = await self._view(a)
        answers = req.params.get("inputResponses")
        answer = answers.get(INPUT_KEY) if isinstance(answers, dict) else None
        action = answer.get("action") if isinstance(answer, dict) else None
        if a["state"] == "pending":
            if action is None:
                return self._input_required(req, view, args, mode)
            if action in ("decline", "cancel"):
                verb = "declined" if action == "decline" else "cancelled"
                out = await self.hub.calls.decide(aid, False, reason=f"{verb} in {req.client or 'the MCP client'}")
                return self.result(req, out)
            if mode == "form":
                content = answer.get("content") if isinstance(answer.get("content"), dict) else {}
                edited = {**a["arguments"], **{k: v for k, v in content.items() if k in (a["ask_fields"] or [])}}
                try:
                    return self.result(req, await self.hub.calls.decide(aid, True, edited, wait=CALL_WAIT_S))
                except HubError as e:
                    if e.code == "invalid_arguments":
                        return self._input_required(req, view, args, mode, note=f"That didn't work: {e.detail}")
                    if e.code != "already_decided":
                        raise ProtocolError(INVALID_PARAMS, e.detail) from None
                    a = await self.hub.approvals.get(aid) or a
            else:  # url: the user decides in AIHub; wait a while for it
                a = await self._await_decision(aid, URL_WAIT_S)
        return await self._decided(req, a, CALL_WAIT_S)

    async def _view(self, a: dict[str, Any]) -> dict[str, Any]:
        t = await self.hub.tools.get(a["tool"])
        return {"approval_id": a["id"], "tool": a["tool"], "arguments": a["arguments"], "ask_fields": a["ask_fields"],
                "risk": a["risk"], "schema": t.parameters if t else {}}

    async def _await_decision(self, aid: str, wait: float) -> dict[str, Any]:
        deadline = time.monotonic() + wait
        a = await self.hub.approvals.get(aid)
        while a is not None and a["state"] == "pending" and time.monotonic() < deadline:
            await asyncio.sleep(min(POLL_S, max(0.0, deadline - time.monotonic())))
            a = await self.hub.approvals.get(aid)
        return a  # type: ignore[return-value]

    async def _decided(self, req: Request, a: dict[str, Any], wait: float) -> dict[str, Any]:
        """The result for an approval as it stands: still waiting, denied, or its call's result."""
        if a["state"] == "pending":
            return self._waiting(req, await self._view(a), lead="Still waiting for the user")
        if a["state"] != "approved":
            why = a.get("reason") or ("not decided in time" if a["state"] == "expired" else "the user said no")
            return self.result(req, {"status": "denied", "tool": a["tool"], "error": {
                "code": "denied_by_user" if a["state"] == "denied" else "approval_expired", "detail": why,
                "fix": "don't run it again unless the user asks; ask what they'd like instead"}})
        if not a.get("call_id"):
            return self.result(req, {"status": "error", "tool": a["tool"], "error": {
                "code": "no_call", "detail": "the approval was approved but has no call"}})
        return self.result(req, await self.hub.calls.status(a["call_id"], wait))

    async def wait_tool(self, req: Request, args: dict[str, Any]) -> dict[str, Any]:
        """`aihub_wait_approval`: the user's decision, then the call's result. Never approves."""
        aid = args.get("approval_id")
        if not isinstance(aid, str) or not aid:
            return self.result(req, {"status": "error", "tool": WAIT_TOOL[0], "error": {
                "code": "invalid_arguments", "detail": "approval_id is required", "fix": "pass the approval_id (ap_…)"}})
        try:
            wait = min(max(float(args.get("wait", CALL_WAIT_S)), 0.0), WAIT_MAX_S)
        except (TypeError, ValueError):
            wait = CALL_WAIT_S
        deadline = time.monotonic() + wait
        a = await self._await_decision(aid, wait)
        if a is None:
            return self.result(req, {"status": "error", "tool": WAIT_TOOL[0], "error": {
                "code": "not_found", "detail": f"there is no approval {aid!r}",
                "fix": "use the approval_id from the tool call's answer"}})
        return await self._decided(req, a, max(0.0, deadline - time.monotonic()))
