"""Live progress for runs (plan 45.1): ComfyUI's preview frames and steps, as a run's `live` (plan 44.2).

ComfyUI started with `--preview-method auto` (or `taesd`) sends a picture of the latent while a sampler runs, as
binary websocket messages to the client that queued the prompt:

    event 1 (PREVIEW_IMAGE):               u32 type · u32 format (1 JPEG, 2 PNG) · the image
    event 4 (PREVIEW_IMAGE_WITH_METADATA): u32 type · u32 metadata length · JSON {prompt_id, node_id, image_type, …} · the image

Event 1 has no prompt id: it belongs to the prompt that is executing. The newest frame per run is kept in memory
with a `seq` (`GET /v1/runs/{id}/preview?after=<seq>`), and dropped a minute after the run ends. Prompts queued
from ComfyUI's own page aren't ours: ComfyUI sends their frames and steps only to that page, so they show as
queued or running without a preview.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from typing import Any

PREVIEW_IMAGE = 1
PREVIEW_WITH_METADATA = 4
KEEP_S = 60


def parse(raw: bytes) -> tuple[str | None, str, bytes] | None:
    """A binary message → (prompt id or None, mime type, image bytes); None when it isn't a preview."""
    if len(raw) < 8:
        return None
    kind = struct.unpack(">I", raw[:4])[0]
    if kind == PREVIEW_IMAGE:
        fmt = struct.unpack(">I", raw[4:8])[0]
        return None, "image/png" if fmt == 2 else "image/jpeg", bytes(raw[8:])
    if kind == PREVIEW_WITH_METADATA:
        n = struct.unpack(">I", raw[4:8])[0]
        try:
            meta = json.loads(raw[8:8 + n])
        except ValueError:
            return None
        mime = meta.get("image_type") if isinstance(meta.get("image_type"), str) else "image/jpeg"
        return meta.get("prompt_id"), mime, bytes(raw[8 + n:])
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG or JPEG, from its header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                hgt, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, hgt
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


class Previews:
    def __init__(self) -> None:
        self.frames: dict[str, dict[str, Any]] = {}     # run id → {data, mime, seq, w, h}
        self.track: dict[str, dict[str, Any]] = {}      # run id → {stage, step, steps, t0, rate}
        self.executing: str | None = None               # the run ComfyUI is executing (event 1 frames go to it)
        self.changed: dict[str, asyncio.Event] = {}

    def _bump(self, rid: str) -> None:
        ev = self.changed.pop(rid, None)
        if ev is not None:
            ev.set()

    def on_binary(self, raw: bytes, by_prompt: dict[str, str]) -> str | None:
        """Keep a preview frame; returns the run it belongs to (None when it isn't ours)."""
        p = parse(raw)
        if p is None:
            return None
        pid, mime, data = p
        rid = by_prompt.get(pid) if pid else self.executing
        if rid is None or not data:
            return None
        old = self.frames.get(rid)
        size = image_size(data) or ((old["w"], old["h"]) if old else (None, None))
        self.frames[rid] = {"data": data, "mime": mime, "seq": (old["seq"] + 1) if old else 1, "w": size[0], "h": size[1]}
        tr = self.track.setdefault(rid, {"stage": "sampling"})
        tr["stage"] = "sampling" if tr.get("stage") in (None, "loading", "queued") else tr["stage"]
        self._bump(rid)
        return rid

    def on_event(self, rid: str, t: str, d: dict[str, Any], now: float | None = None) -> None:
        """ComfyUI's JSON messages for one of our runs → its stage and steps."""
        now = time.monotonic() if now is None else now
        tr = self.track.setdefault(rid, {"stage": "loading"})
        if t == "execution_start":
            self.executing = rid
            tr.update(stage="loading", step=None, steps=None, t0=None, rate=None)
        elif t == "executing":
            self.executing = rid
            if tr.get("stage") == "sampling" and tr.get("steps") and (tr.get("step") or 0) >= tr["steps"]:
                tr["stage"] = "decoding"             # the sampler finished: the VAE decodes, then the result is saved
        elif t == "progress":
            value, mx = d.get("value"), d.get("max")
            if isinstance(value, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
                if tr.get("steps") != mx or (tr.get("step") or 0) > value:      # a new sampler (a second pass)
                    tr.update(t0=now, t_step=value)
                tr.update(stage="sampling", step=int(value), steps=int(mx))
                done = value - (tr.get("t_step") or 0)
                if done > 0 and tr.get("t0") is not None:
                    tr["rate"] = (now - tr["t0"]) / done          # seconds per step
        self._bump(rid)

    def end(self, rid: str) -> None:
        """The run finished: its frame stays a minute (a late reader still gets the last one)."""
        if self.executing == rid:
            self.executing = None
        self._bump(rid)
        asyncio.get_event_loop().call_later(KEEP_S, self.forget, rid)

    def forget(self, rid: str) -> None:
        self.frames.pop(rid, None)
        self.track.pop(rid, None)

    def live(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """A run's `live` (plan 44.2), with its preview's path on this mod."""
        rid, state = run.get("id"), run.get("state")
        if state == "queued":
            return {"stage": "queued"}
        if state != "running" or rid is None:
            return None
        tr, fr = self.track.get(rid) or {}, self.frames.get(rid)
        out: dict[str, Any] = {"stage": tr.get("stage") or "loading"}
        if tr.get("steps"):
            out.update(step=tr.get("step") or 0, steps=tr["steps"])
            if tr.get("rate"):
                out["eta_s"] = round(max(0.0, (tr["steps"] - (tr.get("step") or 0)) * tr["rate"]), 1)
        if fr:
            out["preview"] = {"url": f"/v1/runs/{rid}/preview", "seq": fr["seq"],
                              **({"w": fr["w"], "h": fr["h"]} if fr.get("w") else {})}
        return out

    async def wait(self, rid: str, after: int, timeout: float) -> dict[str, Any] | None:
        """The run's frame when its seq is past `after`, waiting up to `timeout` for one."""
        deadline = time.monotonic() + timeout
        while True:
            fr = self.frames.get(rid)
            if fr and fr["seq"] > after:
                return fr
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ev = self.changed.setdefault(rid, asyncio.Event())
            try:
                await asyncio.wait_for(ev.wait(), timeout=left)
            except asyncio.TimeoutError:
                return None
