"""Preview renders: Blender (on the host) draws a 4-view contact sheet of a job's newest result."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from .config import ROOT, settings

log = logging.getLogger("gen3d.preview")
SCRIPT = ROOT / "scripts" / "render_blender.py"
TIMEOUT_S = 180


def blender() -> str | None:
    return shutil.which(settings.blender) if settings.blender else None


async def render_preview(jdir: Path, glb: Path, png: Path, size: int = 384) -> None:
    """Render `glb` to `png`. Missing Blender is not an error: the preview is just skipped."""
    exe = blender()
    if not exe:
        log.info("no Blender (%r): preview skipped", settings.blender)
        return
    proc = await asyncio.create_subprocess_exec(
        exe, "-b", "--factory-startup", "-P", str(SCRIPT), "--", str(png), str(glb), "--size", str(size),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(jdir))
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Blender took longer than {TIMEOUT_S}s")
    if proc.returncode != 0 or not png.exists():
        tail = out.decode(errors="replace").strip().splitlines()[-5:]
        raise RuntimeError("Blender render failed: " + " | ".join(tail))
