"""The picture an image engine starts from (plan 17): fetched from AIHub's outputs or uploaded, then
written into the job folder as `input.png` (as given, at most MAX_SIDE) and `input_rgba.png` (the
cut-out every engine reads: alpha from the picture, else everything that isn't near-white)."""

from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageFilter

MAX_SIDE = 2048
MAX_BYTES = 64 * 1024 * 1024
WHITE_TOLERANCE = 12            # 0–255: how far from white still counts as background


class ImageError(ValueError):
    pass


async def fetch_output(ref: str, hub_url: str | None = None, timeout: float = 60) -> bytes:
    """`output:<id>` → the output's main file, from the hub (`GET /api/outputs/<id>/file`)."""
    hub = (hub_url or os.environ.get("AIHUB_URL") or "").rstrip("/")
    if not hub:
        raise ImageError("output:<id> images need AIHub (AIHUB_URL isn't set); upload the picture instead")
    oid = ref.split(":", 1)[1]
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(f"{hub}/api/outputs/{oid}/file")
    if r.status_code == 404:
        raise ImageError(f"no output {oid!r}")
    if r.status_code >= 400:
        raise ImageError(f"couldn't fetch output {oid!r} (HTTP {r.status_code})")
    if len(r.content) > MAX_BYTES:
        raise ImageError("the picture is larger than 64 MB")
    return r.content


def cutout(im: Image.Image) -> Image.Image:
    """RGBA with a meaningful alpha: the picture's own, or not-near-white pixels (a white backdrop)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        lo, hi = rgba.getchannel("A").getextrema()
        if lo < 250:                          # a real alpha channel, not an all-opaque one
            return rgba
    rgb = im.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).convert("L")
    mask = diff.point(lambda v: 255 if v > WHITE_TOLERANCE else 0).filter(ImageFilter.MedianFilter(3))
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out


def prepare(data: bytes, jdir: Path) -> dict:
    """Write input.png and input_rgba.png into the job folder; returns their names and the size."""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ImageError(f"not a picture this can read: {exc}") from exc
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    rgba = cutout(im)
    if rgba.getchannel("A").getextrema()[1] == 0:
        raise ImageError("the picture is empty (all background)")
    jdir.mkdir(parents=True, exist_ok=True)
    (im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")).save(jdir / "input.png")
    rgba.save(jdir / "input_rgba.png")
    return {"image": "input.png", "rgba": "input_rgba.png", "size": list(im.size)}
