"""Plan lan-access 1.5: what a device on the network may not do."""

from __future__ import annotations

from utils.lan.limits import needs_body, refused


def test_what_stays_on_this_machine():
    assert refused("POST", "/mcp") and refused("GET", "/mcp")
    for path in ("/api/lan/settings", "/api/lan/password", "/api/lan/sessions/all"):
        assert refused("PUT", path) and refused("DELETE", path), path
    assert refused("POST", "/api/lan/signin") is None and refused("POST", "/api/lan/signout") is None
    assert refused("PUT", "/api/settings", {"hub": {"port": 8000}}) and refused("PUT", "/api/settings", {"voice_mode": {"talk": "push"}}) is None
    assert refused("PATCH", "/api/s/agent/v1/threads/t_1", {"mode": "bypass"})
    assert refused("POST", "/api/s/agent/v1/projects", {"name": "x", "defaults": {"mode": "bypass"}})
    assert refused("PATCH", "/api/s/agent/v1/threads/t_1", {"mode": "auto"}) is None
    assert refused("PATCH", "/api/s/workspace/v1/folders/f1", {"level": "edit"})
    assert refused("PATCH", "/api/s/workspace/v1/environments/e1/folders/f1", {"bypass": True})
    assert refused("POST", "/api/s/workspace/v1/folders", {"path": "/x", "level": "run_net"})
    assert refused("PATCH", "/api/s/agent/v1/projects/p1/folders/f1", {"level": "run"})
    assert refused("POST", "/api/s/workspace/v1/folders", {"path": "/x", "level": "read"}) is None
    assert refused("PATCH", "/api/s/workspace/v1/folders/f1", {"name": "notes"}) is None
    assert refused("GET", "/api/s/workspace/v1/folders") is None and refused("GET", "/api/settings") is None
    assert needs_body("PATCH", "/api/s/agent/v1/threads/t_1") and needs_body("PUT", "/api/settings") and not needs_body("GET", "/api/settings")
    assert not needs_body("POST", "/api/s/comfy/v1/run")
