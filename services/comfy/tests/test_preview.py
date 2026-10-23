"""45.1: preview frames from ComfyUI's websocket, a run's `live`, and GET /v1/runs/{id}/preview."""

import asyncio
import json
import struct
import time

import pytest

from comfy.previews import Previews, image_size, parse
from fakecomfy import PNG_1x1
from test_run import env  # noqa: F401 - the fixture


def test_parse_both_events_and_sizes():
    png = PNG_1x1(64, 48)
    assert parse(struct.pack(">II", 1, 2) + png) == (None, "image/png", png)
    assert parse(struct.pack(">II", 1, 1) + b"\xff\xd8x") == (None, "image/jpeg", b"\xff\xd8x")
    meta = json.dumps({"prompt_id": "p1", "image_type": "image/webp"}).encode()
    assert parse(struct.pack(">II", 4, len(meta)) + meta + b"IMG") == ("p1", "image/webp", b"IMG")
    assert parse(struct.pack(">II", 3, 0)) is None and parse(b"x") is None
    assert image_size(png) == (64, 48)
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"ab" + b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 360, 480) + b"\x00" * 6
    assert image_size(jpeg) == (480, 360)


def test_steps_stage_and_frames_make_live():
    asyncio.run(_steps())


async def _steps():
    p = Previews()
    p.on_event("r1", "execution_start", {}, now=0)
    assert p.live({"id": "r1", "state": "running"}) == {"stage": "loading"}
    p.on_event("r1", "progress", {"value": 1, "max": 8}, now=1)
    p.on_event("r1", "progress", {"value": 3, "max": 8}, now=2)
    assert p.on_binary(struct.pack(">II", 1, 2) + PNG_1x1(100, 50), {}) == "r1"      # event 1: the executing run
    assert p.on_binary(struct.pack(">II", 1, 2) + PNG_1x1(100, 50), {}) == "r1"
    lv = p.live({"id": "r1", "state": "running"})
    assert lv["stage"] == "sampling" and (lv["step"], lv["steps"]) == (3, 8) and lv["eta_s"] == 2.5
    assert lv["preview"] == {"url": "/v1/runs/r1/preview", "seq": 2, "w": 100, "h": 50}
    p.on_event("r1", "progress", {"value": 8, "max": 8}, now=4)
    p.on_event("r1", "executing", {"node": "9"}, now=5)
    assert p.live({"id": "r1", "state": "running"})["stage"] == "decoding"
    assert p.live({"id": "r1", "state": "queued"}) == {"stage": "queued"}
    assert p.live({"id": "r1", "state": "done"}) is None
    meta = json.dumps({"prompt_id": "theirs"}).encode()
    assert p.on_binary(struct.pack(">II", 4, len(meta)) + meta + b"x", {}) is None              # not ours
    assert (await p.wait("r1", 1, 0.1))["seq"] == 2
    assert await p.wait("r1", 2, 0.1) is None


def test_a_run_previews_through_the_route(env):  # noqa: F811
    c, fake, hub, s = env
    fake.previews, fake.step_s = True, 0.15
    rid = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "a red fox"}}).json()["id"]
    seen, t0 = None, time.monotonic()
    while time.monotonic() - t0 < 10:
        job = c.get(f"/v1/jobs/{rid}").json()
        if job.get("live", {}).get("preview"):
            seen = job["live"]
            break
        time.sleep(0.05)
    assert seen and seen["preview"]["url"] == f"/v1/runs/{rid}/preview" and seen["stage"] in ("sampling", "decoding")
    r = c.get(f"/v1/runs/{rid}/preview", params={"after": 0})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and int(r.headers["x-seq"]) >= 1
    assert image_size(r.content)[0] % 8 == 0
    st = c.get("/v1/status").json()
    assert any(j.get("live") for j in st["jobs"] if j["state"] == "running") or st["jobs"][0]["state"] == "done"
    done = c.get(f"/v1/jobs/{rid}", params={"wait": 10}).json()
    assert done["state"] == "done" and "live" not in done
    assert c.get(f"/v1/runs/{rid}/preview", params={"after": 999, "wait": 0}).status_code == 204
