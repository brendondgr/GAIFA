"""mcp-client 1.1: servers saved, checked, changed and removed; secrets stay out of the API."""

from __future__ import annotations

from servers import expand


async def test_add_check_change_remove(c):
    r = await c.post("/v1/servers", json={"id": "blender", "command": "uvx", "args": ["blender-mcp"],
                                          "env": {"BLENDER_TOKEN": "${BLENDER_TOKEN}", "DISABLE_TELEMETRY": "true", "API_KEY": "abc123"}})
    assert r.status_code == 201
    s = r.json()
    assert s["approval"]["state"] == "needs_approval" and s["session"]["state"] == "stopped"
    assert s["env"] == {"BLENDER_TOKEN": "${BLENDER_TOKEN}", "DISABLE_TELEMETRY": "true", "API_KEY": "•••"}
    assert (await c.post("/v1/servers", json={"id": "blender", "command": "x"})).status_code == 409
    for bad in ({"id": "B", "command": "x"}, {"id": "x1"}, {"id": "web", "transport": "http", "url": "ftp://x"}):
        assert (await c.post("/v1/servers", json=bad)).status_code == 422, bad
    p = (await c.patch("/v1/servers/blender", json={"enabled": False, "risks": {"execute_blender_code": "execute"}})).json()
    assert p["enabled"] is False and p["risks"] == {"execute_blender_code": "execute"}
    assert [x["id"] for x in (await c.get("/v1/servers")).json()] == ["blender"]
    assert (await c.delete("/v1/servers/blender")).json() == {"deleted": "blender"}
    assert (await c.delete("/v1/servers/blender")).status_code == 404


def test_expand():
    out, missing = expand({"A": "${X}", "B": "${Y:-dflt}", "C": "plain ${Z}"}, {"X": "1"})
    assert out == {"A": "1", "B": "dflt", "C": "plain "} and missing == ["Z"]
