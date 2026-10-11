"""How long will it take? A per-substage model of the pipeline.

Each stage is a list of substages. A substage's duration comes from, in order:
  1. live progress while it runs (elapsed / step * remaining steps),
  2. the median of the last finished runs with the same features (learned; stored in `timings`),
  3. defaults measured on this machine (Radeon 8060S, CubeArt benchmarks, 2026-09-30).

Model loads only count when the worker does not already have that model resident.
"""

from __future__ import annotations

import math
import statistics
import time

from .options import JobRequest

LOCAL = ("cube3d", "hunyuan21", "sam3d_objects")     # engines whose shape stage runs in gen3d's worker

# ---- defaults from the CubeArt benchmark suite ---------------------------------------------------

GPT_TOKENS = 1024          # Cube3D always emits 1024 shape tokens
GPT_S = 58.0               # ~18 tokens/s, independent of the prompt
GPT_FAST_S = 60.0          # EngineFast (graphs) is not faster on gfx1151
SHAPE_DECODE = {7.0: 3.4, 8.0: 24.5, 9.0: 200.0}     # seconds by resolution_base (CPU marching cubes)
SHAPE_POST = {7.0: 0.5, 8.0: 3.5, 9.0: 11.7}
PART_STEP_S = 2.45          # CubePart diffusion, per step, flat in #parts (always 8 slots)
PARTS_DECODE_8 = {8.0: 55.0, 8.5: 72.0, 9.0: 94.0}   # 8 parts; ~10 s + 7.75 s per part at 8.5
PARTS_ENCODE_S = 5.0        # surface sampling + VAE encode + text encode
LOAD_SHAPE_S = 12.0         # Cube3D GPT + tokenizer + CLIP
LOAD_PARTS_S = 45.0         # DiT + Qwen3-VL + VAE (~20 s) + first-call torch.compile (~25 s)
RIG_S = 15.0
PREVIEW_S = 12.0
WORKER_START_S = 6.0        # podman run + python imports


def _interp_log(table: dict[float, float], x: float) -> float:
    """Log-linear interpolation (decode cost grows ~8x per +1 resolution_base)."""
    ks = sorted(table)
    if x <= ks[0]:
        lo, hi = ks[0], ks[1]
    elif x >= ks[-1]:
        lo, hi = ks[-2], ks[-1]
    else:
        lo = max(k for k in ks if k <= x)
        hi = min(k for k in ks if k >= x)
        if lo == hi:
            return table[lo]
    a, b = math.log(table[lo]), math.log(table[hi])
    return math.exp(a + (b - a) * (x - lo) / (hi - lo))


# ---- image engines (plan 17.7; lab 2026-10-10/11, services/gen3d/runtime/lab/RESULTS.md) -----------
HY_LOAD_S, HY_COND_S, HY_STEP_S, HY_POST_S = 16.0, 0.4, 2.45, 3.0
HY_DECODE_S = {(True, 256): 6.0, (True, 384): 11.0, (True, 512): 20.0,       # FlashVDM
               (False, 256): 53.0, (False, 384): 191.0, (False, 512): 450.0}
S3O_LOAD_S, S3O_POINTMAP_S, S3O_DECODE_S, S3O_POST_S = 25.0, 3.0, 6.4, 2.0
S3O_STAGE_S = {(1, False): 1.3, (1, True): 0.8, (2, False): 1.4, (2, True): 0.9}   # per step: (stage, distilled)
# TRELLIS.2 runs in comfy: one substage with comfy's progress in percent. The refine stage costs ~5 s per
# step on a thin character and ~26 s on a round object (it follows the surface area, RESULTS.md §5);
# the seed is the character, learned times take over per settings.
TR_START_S, TR_STRUCT_S, TR_SHAPE_STEP_S, TR_DECODE_S, TR_LOWPOLY_S = 25.0, 20.0, 0.7, 10.0, 10.0
TR_REFINE_STEP_S = {1024: 5.2, 1536: 16.0}
BODY_S = 8.0


