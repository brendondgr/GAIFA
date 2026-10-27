"""Servers GAIFA knows how to set up (plan mcp-client 5.1): one click on the page, then the user approves the tools.

**blender:** MCP for Blender (ahujasid/mcp-for-blender, MIT), version 2.2.0, whose add-on (1.8) goes in Blender's
add-ons (its setup doc: setup/blender.md). The server runs with `uvx`, telemetry off. If nothing answers on the add-on's
port, a Blender without a window starts (`scripts/blender_headless.py`) and stops with the session; your own Blender
with the add-on's server on is used as it is. Running Python in Blender is `execute`; tools that reach the internet
(Poly Haven, Sketchfab, Hyper3D) are `network`; the tool that sends feedback to the add-on's author is turned off.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BLENDER_PORT = 9876


def _which(name: str) -> str | None:
    return shutil.which(name) or next((str(p) for p in (Path.home() / ".local" / "bin" / name,) if p.exists()), None)


def presets(outputs: Path) -> dict[str, dict[str, Any]]:
    uvx, blender = _which("uvx"), _which("blender")
    day_note = ("Save files (renders, .blend files) as f\"" + str(outputs) + "/{time.strftime('%Y-%m-%d/%H%M%S')}-<what>.<ext>\" "
                "(today's folder, the time now), and print the path: they become outputs in GAIFA.")
    return {"blender": {
        "server": {"id": "blender", "name": "Blender",
                   "description": "MCP for Blender 2.2.0: the scene, objects, materials, Python in Blender, renders. "
                                  "A Blender without a window starts when needed, unless yours has the add-on's server on.",
                   "transport": "stdio", "command": uvx or "uvx", "args": ["--from", "mcp-for-blender==2.2.0", "mcp-for-blender"],
                   "env": {"DISABLE_TELEMETRY": "true", "BLENDER_HOST": "localhost", "BLENDER_PORT": str(BLENDER_PORT)},
                   "skill": "blender", "note": day_note,
                   **({"companion": {"command": blender, "args": ["-b", "--python", str(HERE / "scripts" / "blender_headless.py"),
                                                                  "--", "--port", str(BLENDER_PORT)], "port": BLENDER_PORT}}
                      if blender else {})},
        "risks": {"execute_blender_code": "execute", "generate_3d": "network", "search_assets": "network",
                  "import_asset": "network", "look": "read", "get_scene_info": "read", "get_addon_status": "read"},
        "deny": ["record_trajectory_feedback"],
        "available": bool(uvx and blender),
        "why": "" if uvx and blender else ("uv isn't installed" if not uvx else "Blender isn't on the PATH or in ~/.local/bin"),
    }}
