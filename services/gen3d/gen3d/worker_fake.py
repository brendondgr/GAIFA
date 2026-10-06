"""A stand-in for the GPU worker: same interface and events, simulated timings, sample outputs.

GEN3D_FAKE_WORKER=1 selects it. Stages take their real duration divided by GEN3D_FAKE_SPEED (20).
Outputs are CubePart's own example (the jellyfish car: its mesh, parts and preview from CubeArt) when
they exist, so the UI shows real meshes and parts; otherwise coloured placeholder boxes
(GEN3D_FAKE_SAMPLES=0 forces boxes, as tests do). The fake rig has no joints.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import struct
import time
import zlib
from pathlib import Path

from .config import settings
from .eta import WORKER_START_S, substages
from .glb import boxes_glb
from .options import JobRequest

SPEED = float(os.environ.get("GEN3D_FAKE_SPEED", "20"))
PALETTE = [(242, 109, 109), (242, 208, 109), (175, 242, 109), (109, 242, 142), (109, 242, 242),
           (109, 142, 242), (175, 109, 242), (242, 109, 208)]


def _samples() -> dict[str, Path] | None:
    if os.environ.get("GEN3D_FAKE_SAMPLES", "1") == "0":
        return None
    o = settings.cubeart / "outputs"
    s = {"mesh": settings.cubeart / "cube/cubepart/examples/inputs/jellyfish_car.glb",
         "parts": o / "parts/example_jellyfish_car/s0", "preview": o / "renders/parts_example_jellyfish.png"}
    return s if all(p.exists() for p in s.values()) else None


class FakeWorker:
    def __init__(self) -> None:
        self.up = False
        self.state = "stopped"
        self.loaded: set[str] = set()
        self._cancel = False

    def status(self) -> dict:
        return {"state": self.state, "loaded": sorted(self.loaded), "fake": True, "pid": None}

    async def start(self) -> None:
        if not self.up:
            self.state = "starting"
            await asyncio.sleep(WORKER_START_S / SPEED)
            self.up, self.state = True, "ready"

    async def load(self, models: list[str]) -> None:
        await self.start()
        self.loaded |= set(models)

    async def stop(self, reason: str = "", graceful: bool = True) -> bool:
        was = self.up
        self.up, self.state, self.loaded = False, "stopped", set()
        return was

    async def cancel(self) -> None:
        self._cancel = True

    async def run(self, task: dict, on_event, cancel_check=lambda: False) -> dict:
        self._cancel = False
        if not self.up:
            on_event({"event": "sub", "sub": "worker.start"})
            await self.start()
        self.state = "busy"
        try:
            req = JobRequest.model_validate(task["request"])
            stage = task["stage"]
            for sub, _feat, default, total in substages(req, stage, self.loaded):
                t0 = time.time()
                on_event({"event": "sub", "sub": sub, "total": total})
                dur = default / SPEED
                if total:
                    chunks = 20
                    for i in range(1, chunks + 1):
                        await self._sleep(dur / chunks)
                        on_event({"event": "progress", "step": round(total * i / chunks), "total": total})
                else:
                    await self._sleep(dur)
                on_event({"event": "sub_done", "sub": sub, "seconds": time.time() - t0})
                if sub.startswith("load."):
                    self.loaded.add(sub.split(".", 1)[1])
            return self._outputs(stage, req, Path(task["job_dir"]), task["inputs"])
        finally:
            self.state = "ready" if self.up else "stopped"

    async def _sleep(self, s: float) -> None:
        end = time.monotonic() + s
        while time.monotonic() < end:
            if self._cancel:
                self._cancel = False
                await self.stop(reason="canceled")
                raise RuntimeError("canceled")
            await asyncio.sleep(min(0.05, end - time.monotonic()))

    def _outputs(self, stage: str, req: JobRequest, jdir: Path, inputs: dict) -> dict:
        sm = _samples()
        if stage == "shape":
            if sm:
                shutil.copy(sm["mesh"], jdir / "mesh.glb")
            else:
                (jdir / "mesh.glb").write_bytes(boxes_glb([{"name": "mesh", "center": (0, 0.9, 0),
                                                            "size": (1.2, 1.8, 0.6)}]))
            return {"mesh": "mesh.glb", "faces": 12, "fake": True}
        if stage == "parts":
            names = req.parts.parts
            pdir = jdir / "parts"
            pdir.mkdir(exist_ok=True)
            parts = []
            if sm:
                man = json.loads((sm["parts"] / "manifest.json").read_text())
                src = [p for p in man["parts"] if p.get("file")]
                for i, name in enumerate(names):
                    p = src[i % len(src)]
                    fn = f"part_{i:02d}_{name.replace(' ', '_')}.glb"
                    shutil.copy(sm["parts"] / p["file"], pdir / fn)
                    parts.append({"index": i, "name": name, "file": fn, "faces": p.get("faces"),
                                  "color": list(PALETTE[i % 8])})
                shutil.copy(sm["parts"] / "parts.glb", jdir / "parts.glb")
            else:
                boxes = []
                for i, name in enumerate(names):
                    b = {"name": name, "center": ((i % 4) * 0.6 - 0.9, 0.4 + (i // 4) * 0.8, 0),
                         "size": (0.5, 0.6, 0.4), "color": PALETTE[i % 8]}
                    fn = f"part_{i:02d}_{name.replace(' ', '_')}.glb"
                    (pdir / fn).write_bytes(boxes_glb([b]))
                    boxes.append(b)
                    parts.append({"index": i, "name": name, "file": fn, "faces": 12, "color": list(PALETTE[i % 8])})
                (jdir / "parts.glb").write_bytes(boxes_glb(boxes))
            (pdir / "manifest.json").write_text(json.dumps({"parts": parts, "center": [0, 0, 0], "scale": 1.0}))
            return {"dir": "parts", "scene": "parts.glb", "parts": parts, "fake": True}
        if stage == "rig":
            shutil.copy(Path(inputs["parts_dir"]).parent / "parts.glb", jdir / "rigged.glb")
            (jdir / "rig.json").write_text(json.dumps({"units": "m", "joints": {}}))
            return {"glb": "rigged.glb", "rig": "rig.json", "joints": list(json.loads((jdir / "rig.json").read_text())["joints"]),
                    "fake": True}
        raise ValueError(f"unknown stage {stage}")


def _png(w: int, h: int, rgb=(40, 44, 52)) -> bytes:
    raw = b"".join(b"\0" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


async def fake_preview(jdir: Path, glb: Path, png: Path) -> None:
    await asyncio.sleep(12 / SPEED)
    sm = _samples()
    if sm:
        shutil.copy(sm["preview"], png)
    else:
        png.write_bytes(_png(64, 64))
