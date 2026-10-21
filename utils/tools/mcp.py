"""MCP endpoint (plan 13.4): the agent's tool catalog over the Model Context Protocol at `POST /mcp`.

Streamable HTTP, stateless, single `application/json` responses (no SSE, no sessions, no batches);
`GET`/`DELETE /mcp` are 405. Both protocol eras are served on the one endpoint:

- **Modern (2026-07-28):** every request carries `_meta["io.modelcontextprotocol/protocolVersion"]`
  and `…/clientCapabilities`, mirrored in the `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name`
  headers (a mismatch is `-32020`). Methods: `server/discover`, `tools/list`, `tools/call`. Results
  carry `resultType` and `_meta["io.modelcontextprotocol/serverInfo"]`.
- **Legacy (2025-03-26, 2025-06-18, 2025-11-25):** `initialize` (the client's version is echoed when
  supported), `notifications/initialized` (202), `ping`, `tools/list`, `tools/call`.

**Tools** are the catalog's (annotations from `risk`) plus the MCP-only `aihub_wait_approval`. Every
call goes through `hub.calls.call(..., origin={"service": "mcp", "client": …}, mode="manual")`, so the
permissions and approvals apply exactly as for the chat. An `ask` call runs nothing until the user
decides (`mcp_approval.py`): a modern client that can show forms gets an `input_required` result
whose `elicitation/create` form is the parameter card; every other client gets a result explaining
that the approval waits in AIHub (header → Approvals), plus `_meta["aihub/approval"]`, and can wait
for the outcome with `aihub_wait_approval`.

**Security:** the hub listens on loopback only; a present `Origin` must be the hub's own
(`http://127.0.0.1`, `http://localhost` or `http://[::1]` with the hub's port) and
`Sec-Fetch-Site` mustn't be `cross-site`, else 403 (`utils/origin.py`).
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from utils import origin
from utils.tools import mcp_approval
from utils.tools.mcp_approval import Approver, ProtocolError

if TYPE_CHECKING:
    from utils.server import Hub

log = logging.getLogger("aihub.mcp")

MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED = MODERN + LEGACY
LEGACY_DEFAULT = "2025-03-26"   # a legacy request without the version header (spec: treat it as 2025-03-26)

PV_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_KEY = "io.modelcontextprotocol/serverInfo"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
HEADER_MISMATCH, UNSUPPORTED_VERSION = -32020, -32022
MODERN_STATUS = {PARSE_ERROR: 400, INVALID_REQUEST: 400, INVALID_PARAMS: 400, HEADER_MISMATCH: 400,
                 UNSUPPORTED_VERSION: 400, METHOD_NOT_FOUND: 404}
LIST_TTL_MS = 30_000
INSTRUCTIONS = (
    "AIHub runs this machine's local AI services (speech, images & video, 3D, LLMs). Its tools make files "
    "(returned as outputs with a ref like output:<id> that other tools take as {\"$file\": \"output:<id>\"}). "
    "Tools that generate or change things ask the user first: the call answers with an approval that the user "
    "decides in AIHub (or in your client's form); wait for it with aihub_wait_approval. Long jobs answer "
    "status 'running' with a call_id: get the result with hub_job_status.")


class Request:
    """One JSON-RPC message, with what the era rules found in it."""

    def __init__(self, msg: dict[str, Any], headers: Mapping[str, str], base: str) -> None:
        self.msg, self.headers, self.base = msg, headers, base
        self.id = msg.get("id")
        self.method: str = msg["method"]
        self.params: dict[str, Any] = msg.get("params") or {}
        meta = self.params.get("_meta")
        self.meta: dict[str, Any] = meta if isinstance(meta, dict) else {}
        self.modern = PV_KEY in self.meta
        if self.modern:
            self.version = self.meta.get(PV_KEY)
        else:
            hv = headers.get("mcp-protocol-version")
            self.version = hv if hv in SUPPORTED else LEGACY_DEFAULT
        caps = self.meta.get(CAPS_KEY)
        self.caps: dict[str, Any] = caps if isinstance(caps, dict) else {}

    @property
    def client(self) -> str | None:
        info = self.meta.get(CLIENT_KEY)
        if isinstance(info, dict) and isinstance(info.get("name"), str):
            return info["name"][:80]
        ua = self.headers.get("user-agent", "").split(" ")[0]
        return ua[:80] or None

    def at_least(self, version: str) -> bool:
        return str(self.version) >= version


def _decode_header(v: str | None) -> str | None:
    if v and v.startswith("=?base64?") and v.endswith("?="):
        try:
            return base64.b64decode(v[9:-2]).decode()
        except ValueError:
            return None
    return v


def error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    out: dict[str, Any] = {"jsonrpc": "2.0", "error": err}
    if id_ is not None:
        out["id"] = id_
    return out


class McpServer:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.approver = Approver(hub)

    @property
    def server_info(self) -> dict[str, str]:
        return {"name": "aihub", "title": "AIHub", "version": self.hub.version}

    # ---- transport ---------------------------------------------------------------------------

    async def handle(self, raw: bytes, headers: Mapping[str, str], base: str) -> tuple[int, dict[str, Any] | None]:
        """One POST body → (HTTP status, JSON body or None for 202). `headers` keys are lowercase."""
        if origin.refusal(headers, self.hub.allowed_hosts, self.hub.port):
            return 403, error(None, INVALID_REQUEST, f"Forbidden origin {headers.get('origin')!r}: AIHub's MCP endpoint "
                                                     "only answers AIHub's own page and local clients")
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as e:
            return 400, error(None, PARSE_ERROR, f"Parse error: {e}")
        if isinstance(msg, list):
            return 400, error(None, INVALID_REQUEST, "JSON-RPC batches are not supported; send one message per POST")
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return 400, error(None, INVALID_REQUEST, "Invalid request: expected a JSON-RPC 2.0 object")
        if "method" not in msg:
            if "result" in msg or "error" in msg:
                return 202, None   # a response from a legacy client; nothing is waiting for it
            return 400, error(msg.get("id"), INVALID_REQUEST, "Invalid request: no method")
        if not isinstance(msg["method"], str) or ("params" in msg and not isinstance(msg["params"], (dict, type(None)))):
            return 400, error(msg.get("id"), INVALID_REQUEST, "Invalid request: method must be a string and params an object")
        if "id" not in msg:
            return 202, None       # a notification (notifications/initialized, cancelled…): accepted, nothing to do
        if msg["id"] is None or isinstance(msg["id"], (bool, float, dict, list)):
            return 400, error(None, INVALID_REQUEST, "Invalid request: id must be a string or an integer")
        req = Request(msg, headers, base)
        try:
            if req.modern:
                self._check_modern(req)
            result = await self._dispatch(req)
        except ProtocolError as e:
            status = MODERN_STATUS.get(e.code, 200) if req.modern else (400 if e.code in (PARSE_ERROR, INVALID_REQUEST) else 200)
            return status, error(req.id, e.code, e.message, e.data)
        except Exception as e:  # noqa: BLE001
            log.exception("MCP %s failed", req.method)
            return 200, error(req.id, INTERNAL_ERROR, f"Internal error: {type(e).__name__}: {e}"[:400])
        if req.modern:
            meta = result.setdefault("_meta", {})
            meta[SERVER_KEY] = self.server_info
            result = {"resultType": "complete", **result}
        return 200, {"jsonrpc": "2.0", "id": req.id, "result": result}

    def _check_modern(self, req: Request) -> None:
        """The 2026-07-28 request ladder: envelope, headers, then the version."""
        missing = [k for k in (PV_KEY, CAPS_KEY) if k not in req.meta]
        if missing:
            raise ProtocolError(INVALID_PARAMS, f"params._meta is missing the required key(s): {', '.join(missing)}")
        h = req.headers
        if h.get("mcp-protocol-version") != req.version:
            raise ProtocolError(HEADER_MISMATCH, "MCP-Protocol-Version header does not match params._meta's protocol version")
        if h.get("mcp-method") != req.method:
            raise ProtocolError(HEADER_MISMATCH, "Mcp-Method header does not match the request's method")
        if req.method == "tools/call" and isinstance(req.params.get("name"), str) \
                and _decode_header(h.get("mcp-name")) != req.params["name"]:
            raise ProtocolError(HEADER_MISMATCH, "Mcp-Name header does not match params.name")
        if not isinstance(req.version, str):
            raise ProtocolError(INVALID_PARAMS, "the protocol version must be a string")
        if req.version not in MODERN:
            if req.version in LEGACY:   # a handshake-era version without the handshake: serve it the legacy way
                req.modern = False
                return
            raise ProtocolError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                                {"supported": list(SUPPORTED), "requested": req.version})

    # ---- methods -----------------------------------------------------------------------------

    async def _dispatch(self, req: Request) -> dict[str, Any]:
        m = req.method
        if m == "tools/list":
            return await self._tools_list(req)
        if m == "tools/call":
            return await self._tools_call(req)
        if req.modern:
            if m == "server/discover":
                return {"supportedVersions": list(SUPPORTED), "capabilities": {"tools": {}},
                        "instructions": INSTRUCTIONS, "ttlMs": 3_600_000, "cacheScope": "private"}
        elif m == "initialize":
            return self._initialize(req)
        elif m == "ping":
            return {}
        raise ProtocolError(METHOD_NOT_FOUND, f"Method not found: {m}")

    def _initialize(self, req: Request) -> dict[str, Any]:
        asked = req.params.get("protocolVersion")
        version = asked if asked in SUPPORTED else LEGACY[0]
        info = dict(self.server_info) if version >= "2025-06-18" else {"name": "aihub", "version": self.hub.version}
        return {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": info, "instructions": INSTRUCTIONS}

    async def _tools_list(self, req: Request) -> dict[str, Any]:
        catalog = await self._ready().tools.tools()
        tools = [self._tool(t, req) for t in catalog] + [self._tool_entry(req, *mcp_approval.WAIT_TOOL)]
        out: dict[str, Any] = {"tools": tools}
        if req.modern:
            out.update({"ttlMs": LIST_TTL_MS, "cacheScope": "private"})
        return out

    def _title(self, t: Any) -> str:
        if t.mod is None:
            owner = "AIHub"
        else:
            svc = self.hub.services.services.get(t.mod) if self.hub.services else None
            owner = svc.mod.name if svc else t.mod
        return f"{owner}: {t.tool.replace('_', ' ')}"

    def _tool(self, t: Any, req: Request) -> dict[str, Any]:
        entry = self._tool_entry(req, t.name, self._title(t), t.function()["function"]["description"], t.parameters,
                                 t.risk)
        entry["_meta"] = {"aihub/risk": t.risk, "aihub/mod": t.mod or "hub", "aihub/ask": t.ask,
                          "aihub/available": t.available}
        if not t.available and t.why:
            entry["description"] += f"\n(Not running now: {t.why}. Calling it starts it.)"
        return entry

    def _tool_entry(self, req: Request, name: str, title: str, description: str, schema: dict[str, Any],
                    risk: str) -> dict[str, Any]:
        schema = schema if schema.get("type") == "object" else {"type": "object", **schema}
        entry: dict[str, Any] = {"name": name, "description": description, "inputSchema": schema,
                                 "annotations": {"title": title, "readOnlyHint": risk == "read",
                                                 "destructiveHint": risk in ("destructive", "execute"),
                                                 "openWorldHint": risk == "network"}}
        if req.modern or req.at_least("2025-06-18"):
            entry["title"] = title
        return entry

    async def _tools_call(self, req: Request) -> dict[str, Any]:
        hub = self._ready()
        name, args = req.params.get("name"), req.params.get("arguments")
        if not isinstance(name, str) or not name:
            raise ProtocolError(INVALID_PARAMS, "params.name must be the tool's name")
        if args is not None and not isinstance(args, dict):
            raise ProtocolError(INVALID_PARAMS, "params.arguments must be an object")
        args = args or {}
        if name == mcp_approval.WAIT_TOOL[0]:
            return await self.approver.wait_tool(req, args)
        if req.modern and req.params.get("requestState") is not None:
            return await self.approver.resume(req, name, args)
        out = await hub.calls.call(name, args, origin={"service": "mcp", "client": req.client}, mode="manual",
                                   wait=mcp_approval.CALL_WAIT_S)
        if out.get("status") == "needs_approval":
            return await self.approver.needs(req, out, args)
        return self.approver.result(req, out)

    def _ready(self) -> Hub:
        if self.hub.calls is None or self.hub.tools is None:
            raise ProtocolError(INTERNAL_ERROR, "AIHub is still starting; try again in a moment")
        return self.hub
