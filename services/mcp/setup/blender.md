<!-- gaifa-setup
id = "mcp-blender"
title = "Blender for the mcp mod (MCP for Blender)"
models = []
scan = []
summary = "Blender in your chats: the MCP for Blender server and its add-on, with a Blender without a window when yours isn't open"
gpu = false
disk_gb = 0.1
after = ["mcp"]
needs = ["uv", "blender"]
check = "curl -sf \"${GAIFA_URL:-http://127.0.0.1:7000}/api/s/mcp/v1/servers/blender\" >/dev/null"

[[steps]]
run = "ls ~/.config/blender/*/scripts/addons/blender_mcp.py >/dev/null 2>&1 || uvx --from mcp-for-blender==2.2.0 mcp-for-blender install-addon"
what = "installs the MCP for Blender add-on (1.8) into Blender's add-ons in ~/.config/blender, unless it's there"
ask = "MCP for Blender (github.com/ahujasid/mcp-for-blender, MIT) lets a chat run Python inside Blender; every code step asks you first (in Auto, the judge decides). Install its add-on into Blender?"

[[steps]]
run = "curl -sf -X POST \"${GAIFA_URL:-http://127.0.0.1:7000}/api/s/mcp/v1/presets/blender\" >/dev/null || curl -sf \"${GAIFA_URL:-http://127.0.0.1:7000}/api/s/mcp/v1/servers/blender\" >/dev/null"
what = "adds the Blender server to the mcp mod (its tools then wait for your approval on the MCP servers page)"
-->

# Blender for the mcp mod: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs). The mod's own setup is [mcp.md](mcp.md).

## What it is

[MCP for Blender](https://github.com/ahujasid/mcp-for-blender) (MIT; formerly `blender-mcp`): an add-on inside Blender that listens on `localhost:9876` and runs what it's sent on Blender's main thread, and a stdio MCP server (`mcp-for-blender`, run with `uvx`) that turns those commands into tools: the scene, Python in Blender (`execute_blender_code`), assets from Poly Haven and Sketchfab, 3D generation through Hyper3D, viewport pictures (`look`). GAIFA adds it as the `blender` preset of the `mcp` mod, with telemetry off (`DISABLE_TELEMETRY=true`; its consent question is an elicitation, which the mod declines).

When nothing listens on the add-on's port, the mod starts a Blender without a window (`scripts/blender_headless.py`: `blender -b --python … -- --port 9876`), which runs the add-on's queued commands in a loop, and stops it with the session; open Blender with the add-on's server on and that one is used instead. Without a window, Blender still draws the viewport offscreen for `look`, and renders to a file work.

Blender's own MCP server ([Blender Lab](https://www.blender.org/lab/mcp-server/), Blender 5.1 and newer) is another choice: add it on the MCP servers page as any stdio server.

## Tested with

Read from this machine on 2026-10-26: Blender 5.2.2 LTS (`~/.local/opt/blender-5.2.2-linux-x64`, linked from `~/.local/bin/blender`), the add-on 1.8 in `~/.config/blender/5.2/scripts/addons/blender_mcp.py`, `mcp-for-blender` 2.2.0 (with `mcp` 1.30.0) from uv's cache, uv 0.9.

## Prerequisites

- Blender 3.0 or newer on the PATH (or in `~/.local/bin`).
- `uv` ([host.md](../../../docs/setup/host.md)).
- The `mcp` mod ([mcp.md](mcp.md)).

## Install

```bash
gaifa setup mcp-blender
```

Or by hand: install the add-on (`uvx --from mcp-for-blender==2.2.0 mcp-for-blender install-addon`), then on the MCP servers page press Blender under presets.

## Choosing models

None: Blender runs no model. How well a chat drives Blender depends on the chat's model; the eval is `services/agent/evals/blender.py`.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `BLENDER_HOST`, `BLENDER_PORT` | the server's env (the preset: `localhost`, `9876`) | no | where the add-on listens |
| `DISABLE_TELEMETRY` | the server's env (the preset: `true`) | no | the server sends nothing to its author |
| risks and turned-off tools | the MCP servers page | no | the preset: `execute_blender_code` execute; `generate_3d`, `search_assets`, `import_asset` network; `record_trajectory_feedback` off |

## Check it works

On the MCP servers page, press Tools on Blender (a Blender without a window starts), look at the tools, and approve them. Then in a chat: "make a red cube in Blender and render it".

## What to look for

- **The server didn't start:** `data/logs/mcp-blender.log` (the server) and `data/logs/mcp-blender-companion.log` (the Blender without a window).
- **Port 9876 in use:** another Blender has the add-on's server on: that's the one used; close it to use the windowless one.
- **A blank render:** the camera doesn't look at the subject or there's no light; the Blender skill says how to aim it.
