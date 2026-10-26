"""mcp-client 3.1: servers other apps configure, found by name and command, never by value."""

from __future__ import annotations

import json

import importers


def test_found_in_each_apps_file_and_a_project(tmp_path, monkeypatch):
    claude = tmp_path / ".claude.json"
    claude.write_text(json.dumps({"mcpServers": {"web": {"type": "http", "url": "https://x.example/mcp", "headers": {"Authorization": "Bearer abc"}}},
                                  "projects": {"/p/Blender": {"mcpServers": {"blender": {"command": "uvx", "args": ["blender-mcp"]}}}}}))
    codex = tmp_path / "config.toml"
    codex.write_text('[mcp_servers.blender]\ncommand = "uvx"\nargs = ["--from", "blender-mcp==2.0.0", "blender-mcp"]\n'
                     '[mcp_servers.blender.env]\nDISABLE_TELEMETRY = "true"\nBLENDER_PORT = "9876"\n'
                     '[mcp_servers.gh]\nurl = "https://api.example/mcp"\nbearer_token_env_var = "GH_TOKEN"\n')
    vscode = tmp_path / "mcp.json"
    vscode.write_text(json.dumps({"servers": {"fs": {"type": "stdio", "command": "npx", "args": ["-y", "fs-mcp"]}}}))
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"local": {"command": "python", "args": ["srv.py"], "env": {"API_KEY": "s3cret"}}}}))
    monkeypatch.setattr(importers, "APPS", [("Claude Code", claude, "claude_code"), ("Codex", codex, "codex"),
                                            ("VS Code", vscode, "servers"), ("Cursor", tmp_path / "missing.json", "mcpServers")])
    rows = importers.found([str(proj)])
    by = {(r["app"], r["name"]): r for r in rows}
    assert set(by) == {("Claude Code", "web"), ("Claude Code", "blender"), ("Codex", "blender"), ("Codex", "gh"), ("VS Code", "fs"),
                       ("project file in proj", "local")}
    assert by[("Claude Code", "blender")]["scope"] == "project /p/Blender"
    cb = by[("Codex", "blender")]
    assert cb["env_names"] == ["BLENDER_PORT", "DISABLE_TELEMETRY"] and "true" not in json.dumps(rows) and "s3cret" not in json.dumps(rows)
    assert "abc" not in json.dumps(rows)
    s = importers.as_server(cb)
    assert s == {"id": "blender", "name": "blender", "transport": "stdio", "command": "uvx", "args": ["--from", "blender-mcp==2.0.0", "blender-mcp"],
                 "env": {"BLENDER_PORT": "${BLENDER_PORT}", "DISABLE_TELEMETRY": "${DISABLE_TELEMETRY}"}, "description": s["description"]}
    g = importers.as_server(by[("Codex", "gh")])
    assert g["transport"] == "http" and g["headers"] == {"Authorization": "Bearer ${GH_TOKEN}"}


async def test_import_routes(c, monkeypatch, tmp_path):
    f = tmp_path / "cfg.json"
    f.write_text(json.dumps({"mcpServers": {"Fake One": {"command": "python", "args": ["x.py"]}}}))
    monkeypatch.setattr(importers, "APPS", [("Cursor", f, "mcpServers")])
    [e] = (await c.get("/v1/import")).json()["found"]
    assert e["added"] is False
    r = await c.post(f"/v1/import/{e['key']}")
    assert r.status_code == 201 and r.json()["id"] == "fake-one" and r.json()["approval"]["state"] == "needs_approval"
    assert (await c.get("/v1/import")).json()["found"][0]["added"] is True
    assert (await c.post(f"/v1/import/{e['key']}")).json()["code"] == "exists"
    assert (await c.post("/v1/import/nope")).status_code == 404
