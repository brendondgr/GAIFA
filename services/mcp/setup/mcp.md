<!-- gaifa-setup
id = "mcp"
title = "MCP servers"
models = []
scan = []
summary = "Other MCP servers' tools (Blender, and any stdio or HTTP MCP server) in GAIFA's chats, after you approve them"
gpu = false
disk_gb = 0.2
needs = []
check = "gaifa check mcp --start"

[[steps]]
run = "gaifa install mcp"
what = "makes .venv/ in this folder: FastAPI and the MCP Python SDK (under 100 MB, a minute)"
-->

# MCP servers: setup

The mod itself is a small Python service. The MCP servers you add are separate programs it starts (stdio) or reaches (HTTP); each one's own setup is its own.

## What it is

A FastAPI service on `127.0.0.1:5108` that keeps the list of MCP servers in `data/state/mcp/servers.json`, starts them on first use, and offers their approved tools to the hub.

## Tested with

Python 3.14 (uv-managed), `mcp` 2.3.0, FastAPI and uvicorn as `requirements.txt` resolves them.

## Prerequisites

`uv` ([host.md](../../../docs/setup/host.md)). A stdio server needs its own launcher on the PATH GAIFA runs with: `uvx` (from uv) for Python servers, `npx` (Node) for JavaScript ones.

## Install

```bash
gaifa install mcp
```

## Choosing models

None: this mod runs no model.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `MCP_STATE` | `service.toml` `[run].env` | no | where `servers.json` is (default `data/state/mcp`) |
| a server's `${NAME}` | `services/mcp/.env` | when a server names it | a secret (a token, a key) the server's env or headers use |

## Check it works

```bash
gaifa start mcp && gaifa check mcp
```

Expect `all checks passed`. Then add a server on the MCP servers page, look at its tools and approve them.

## What to look for

- **A server didn't start:** its stderr is in `data/logs/mcp-<id>.log`; a launcher missing from GAIFA's PATH (`uvx`, `npx`) is the usual cause: give the full path as the command.
- **`409 changed`:** the server's tools changed since you approved them; look at the difference on the page and approve again.
- **`409 missing_secret`:** add the named variable to `services/mcp/.env`.
