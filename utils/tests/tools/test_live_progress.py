"""44.2: a job's live progress: through the hub's tool calls (`live` on the call, `changed` long polls) and on the
mods' status jobs (`Job.live` in /api/events/recent), with the mod's paths rewritten to the hub's proxy."""

from __future__ import annotations

import asyncio
import json
import time

from utils import live


def test_clean_keeps_known_fields_and_rewrites_paths():
    lv = live.clean({"stage": "sampling", "step": 3, "steps": 8, "eta_s": 6.54, "junk": 1, "lines": [2, 9],
                     "preview": {"url": "/v1/runs/r/preview", "seq": 3, "w": 10, "h": -1}, "audio": "/v1/a",
                     "stages": [{"id": "shape", "state": "running", "eta_s": 4}, {"id": "rig", "state": "bogus"}, "x"]}, "comfy")
    assert lv == {"stage": "sampling", "step": 3, "steps": 8, "eta_s": 6.5, "lines": [2, 9],
                  "preview": {"url": "/api/s/comfy/v1/runs/r/preview", "seq": 3, "w": 10}, "audio": "/api/s/comfy/v1/a",
                  "stages": [{"id": "shape", "label": "shape", "state": "running", "eta_s": 4.0}, {"id": "rig", "label": "rig", "state": "waiting"}]}
    assert live.clean({"preview": {"url": "https://evil/x"}, "audio": "//evil/a"}, "m") is None
    assert live.clean("nope", "m") is None and live.clean({}, "m") is None
    big = live.clean({"stages": [{"id": f"s{i}", "label": "x" * 60} for i in range(12)], "stage": "a"}, "m")
    assert len(json.dumps(big)) <= live.CAP_BYTES and big["stage"] == "a"
    assert live.key(lv) != live.key({**lv, "preview": {**lv["preview"], "seq": 4}})


async def test_a_jobs_live_reaches_the_call_and_changed_answers_at_the_next_step(th):
    r = await th.call("fake_tools_render", {"prompt": "slow", "seconds": 4}, mode="auto", wait=0.3)
    assert r["status"] == "running"
    cid = r["call_id"]
    await asyncio.sleep(2.2)                          # the hub polls the job every 2 s
    st = (await th.client.get(f"/api/tools/calls/{cid}")).json()
    lv = st["live"]
    assert lv["stage"] == "sampling" and lv["steps"] == 4 and "junk" not in lv
    assert lv["preview"]["url"].startswith("/api/s/fake-tools/v1/render/") and lv["preview"]["w"] == 64
    t0 = time.monotonic()
    nxt = (await th.client.get(f"/api/tools/calls/{cid}", params={"wait": 20, "changed": "true"})).json()
    assert time.monotonic() - t0 < 5 and nxt.get("live") != lv
    assert nxt["status"] == "running" or nxt["status"] == "done"
    done = (await th.client.get(f"/api/tools/calls/{cid}", params={"wait": 20})).json()
    assert done["status"] == "done" and "live" not in done
