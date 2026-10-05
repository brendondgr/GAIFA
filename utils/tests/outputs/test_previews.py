"""4.3: previews: cached JPEGs for big images, video posters, 3D preview files; failures never block."""

from __future__ import annotations

import io
import os
import time

from PIL import Image

from utils.outputs import media
from utils.tests.outputs.conftest import index, needs_ffmpeg
from utils.tests.services.conftest import until


def jpeg_size(b: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(b)) as im:
        assert im.format == "JPEG"
        return im.size


async def by_title(client) -> dict[str, dict]:
    return {o["title"]: o for o in (await client.get("/api/outputs")).json()["items"]}


async def test_image_previews(app, client, hub_tree):
    hub_tree.png("comfy/2026-10-04/small.png", 300, 200)
    big = hub_tree.png("comfy/2026-10-04/big.png", 2600, 1700)
    await index(app)
    o = await by_title(client)
    small = await client.get(o["small"]["preview"])
    assert small.status_code == 200 and small.headers["content-type"] == "image/png"  # the image itself
    assert o["big"]["preview"].startswith(f"/api/outputs/{o['big']['id']}/preview?v=")
    r = await client.get(o["big"]["preview"])
    assert r.status_code == 200 and jpeg_size(r.content) == (640, 418)
    assert r.headers["cache-control"] == "private, max-age=604800"  # versioned URL
    cached = hub_tree.dir / "comfy/2026-10-04/.big.png.preview.jpg"
    assert cached.exists()
    stamp = cached.stat().st_mtime_ns
    await client.get(o["big"]["preview"])
    assert cached.stat().st_mtime_ns == stamp  # reused
    # the image changes: a new version URL and a fresh preview
    Image.new("RGB", (1800, 2600), (0, 0, 255)).save(big, "PNG")
    os.utime(big, (time.time() + 5, time.time() + 5))
    await index(app)
    o2 = await by_title(client)
    assert o2["big"]["preview"] != o["big"]["preview"]
    assert jpeg_size((await client.get(o2["big"]["preview"])).content) == (443, 640)
    assert (await by_title(client))["big"]["dims"] == {"w": 1800, "h": 2600}


async def test_previews_are_made_ahead_of_time(app, hub_tree):
    hub_tree.png("comfy/2026-10-04/big.png", 2600, 1700)
    await app.state.hub.outputs.sync()
    cached = hub_tree.dir / "comfy/2026-10-04/.big.png.preview.jpg"
    await until(cached.exists, timeout=5)


async def test_3d_and_audio(app, client, hub_tree):
    hub_tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": 9}, title="fox")
    hub_tree.png("gen3d/2026-10-04/j1-fox/preview.png", 32, 32)
    hub_tree.folder("gen3d/2026-10-04/j2-crate", {"mesh.glb": 9, "renders/front.png": 3}, title="crate", preview="renders/front.png")
    hub_tree.wav("tts/2026-10-04/a.wav")
    await index(app)
    o = await by_title(client)
    r = await client.get(o["fox"]["preview"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert o["crate"]["preview"] and (await client.get(o["crate"]["preview"])).content == b"\0\0\0"
    assert o["a"]["preview"] is None
    r = await client.get(f"/api/outputs/{o['a']['id']}/preview")
    assert (r.status_code, r.json()["code"]) == (404, "output_not_found")


@needs_ffmpeg
async def test_video_poster(app, client, hub_tree):
    hub_tree.mp4("comfy/2026-10-04/clip.mp4", seconds=2.0, size="1280x720")
    hub_tree.mp4("comfy/2026-10-04/blip.mp4", seconds=0.5, size="320x240")  # shorter than 1 s: the first frame
    await index(app)
    o = await by_title(client)
    assert o["clip"]["dims"] == {"w": 1280, "h": 720}
    assert jpeg_size((await client.get(o["clip"]["preview"])).content) == (640, 360)
    assert jpeg_size((await client.get(o["blip"]["preview"])).content) == (320, 240)


@needs_ffmpeg
async def test_a_broken_video_still_indexes(app, client, hub_tree, caplog):
    hub_tree.put("comfy/2026-10-04/broken.mp4", b"not a video at all" * 100)
    await index(app)
    o = (await by_title(client))["broken"]
    assert o["kind"] == "video" and "dims" not in o and "duration_s" not in o
    r = await client.get(o["preview"])
    assert (r.status_code, r.json()["code"]) == (404, "output_not_found")
    assert not list(hub_tree.dir.glob("comfy/2026-10-04/.*"))  # no half-written preview left behind


async def test_without_ffmpeg_videos_have_no_preview(app, client, hub_tree, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    media.tool.cache_clear()
    hub_tree.put("comfy/2026-10-04/clip.mp4", b"\0" * 64)
    await index(app)
    o = (await by_title(client))["clip"]
    assert o["preview"] is None and "duration_s" not in o


async def test_a_broken_big_image_falls_back_to_the_original(app, client, hub_tree, monkeypatch):
    p = hub_tree.png("comfy/2026-10-04/odd.png", 2600, 1700)
    await index(app)
    o = (await by_title(client))["odd"]
    p.write_bytes(p.read_bytes()[:200])  # truncated after indexing
    os.utime(p, (time.time() + 5, time.time() + 5))
    r = await client.get(o["preview"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