def image_substages(req: JobRequest, loaded: set[str]) -> list[tuple[str, dict, float, int | None]]:
    e = req.engine
    if e == "hunyuan21":
        o = req.hunyuan21
        out = [] if "hunyuan21" in loaded else [("load.hunyuan21", {}, HY_LOAD_S, None)]
        return out + [
            ("hunyuan.conditioning", {}, HY_COND_S, None),
            ("hunyuan.diffusion", {"steps": o.steps}, HY_STEP_S * o.steps, o.steps),
            ("hunyuan.decode", {"flashvdm": o.flashvdm, "octree": o.octree}, HY_DECODE_S[(o.flashvdm, o.octree)], None),
            ("hunyuan.post", {"target": bool(o.target_faces)}, HY_POST_S, None)]
    if e == "sam3d_objects":
        o = req.sam3d_objects
        out = [] if "sam3d_objects" in loaded else [("load.sam3d_objects", {}, S3O_LOAD_S, None)]
        return out + [
            ("sam3do.pointmap", {}, S3O_POINTMAP_S, None),
            ("sam3do.stage1", {"steps": o.ss_steps, "distill": o.distill}, S3O_STAGE_S[(1, o.distill)] * o.ss_steps, None),
            ("sam3do.stage2", {"steps": o.slat_steps, "distill": o.distill}, S3O_STAGE_S[(2, o.distill)] * o.slat_steps, None),
            ("sam3do.decode", {}, S3O_DECODE_S, None),
            ("sam3do.post", {"target": bool(o.target_faces)}, S3O_POST_S, None)]
    if e == "trellis2":
        o = req.trellis2
        secs = TR_START_S + TR_STRUCT_S + TR_SHAPE_STEP_S * o.shape_steps + TR_DECODE_S
        if o.resolution > 512:
            secs += TR_REFINE_STEP_S[o.resolution] * o.refine_steps
        if o.target_faces:
            secs += TR_LOWPOLY_S
        feats = {"res": o.resolution, "shape": o.shape_steps, "refine": o.refine_steps if o.resolution > 512 else 0,
                 "lowpoly": bool(o.target_faces)}
        return [("trellis2.comfy", feats, secs, 100)]
    if e == "sam3d_body":
        return [("sam3d_body.comfy", {"hands": req.sam3d_body.hand_refinement}, BODY_S, 100)]
    return []


def substages(req: JobRequest, stage: str, loaded: set[str]) -> list[tuple[str, dict, float, int | None]]:
    """[(substage, features, default_seconds, total_steps_or_None)] for one stage of a request."""
    s, p = req.shape, req.parts
    if stage == "shape" and req.engine != "cube3d":
        return image_substages(req, loaded)
    if stage == "shape":
        out = []
        if "shape" not in loaded:
            out.append(("load.shape", {}, LOAD_SHAPE_S, None))
        out += [
            ("shape.gpt", {"fast": s.fast_engine}, GPT_FAST_S if s.fast_engine else GPT_S, GPT_TOKENS),
            ("shape.decode", {"res": s.resolution_base}, _interp_log(SHAPE_DECODE, s.resolution_base), None),
            ("shape.post", {"res": s.resolution_base, "target": s.target_faces}, _interp_log(SHAPE_POST, s.resolution_base), None),
        ]
        return out
    if stage == "parts":
        n = max(1, len(p.parts))
        out = []
        if "parts" not in loaded:
            out.append(("load.parts", {}, LOAD_PARTS_S, None))
        decode8 = _interp_log(PARTS_DECODE_8, p.resolution_base)
        out += [
            ("parts.encode", {}, PARTS_ENCODE_S, None),
            ("parts.diffusion", {"steps": p.steps}, PART_STEP_S * p.steps, p.steps),
            ("parts.decode", {"res": p.resolution_base, "n": n, "target": p.target_faces},
             decode8 * (10 + 7.75 * n) / 72.0 + (6.0 if p.target_faces else 0.0), None),
        ]
        return out
    if stage == "rig":
        return [("rig", {}, RIG_S, None)]
    if stage == "preview":
        return [("preview", {}, PREVIEW_S, None)]
    return []


