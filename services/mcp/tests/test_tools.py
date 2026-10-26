"""mcp-client 1.2–2.1: a real stdio server: approval, the hub's rows, calls (text, a picture, an error, a crash),
risks, and a server whose tools change being held until approved again."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import FAKE, approved


async def test_nothing_is_offered_before_approval(c):
    assert (await c.post("/v1/servers", json=FAKE)).status_code == 201
    assert (await c.get("/v1/tools")).json() == {"tools": []}
    r = await c.post("/v1/call/fake/echo", json={"arguments": {"text": "hi"}})
    assert r.status_code == 409 and r.json()["code"] == "not_approved"
    s = (await c.get("/v1/servers/fake?tools=true")).json()
    assert {t["name"] for t in s["tools"]} == {"echo", "picture", "fail", "slow", "execute_code", "die", "ask"} and s["session"]["state"] == "running"
    assert (await c.post("/v1/servers/fake/approve", json={"hash": "stale"})).json()["code"] == "changed"


async def test_rows_risks_and_calls(c, tmp_path):
    await approved(c)
    rows = {r["function"]["name"]: r for r in (await c.get("/v1/tools")).json()["tools"]}
    assert set(rows) == {"fake_echo", "fake_picture", "fake_fail", "fake_slow", "fake_execute_code", "fake_die", "fake_ask"}
    assert rows["fake_echo"]["risk"] == "read" and rows["fake_die"]["risk"] == "destructive" and rows["fake_execute_code"]["risk"] == "execute"
    assert rows["fake_picture"]["risk"] == "write" and all(r["mcp"] is False for r in rows.values())
    assert rows["fake_echo"]["op"] == "POST /v1/call/fake/echo" and rows["fake_echo"]["function"]["description"].startswith("Fake (MCP server): Say it back")
    r = (await c.post("/v1/call/fake/echo", json={"arguments": {"text": "hi"}})).json()
    assert r["text"] == '<untrusted source="mcp:fake/echo">\necho: hi (token=s3cret)\n</untrusted>'   # the secret came from .env
    pic = (await c.post("/v1/call/fake/picture", json={"arguments": {}})).json()
    p = Path(pic["outputs"][0])
    assert p.is_file() and p.suffix == ".png" and p.parent.parent == tmp_path / "outputs"
    assert json.loads(p.with_suffix(".json").read_text())["source"] == {"service": "mcp", "server": "fake", "tool": "picture"}
    err = await c.post("/v1/call/fake/fail", json={"arguments": {}})
    assert err.status_code == 422 and err.json()["code"] == "tool_error" and "fail" in err.json()["detail"]
    await c.post("/v1/call/fake/die", json={"arguments": {}})                    # the process ends …
    again = await c.post("/v1/call/fake/echo", json={"arguments": {"text": "back"}})
    assert again.status_code == 200 and "echo: back" in again.json()["text"]          # … and starts again
    assert "dying" in (tmp_path / "logs" / "mcp-fake.log").read_text()


async def test_a_denied_tool_and_a_users_risk(c):
    await approved(c)
    await c.patch("/v1/servers/fake", json={"deny": ["die"], "risks": {"picture": "generate"}})
    rows = {r["function"]["name"]: r for r in (await c.get("/v1/tools")).json()["tools"]}
    assert "fake_die" not in rows and rows["fake_picture"]["risk"] == "generate"
    assert (await c.post("/v1/call/fake/die", json={"arguments": {}})).json()["code"] == "denied"


async def test_a_server_whose_tools_change_is_held(c, app, tmp_path):
    flag = tmp_path / "variant"
    await approved(c, {**FAKE, "env": {**FAKE["env"], "FAKE_MCP_VARIANT_FILE": str(flag)}})
    rev0 = (await c.get("/v1/status")).json()["tools_rev"]
    await c.post("/v1/servers/fake/stop")
    flag.write_text("changed")                                                  # the program changes under us
    r = await c.post("/v1/call/fake/echo", json={"arguments": {"text": "hi"}})
    assert r.status_code == 409 and r.json()["code"] == "changed"
    assert (await c.get("/v1/tools")).json() == {"tools": []}
    assert (await c.get("/v1/status")).json()["tools_rev"] != rev0
    s = (await c.get("/v1/servers/fake?tools=true")).json()
    assert s["approval"]["state"] == "changed" and s["approval"]["diff"] == {"added": [], "removed": [], "changed": ["echo"]}
    ok = (await c.post("/v1/servers/fake/approve", json={"hash": s["hash"]})).json()
    assert ok["approval"]["state"] == "approved"
    assert (await c.post("/v1/call/fake/echo", json={"arguments": {"text": "hi"}})).status_code == 200


async def test_a_call_that_takes_too_long(app):
    from client import ServerError
    pool = app.state.pool
    app.state.servers.add(__import__("servers").ServerIn(**FAKE))
    try:
        await pool.call("fake", "slow", {"seconds": 5}, timeout=0.5)
        raise AssertionError("no timeout")
    except ServerError as e:
        assert e.code == "timeout"


async def test_a_missing_secret_and_idle_stop(c, app):
    await c.post("/v1/servers", json={**FAKE, "id": "nosecret", "env": {"T": "${NOT_SET_ANYWHERE}"}})
    r = await c.post("/v1/servers/nosecret/start")
    assert r.status_code == 409 and "NOT_SET_ANYWHERE" in r.json()["detail"]
    await c.post("/v1/servers", json=FAKE)
    await c.post("/v1/servers/fake/start")
    pool = app.state.pool
    pool.idle_s = 0
    import asyncio
    stop = asyncio.Event()
    t = asyncio.create_task(pool.reap(stop, every=0.05))
    await asyncio.sleep(0.3)
    stop.set()
    await t
    assert (await c.get("/v1/servers/fake")).json()["session"]["state"] == "stopped"


async def test_an_elicitation_is_declined_and_reported(c):
    """mcp-client 2.2: no form in a chat yet: declined, with what the server asked."""
    await approved(c)
    r = (await c.post("/v1/call/fake/ask", json={"arguments": {}})).json()
    assert "decline" in r["text"] and r["asked"] == "Which size should the box be?" and "ask the user" in r["note"]
