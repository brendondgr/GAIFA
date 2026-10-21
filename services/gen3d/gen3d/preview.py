"""Preview renders: Blender (on the host) draws a 4-view contact sheet of a job's newest result.

Blender's Workbench draws through OpenGL, so `gpu` uses the GPU even in background mode. `cpu` (the default)
forces Mesa's software rasterizer (llvmpipe), and the script refuses to render if the context it gets is a
hardware one. The device is read for each render: the page's saved choice, else `GEN3D_PREVIEW_DEVICE`
(prefs.py). Meshes over `GEN3D_PREVIEW_MAX_FACES` are simplified for the picture only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import struct
from pathlib import Path

from . import prefs
from .config import ROOT, settings

log = logging.getLogger("gen3d.preview")
SCRIPT = ROOT / "scripts" / "render_blender.py"
PREVIEWABLE = (".glb", ".obj", ".ply")   # what the script imports; .gltf (external files), .stl, .off are not
MAX_GLB_JSON = 64 * 1024 * 1024
SOFTWARE_GL_ENV = {"LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe"}


def blender() -> str | None:
    return shutil.which(settings.blender) if settings.blender else None


def blender_command(exe: str, glb: Path, png: Path, size: int, device: str, max_faces: int) -> list[str]:
    """No user prefs or startup scripts (--factory-startup), no scripts embedded in the file (--disable-autoexec)."""
    cmd = [exe, "-b", "--factory-startup", "--disable-autoexec"]
    if device == "cpu":
        cmd += ["--gpu-backend", "opengl"]      # Mesa's llvmpipe is an OpenGL driver
    return cmd + ["-P", str(SCRIPT), "--", str(png), str(glb), "--size", str(size),
                  "--max-faces", str(max_faces), "--device", device]


def blender_env(device: str, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    if device == "cpu":
        env.update(SOFTWARE_GL_ENV)
    return env


def external_uris(path: Path) -> list[str]:
    """The buffer and image URIs in a GLB that point at files (anything but data: URIs). Blender's importer
    would read them, absolute paths and `..` included."""
    with path.open("rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ValueError("not a GLB file")
        clen, ctype = struct.unpack_from("<II", head, 12)
        if ctype != 0x4E4F534A or clen > MAX_GLB_JSON:     # "JSON"
            raise ValueError("GLB has no readable JSON chunk")
        doc = json.loads(f.read(clen))
    uris = [x.get("uri") for key in ("buffers", "images") for x in (doc.get(key) or []) if isinstance(x, dict)]
    return [u for u in uris if isinstance(u, str) and not u.startswith("data:")]


def check_previewable(path: Path) -> None:
    """Raise unless `path` is a mesh the preview may hand to Blender."""
    ext = path.suffix.lower()
    if ext not in PREVIEWABLE:
        raise RuntimeError(f"no preview for {ext or 'files without an extension'}: Blender previews {', '.join(PREVIEWABLE)}")
    if ext == ".glb":
        try:
            bad = external_uris(path)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"no preview: {exc}") from exc
        if bad:
            raise RuntimeError(f"no preview: the GLB points at outside files ({bad[0][:80]})")


async def render_preview(jdir: Path, glb: Path, png: Path, size: int = 384) -> None:
    """Render `glb` to `png`. Missing Blender is not an error: the preview is just skipped."""
    exe = blender()
    if not exe:
        log.info("no Blender (%r): preview skipped", settings.blender)
        return
    check_previewable(glb)
    device, timeout = prefs.preview_device(), settings.preview_timeout_s
    proc = await asyncio.create_subprocess_exec(
        *blender_command(exe, glb, png, size, device, settings.preview_max_faces), env=blender_env(device),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(jdir))
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Blender took longer than {timeout:g}s (GEN3D_PREVIEW_TIMEOUT_S)")
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        raise
    if proc.returncode != 0 or not png.exists():
        tail = out.decode(errors="replace").strip().splitlines()[-5:]
        raise RuntimeError("Blender render failed: " + " | ".join(tail))
