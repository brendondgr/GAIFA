"""The JSON-lines protocol of the image-engine workers (the same as cube_worker.py's):

  stdin   {"cmd": "load", "models": [...]} | {"cmd": "run", "task": {...}} | {"cmd": "quit"}
  stdout  {"event": "ready"} once, then sub / progress / sub_done / loaded / result / error

`serve(load, run)` owns stdout (everything else printed goes to stderr, the server log) and the loop.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

_OUT = None


def _own_stdout() -> None:
    global _OUT
    if _OUT is None:
        _OUT = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())        # C-level prints too
        sys.stdout = sys.stderr


def emit(event: str, **data) -> None:
    _OUT.write(json.dumps({"event": event, **data}) + "\n")
    _OUT.flush()


def sync() -> None:
    import torch
    if torch.cuda.is_available():
        torch.cuda.synchronize()


class Subs:
    """Announces substages one after another: `next(name)` closes the open one (with its seconds)."""

    def __init__(self):
        self.name, self.t0 = None, 0.0

    def next(self, name: str | None, total: int | None = None) -> None:
        if self.name:
            sync()
            emit("sub_done", sub=self.name, seconds=round(time.time() - self.t0, 2))
        self.name, self.t0 = name, time.time()
        if name:
            emit("sub", sub=name, total=total)

    def done(self) -> None:
        self.next(None)


def reduce_mesh(mesh, target: int):
    """Quadric decimation to about `target` faces (fast-simplification; lab: 0.2–0.7 s, 50 k faces within
    0.01 % of the diagonal on Hunyuan3D meshes). Returns the mesh unchanged when it is already smaller."""
    import fast_simplification
    import numpy as np
    import trimesh
    if not target or len(mesh.faces) <= target:
        return mesh
    v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.int32),
                                        target_reduction=1 - target / len(mesh.faces))
    return trimesh.Trimesh(v, f, process=False)


def peak_gb() -> float | None:
    import torch
    return round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch.cuda.is_available() else None


def serve(load, run, info: dict | None = None) -> None:
    """load(models) -> loaded list; run(task) -> result dict. Errors become `error` events."""
    _own_stdout()
    import torch
    emit("ready", device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
         torch=torch.__version__, **(info or {}))
    loaded: list[str] = []
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        cmd = msg.get("cmd")
        if cmd == "quit":
            break
        try:
            if cmd == "load":
                loaded = load(msg.get("models") or [])
                emit("loaded", models=loaded)
            elif cmd == "run":
                torch.cuda.reset_peak_memory_stats() if torch.cuda.is_available() else None
                result, loaded = run(msg["task"])
                emit("result", result=result, loaded=loaded)
        except Exception as exc:                                  # the worker stays up for the next task
            emit("error", message=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(), loaded=loaded)