class Estimator:
    def __init__(self, store, scale: float = 1.0):
        self.store = store
        self.scale = scale  # < 1 for the fake worker, which runs faster than the real thing
        self._cache: dict[str, list[dict]] = {}

    # learned durations ------------------------------------------------------------------------
    def learned(self, sub: str, features: dict) -> float | None:
        if sub not in self._cache:
            self._cache[sub] = self.store.timings(sub, limit=100)
        same = [t["seconds"] for t in self._cache[sub] if t["features"] == features][:5]
        return statistics.median(same) if same else None

    def record(self, sub: str, features: dict, seconds: float) -> None:
        self.store.add_timing(sub, features, seconds)
        self._cache.pop(sub, None)

    def duration(self, sub: str, features: dict, default: float) -> float:
        got = self.learned(sub, features)
        return got if got is not None else default * self.scale

    # plans --------------------------------------------------------------------------------------
    def plan(self, req: JobRequest, stages: list[str], loaded: set[str], worker_up: bool) -> list[dict]:
        """Full breakdown for stages still to run, in order. Models loaded by an earlier stage of the
        same job count as loaded for later stages."""
        loaded = set(loaded)
        out = []
        local = [st for st in stages if st in ("parts", "rig") or (st == "shape" and req.engine in LOCAL)]
        if not worker_up and local:
            out.append({"stage": local[0], "sub": "worker.start", "seconds": WORKER_START_S * self.scale})
        for st in stages:
            for sub, feat, default, _ in substages(req, st, loaded):
                out.append({"stage": st, "sub": sub, "seconds": round(self.duration(sub, feat, default), 1)})
            if st in ("shape", "parts"):
                loaded.add(st if st == "parts" or req.engine == "cube3d" else req.engine)
        return out

    def remaining(self, job: dict, req: JobRequest, loaded: set[str], worker_up: bool,
                  now: float | None = None) -> dict:
        """Seconds left for a job, split by stage. Uses live progress for the running substage."""
        now = now or time.time()
        stages = job["stages"]
        todo = [s for s, v in stages.items() if v.get("state") in ("pending", "running")]
        by_stage: dict[str, float] = {}
        running = next((s for s in todo if stages[s].get("state") == "running"), None)
        plan = self.plan(req, todo, loaded, worker_up or running is not None)
        cur = stages.get(running, {}) if running else {}
        cur_sub = cur.get("sub")
        planned_subs = {i["sub"] for i in plan if i["stage"] == running}
        # A current substage outside the plan (the worker starting, an extra model load) comes first:
        # count its own remainder, then every planned substage of the stage as still to do.
        seen_current = not cur_sub or cur_sub not in planned_subs
        if running and cur_sub and cur_sub not in planned_subs:
            extra = {"worker.start": WORKER_START_S}.get(cur_sub, 0.0) * self.scale
            elapsed = now - (cur.get("sub_started") or now)
            by_stage[running] = max(0.0, extra - elapsed)
        for item in plan:
            secs = item["seconds"]
            if running and item["stage"] == running:
                if item["sub"] == cur_sub:
                    seen_current = True
                    secs = self._live(item, cur, now)
                elif not seen_current:
                    continue  # substages of the running stage that already finished
            by_stage[item["stage"]] = by_stage.get(item["stage"], 0.0) + secs
        total = sum(by_stage.values())
        return {"eta_s": round(total, 1), "by_stage": {k: round(v, 1) for k, v in by_stage.items()},
                "done_at": now + total}

    @staticmethod
    def _live(item: dict, cur: dict, now: float) -> float:
        planned = item["seconds"]
        started = cur.get("sub_started") or now
        elapsed = max(0.0, now - started)
        step, total = cur.get("step"), cur.get("total")
        if step and total and step >= max(3, total * 0.03):
            rate = elapsed / step
            return max(0.0, rate * (total - step))
        return max(0.0, planned - elapsed) if elapsed < planned else planned * 0.1
