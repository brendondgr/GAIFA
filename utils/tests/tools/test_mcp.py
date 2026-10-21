"""13.4: the MCP endpoint. Both eras (2026-07-28 per-request `_meta`; the 2025 `initialize` era),
tool annotations from risk, calls, approvals that can't be skipped (the explanation +
`aihub_wait_approval`, and the 2026-07-28 `input_required` form), Origin, JSON-RPC errors, and the
official `mcp` client against a real hub process."""

from __future__ import annotations

import json
from typing import Any

import pytest

MODERN = "2026-07-28"
_ids = iter(range(1, 10_000))


async def rpc(th, method: str, params: dict | None = None, *, version: str | None = None, caps: dict | None = None,
              headers: dict | None = None, notify: bool = False) -> tuple[int, Any]:
    """POST one message. `version=MODERN` sends the 2026-07-28 envelope and headers; else the legacy shape."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": dict(params or {})}
    if not notify:
        msg["id"] = next(_ids)
    h = {"Accept": "application/json, text/event-stream", **(headers or {})}
    if version == MODERN:
        msg["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": MODERN,
                                  "io.modelcontextprotocol/clientCapabilities": caps or {},
                                  "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"}}
        h.setdefault("MCP-Protocol-Version", MODERN)
        h.setdefault("Mcp-Method", method)
        if method == "tools/call":
            h.setdefault("Mcp-Name", msg["params"]["name"])
    elif version:
        h["MCP-Protocol-Version"] = version
    r = await th.client.post("/mcp", json=msg, headers=h)
    return r.status_code, (r.json() if r.content else None)


async def call(th, name: str, arguments: dict, **kw: Any) -> dict:
    status, body = await rpc(th, "tools/call", {"name": name, "arguments": arguments}, **kw)
    assert status == 200 and "result" in body, body
    return body["result"]


def text(res: dict) -> str:
    return "\n".join(c["text"] for c in res["content"] if c["type"] == "text")


async def test_legacy_initialize_negotiates_and_pings(th):
    for asked in ("2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"):
        status, body = await rpc(th, "initialize", {"protocolVersion": asked, "capabilities": {},
                                                    "clientInfo": {"name": "t", "version": "1"}})
        assert status == 200 and body["result"]["protocolVersion"] == asked
    res = body["result"]
    assert res["serverInfo"]["name"] == "aihub" and res["capabilities"] == {"tools": {"listChanged": False}}
    _, body = await rpc(th, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert body["result"]["protocolVersion"] == "2025-11-25"
    assert await rpc(th, "notifications/initialized", notify=True) == (202, None)
    assert (await rpc(th, "ping", version="2025-06-18"))[1]["result"] == {}


async def test_modern_discover_and_envelope_rules(th):
    status, body = await rpc(th, "server/discover", version=MODERN)
    res = body["result"]
    assert status == 200 and res["resultType"] == "complete" and MODERN in res["supportedVersions"]
    assert res["capabilities"] == {"tools": {}} and res["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "aihub"
    status, body = await rpc(th, "tools/list", version=MODERN, headers={"Mcp-Method": "tools/call"})
    assert status == 400 and body["error"]["code"] == -32020
    status, body = await rpc(th, "tools/call", {"name": "hub_list_services"}, version=MODERN, headers={"Mcp-Name": "x"})
    assert status == 400 and body["error"]["code"] == -32020
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
           "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2099-01-01",
                                "io.modelcontextprotocol/clientCapabilities": {}}}}
    r = await th.client.post("/mcp", json=msg, headers={"MCP-Protocol-Version": "2099-01-01", "Mcp-Method": "tools/list"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32022 and MODERN in r.json()["error"]["data"]["supported"]
    del msg["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    r = await th.client.post("/mcp", json=msg, headers={"MCP-Protocol-Version": "2099-01-01", "Mcp-Method": "tools/list"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32602
    status, body = await rpc(th, "ping", version=MODERN)   # removed in 2026-07-28
    assert status == 404 and body["error"]["code"] == -32601


async def test_tools_list_annotations_follow_risk(th):
    for version in ("2025-06-18", MODERN):
        _, body = await rpc(th, "tools/list", version=version)
        tools = {t["name"]: t for t in body["result"]["tools"]}
        get, wipe, make = tools["fake_tools_get_item"], tools["fake_tools_wipe"], tools["fake_tools_make_image"]
        assert get["annotations"]["readOnlyHint"] is True and get["annotations"]["destructiveHint"] is False
        assert wipe["annotations"]["readOnlyHint"] is False and wipe["annotations"]["destructiveHint"] is True
        assert make["annotations"]["readOnlyHint"] is False and make["_meta"]["aihub/ask"] == ["aspect", "steps"]
        assert make["title"] == "Fake Tools: make image" and make["inputSchema"]["properties"]["aspect"]["enum"]
        assert "Example arguments" in make["description"]
        assert tools["aihub_wait_approval"]["annotations"]["readOnlyHint"] is True and "hub_list_services" in tools
    assert body["result"]["resultType"] == "complete" and body["result"]["cacheScope"] == "private"
    _, body = await rpc(th, "tools/list", version="2025-03-26")
    assert "title" not in body["result"]["tools"][0] and "resultType" not in body["result"]


async def test_read_tool_runs_and_returns_json(th):
    res = await call(th, "fake_tools_get_item", {"item_id": "a"}, version="2025-06-18")
    assert res["isError"] is False and json.loads(text(res))["result"]["id"] == "a"
    assert res["structuredContent"]["result"]["id"] == "a" and res["structuredContent"]["call_id"].startswith("call_")
    res = await call(th, "fake_tools_get_item", {"item_id": 5})
    assert res["isError"] is True and "expected string" in text(res) and "Fix:" in text(res)
    res = await call(th, "fake_tools_nope", {})
    assert res["isError"] is True and "unknown_tool" in text(res)
    status, body = await rpc(th, "tools/call", {"arguments": {}})
    assert status == 200 and body["error"]["code"] == -32602


async def test_ask_tool_waits_for_the_user_then_wait_approval_returns_the_result(th):
    res = await call(th, "fake_tools_make_image", {"prompt": "x"}, version="2025-06-18",
                     headers={"User-Agent": "claude-code/9.9"})
    ap = res["_meta"]["aihub/approval"]
    assert res["isError"] is False and res["structuredContent"]["status"] == "needs_approval"
    assert ap["approval_id"].startswith("ap_") and ap["arguments"] == {"prompt": "x"} and ap["ask_fields"] == ["aspect", "steps"]
    assert "has not run" in text(res) and "aihub_wait_approval" in text(res)
    assert not list((th.root / "outputs").rglob("*.png"))   # nothing ran
    pending = (await th.client.get("/api/approvals")).json()
    assert [a["id"] for a in pending] == [ap["approval_id"]]
    assert pending[0]["origin"] == {"service": "mcp", "client": "claude-code/9.9"}
    # calling again doesn't skip it: another approval, still nothing run
    again = await call(th, "fake_tools_make_image", {"prompt": "x"})
    assert again["_meta"]["aihub/approval"]["approval_id"] != ap["approval_id"]
    assert len((await th.client.get("/api/approvals")).json()) == 2 and not list((th.root / "outputs").rglob("*.png"))
    # waiting doesn't approve
    res = await call(th, "aihub_wait_approval", {"approval_id": ap["approval_id"], "wait": 0.6})
    assert res["isError"] is False and "Still waiting" in text(res)
    assert (await th.client.get(f"/api/approvals/{ap['approval_id']}")).json()["state"] == "pending"
    # the user approves in AIHub (with an edit); the wait tool returns the call's result
    r = await th.client.post(f"/api/approvals/{ap['approval_id']}?wait=0", json={"approve": True, "arguments": {"prompt": "x", "aspect": "16:9"}})
    assert r.status_code == 200
    res = await call(th, "aihub_wait_approval", {"approval_id": ap["approval_id"], "wait": 20}, version="2025-06-18")
    assert res["isError"] is False, text(res)
    body = json.loads(text(res))
    assert body["result"]["aspect"] == "16:9" and body["outputs"][0]["kind"] == "image"
    assert [c for c in res["content"] if c["type"] == "resource_link"][0]["uri"].startswith("http://hub/api/outputs/")
    # a denied one
    other = again["_meta"]["aihub/approval"]["approval_id"]
    await th.client.post(f"/api/approvals/{other}", json={"approve": False, "reason": "not now"})
    res = await call(th, "aihub_wait_approval", {"approval_id": other, "wait": 5})
    assert res["isError"] is True and "not now" in text(res)
    res = await call(th, "aihub_wait_approval", {"approval_id": "ap_nope", "wait": 0})
    assert res["isError"] is True and "not_found" in text(res)


async def test_modern_input_required_form_is_the_parameter_card(th):
    caps = {"elicitation": {"form": {}}}
    args = {"prompt": "a fox", "aspect": "1:1"}
    res = await call(th, "fake_tools_make_image", args, version=MODERN, caps=caps)
    assert res["resultType"] == "input_required" and res["requestState"]
    el = res["inputRequests"]["approval"]
    assert el["method"] == "elicitation/create" and el["params"]["mode"] == "form"
    props = el["params"]["requestedSchema"]["properties"]
    assert set(props) == {"aspect", "steps"} and props["aspect"]["default"] == "1:1" and "16:9" in props["aspect"]["enum"]
    aid = res["_meta"]["aihub/approval"]["approval_id"]
    assert not list((th.root / "outputs").rglob("*.png"))
    # a retry without an answer asks again; a tampered or mismatched state is refused
    params = {"name": "fake_tools_make_image", "arguments": args, "requestState": res["requestState"]}
    status, body = await rpc(th, "tools/call", params, version=MODERN, caps=caps)
    assert body["result"]["resultType"] == "input_required" and len((await th.client.get("/api/approvals")).json()) == 1
    for bad in ({**params, "requestState": res["requestState"][:-2] + "xx"}, {**params, "arguments": {"prompt": "other"}}):
        status, body = await rpc(th, "tools/call", bad, version=MODERN, caps=caps)
        assert status == 400 and body["error"]["code"] == -32602
    # an invalid edit asks again with the problem; a good one runs the edit
    status, body = await rpc(th, "tools/call", {**params, "inputResponses": {"approval": {"action": "accept", "content": {"aspect": "4:5"}}}},
                             version=MODERN, caps=caps)
    assert body["result"]["resultType"] == "input_required" and "didn't work" in body["result"]["inputRequests"]["approval"]["params"]["message"]
    status, body = await rpc(th, "tools/call", {**params, "inputResponses": {"approval": {"action": "accept", "content": {"aspect": "16:9", "steps": 4}}}},
                             version=MODERN, caps=caps)
    res = body["result"]
    assert res["resultType"] == "complete" and res["isError"] is False, res
    assert res["structuredContent"]["result"]["aspect"] == "16:9" and res["structuredContent"]["result"]["steps"] == 4
    a = (await th.client.get(f"/api/approvals/{aid}")).json()
    assert a["state"] == "approved" and a["final"]["aspect"] == "16:9"
    # the same retry again: the approval is used, so it returns the same call's result
    status, body = await rpc(th, "tools/call", {**params, "inputResponses": {"approval": {"action": "accept", "content": {}}}},
                             version=MODERN, caps=caps)
    assert body["result"]["structuredContent"]["call_id"] == a["call_id"]
    # declining denies
    res = await call(th, "fake_tools_make_image", {"prompt": "b"}, version=MODERN, caps=caps)
    status, body = await rpc(th, "tools/call", {"name": "fake_tools_make_image", "arguments": {"prompt": "b"},
                                                "requestState": res["requestState"],
                                                "inputResponses": {"approval": {"action": "decline"}}}, version=MODERN, caps=caps)
    assert body["result"]["isError"] is True
    assert (await th.client.get(f"/api/approvals/{res['_meta']['aihub/approval']['approval_id']}")).json()["state"] == "denied"
    # a modern client without elicitation gets the explanation instead
    res = await call(th, "fake_tools_make_image", {"prompt": "c"}, version=MODERN)
    assert res["resultType"] == "complete" and res["structuredContent"]["status"] == "needs_approval"


async def test_origin_and_jsonrpc_errors(th):
    # only the hub's own page (any loopback name, the hub's port) or no Origin at all; JSON-RPC errors, not the envelope
    for bad in ("https://evil.example", "http://localhost:5173", "http://127.0.0.1:5070", "http://127.attacker.com:7000",
                "https://127.0.0.1:7000", "null"):
        status, body = await rpc(th, "tools/list", headers={"Origin": bad})
        assert status == 403 and "error" in body, bad
    status, body = await rpc(th, "tools/list", headers={"Origin": "http://127.0.0.1:7000", "Sec-Fetch-Site": "cross-site"})
    assert status == 403 and "error" in body
    for ok in ("http://localhost:7000", "http://127.0.0.1:7000", "http://[::1]:7000"):
        assert (await rpc(th, "tools/list", headers={"Origin": ok, "Sec-Fetch-Site": "same-origin"}))[0] == 200
    assert (await rpc(th, "tools/list"))[0] == 200
    r = await th.client.post("/mcp", content=b"{nope", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700
    r = await th.client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert r.status_code == 400 and r.json()["error"]["code"] == -32600
    status, body = await rpc(th, "nope/nothing")
    assert status == 200 and body["error"]["code"] == -32601
    assert (await th.client.get("/mcp")).status_code == 405


def test_the_mcp_client_lists_and_calls_hub_tools(hub_process):
    mcp = pytest.importorskip("mcp")
    import anyio
    import httpx
    from mcp import types

    asked: list[Any] = []

    async def decline(_ctx: Any, params: Any) -> Any:
        asked.append(params)
        return types.ElicitResult(action="decline")

    async def run(mode: str) -> dict[str, Any]:
        async with mcp.Client(hub_process.url + "/mcp", mode=mode) as c:
            out = {"version": c.session.protocol_version, "names": {t.name for t in (await c.list_tools()).tools},
                   "listed": await c.call_tool("hub_list_services", {}),
                   "ask": await c.call_tool("hub_stop_service", {"id": "nope"})}
        if mode == "auto":   # 2026-07-28 with a form-capable client: input_required → the client's form → declined
            async with mcp.Client(hub_process.url + "/mcp", elicitation_callback=decline) as c:
                out["declined"] = await c.call_tool("hub_stop_service", {"id": "nope"})
        return out

    runs = {mode: anyio.run(run, mode) for mode in ("auto", "legacy")}
    for mode, version in (("auto", "2026-07-28"), ("legacy", "2025-11-25")):
        out = runs[mode]
        assert out["version"] == version
        assert {"hub_list_services", "hub_job_status", "aihub_wait_approval"} <= out["names"], out["names"]
        assert out["listed"].is_error is False and "result" in json.loads(out["listed"].content[0].text)
        ask = out["ask"]   # no elicitation: the explanation; nothing ran
        assert ask.is_error is False and "has not run" in ask.content[0].text
    assert runs["auto"]["declined"].is_error is True and "hub_stop_service" in asked[0].message
    pending = httpx.get(hub_process.url + "/api/approvals?state=all", trust_env=False).json()
    assert sorted(a["state"] for a in pending) == ["denied", "pending", "pending"]
    assert all(a["origin"]["service"] == "mcp" for a in pending)
