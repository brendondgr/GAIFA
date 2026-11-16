<!-- gaifa-setup
id = "mcp"
title = "MCP servers"
models = []
scan = []
summary = "Other MCP servers' tools (Blender, and any stdio or HTTP MCP server) in GAIFA's chats, after you approve them"
recommended = true   # offered first for chat (capability-enablement 1.4)
gpu = false
disk_gb = 0.2
needs = []
check = "gaifa check mcp --start"

[[steps]]
run = "gaifa install mcp"
what = "makes .venv/ in this folder: FastAPI and the MCP Python SDK (under 100 MB, a minute)"
-->

# MCP servers: setup

**The easy way:** paste the text of `gaifa setup --prompt mcp` into your coding agent (Claude Code, Codex): it reads this doc, runs the same commands and checks, and can fix what goes wrong. Or run `gaifa setup mcp` yourself.

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

## Check

```bash
gaifa check mcp --start
```

Expect `mcp: all checks passed`.

```bash
curl -s "$(gaifa url api/s/mcp/v1/servers)" | head -c 200
```

Expect a JSON list (`[]` before you add a server; each server with its `id`, `name`, `approval` and `session`). Then add a server on the MCP servers page, look at its tools and approve them: they reach chats as `mcp_<server>_<tool>`.

## When it fails

| What you see | What to check | The fix |
|---|---|---|
| a server's `session` is `failed` (with an `error`) | the MCP servers page (its error), `gaifa logs mcp` | fix its command or URL (a stdio server's program must be on `PATH`), then Start on its row |
| a server's tools don't reach a chat | its row: tools waiting for approval, or held because they changed | approve them; in the chat turn the server on (`@mcp:<server>` or the composer) |
| Import finds nothing | the paths Import reads (the MCP servers page lists them) | add the server by hand (its command or URL) |
| `gaifa status` shows mcp `not set up`; a chat says it isn't set up | `ls services/mcp/.venv` | `gaifa setup mcp` (or the Set up dialog: Settings → Services → Set up) |
| `gaifa status` shows mcp `failed` | `gaifa logs mcp` (the last lines say why) | fix what the log names, then `gaifa start mcp`; still failing: `gaifa setup --prompt mcp` for your coding agent |
| mcp is off (Settings → Services shows its switch off) | Settings → Services | turn its switch on, or ask GAIFA's agent to turn it on; `gaifa start mcp` starts it once |

## What to look for

- **A server didn't start:** its stderr is in `data/logs/mcp-<id>.log`; a launcher missing from GAIFA's PATH (`uvx`, `npx`) is the usual cause: give the full path as the command.
- **`409 changed`:** the server's tools changed since you approved them; look at the difference on the page and approve again.
- **`409 missing_secret`:** add the named variable to `services/mcp/.env`.
