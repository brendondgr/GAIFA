"""`python -m evals.blender [--model skynet] [--runs 1] [--base http://127.0.0.1:7000] [--keep] [--out file.json]`

The Blender eval (plan mcp-client 5.3), against the installed hub with the `mcp` mod's Blender server approved. Each
task resets the scene (an empty one with a camera and a light, through the mod), asks one thing in a new Manual chat,
approves every card (each code step is kept in the result to read, whether it asked or a grant allowed it), and checks Blender's state afterwards,
not the agent's words: the objects, their places and materials, whether the camera sees them, a rendered picture that
isn't blank. Chats and
the outputs they made are deleted at the end unless --keep.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from evals.cleanup import AGENT_PREFIX, forget

RESET = """import bpy
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for m in list(bpy.data.materials):
    bpy.data.materials.remove(m)
bpy.ops.object.light_add(type='SUN', location=(4, -4, 8))
bpy.ops.object.camera_add(location=(8, -8, 6))
bpy.context.scene.camera = bpy.context.object
print('reset')"""

STATE = """import bpy, json
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
bpy.context.view_layer.update()
scene, cam = bpy.context.scene, bpy.context.scene.camera
def in_view(o):
    if cam is None or o.type != 'MESH':
        return None
    c = sum((o.matrix_world @ Vector(b) for b in o.bound_box), Vector()) / 8
    p = world_to_camera_view(scene, cam, c)
    return bool(p.z > 0 and 0 <= p.x <= 1 and 0 <= p.y <= 1)
out = []
for o in bpy.data.objects:
    mats = []
    for s in getattr(o, 'material_slots', []):
        m = s.material
        if m is None:
            continue
        col = list(m.diffuse_color)[:3]
        if m.use_nodes and m.node_tree and m.node_tree.nodes.get('Principled BSDF'):
            col = list(m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value)[:3]
        mats.append({'name': m.name, 'color': [round(c, 3) for c in col]})
    out.append({'name': o.name, 'type': o.type, 'loc': [round(v, 3) for v in o.location], 'materials': mats, 'in_view': in_view(o)})
print('STATE' + json.dumps(out))"""


@dataclass
class Task:
    id: str
    prompt: str
    check: Callable[[list[dict[str, Any]], dict[str, Any]], tuple[bool, str]]
    seed: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def meshes(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [o for o in state if o["type"] == "MESH"]


def _row(state, run):
    ms = {o["name"].lower(): o for o in meshes(state)}
    if not all(k in ms for k in ("a", "b", "c")):
        return False, f"meshes: {sorted(ms)}"
    xs = [ms[k]["loc"][0] for k in ("a", "b", "c")]
    ys = {round(ms[k]["loc"][1], 1) for k in ("a", "b", "c")}
    return xs == sorted(xs) and len(set(xs)) == 3 and len(ys) == 1, f"x {xs}, y {ys}"


def _red(state, run):
    a = next((o for o in meshes(state) if o["name"].lower() == "a"), None)
    if a is None or not a["materials"]:
        return False, f"A: {a}"
    r, g, b = a["materials"][0]["color"]
    return r > 0.5 and g < 0.3 and b < 0.3, f"colour {a['materials'][0]['color']}"


def _render(state, run):
    pics = [p for p in run["new_files"] if p.suffix.lower() in (".png", ".jpg", ".jpeg") and "-look" not in p.name]
    if not pics:
        return False, "no render in outputs/mcp" + (" (only a viewport look)" if run["new_files"] else "")
    from PIL import Image, ImageStat
    st = ImageStat.Stat(Image.open(pics[-1]).convert("L"))
    return st.stddev[0] > 4, f"{pics[-1].name}: stddev {st.stddev[0]:.1f}"


def _imported(state, run):
    ms = meshes(state)
    if not ms:
        return False, "no mesh in the scene"
    seen = [o["name"] for o in ms if o["in_view"]]
    return bool(seen), f"meshes {[o['name'] for o in ms]}, in view: {seen}"


def _count(state, run):
    n = len(state)
    return str(n) in run["answer"], f"{n} objects; said: {run['answer'][:80]!r}"


TASKS = [
    Task("row", "In Blender: add three primitives in a row along the X axis, a cube named A, a sphere named B and a cone named C, "
         "one metre apart, all at the same Y.", _row),
    Task("material", "In Blender: give the object named A a red material.", _red,
         seed="import bpy\nbpy.ops.mesh.primitive_cube_add(location=(0,0,0)); bpy.context.object.name = 'A'"),
    Task("render", "In Blender: render a small (512 px) picture of the scene and show it to me.", _render,
         seed="import bpy\nbpy.ops.mesh.primitive_monkey_add(location=(0,0,1)); bpy.context.object.name = 'Suzanne'\n"
              "c = bpy.context.scene.camera.constraints.new('TRACK_TO'); c.target = bpy.data.objects['Suzanne']; "
              "c.track_axis = 'TRACK_NEGATIVE_Z'; c.up_axis = 'UP_Y'"),
    Task("gen3d", "In Blender: import the newest 3D model GAIFA's gen3d made and point the camera at it.", _imported,
         seed="import bpy\nbpy.context.scene.camera.rotation_euler = (0, 0, 0)"),     # looking straight down at nothing
    Task("tree", "make a low-poly tree in Blender and show me a render", _render),        # the plan's Phase 5 check
    Task("count", "In Blender: how many objects are in the scene right now? Answer with the number.", _count,
         seed="import bpy\nfor i in range(3): bpy.ops.mesh.primitive_cube_add(location=(i*2,0,0))"),
]


class Run:
    def __init__(self, base: str, model: str) -> None:
        self.base, self.model = base.rstrip("/"), model
        self.c = httpx.AsyncClient(base_url=self.base, timeout=180)

    async def blender(self, code: str) -> str:
        r = await self.c.post("/api/s/mcp/v1/call/blender/execute_blender_code", json={"arguments": {"code": code}})
        r.raise_for_status()
        return r.json().get("text") or ""

    async def state(self) -> list[dict[str, Any]]:
        t = await self.blender(STATE)
        return json.loads(t.split("STATE", 1)[1].split("\n", 1)[0])

    async def one(self, t: Task, outputs: Path) -> dict[str, Any]:
        await self.blender(RESET)
        if t.seed:
            await self.blender(t.seed)
        A = "/api/s/agent"
        tid = (await self.c.post(f"{A}/v1/threads", json={"title": f"eval blender {t.id}", "mode": "manual", "model": self.model})).json()["id"]
        t0 = time.time()
        await self.c.post(f"{A}/v1/threads/{tid}/messages", json={"text": t.prompt})
        codes: list[str] = []
        seen: set[str] = set()
        while time.time() - t0 < 600:
            th = (await self.c.get(f"{A}/v1/threads/{tid}")).json()
            evs = (await self.c.get(f"{A}/v1/threads/{tid}/events")).json()
            waiting = [e["payload"] for e in evs if e["type"] == "approval" and e["payload"]["approval_id"] not in seen
                       and not any(d["type"] == "decision" and d["payload"]["approval_id"] == e["payload"]["approval_id"] for d in evs)]
            for ap in waiting:
                seen.add(ap["approval_id"])
                codes.append((ap.get("arguments") or {}).get("code") or json.dumps(ap.get("arguments"))[:500])
                await self.c.post(f"{A}/v1/threads/{tid}/approval", json={"approval_id": ap["approval_id"], "approve": True})
            if th["state"] in ("idle", "error") and not waiting:
                break
            await asyncio.sleep(1.5)
        evs = (await self.c.get(f"{A}/v1/threads/{tid}/events")).json()
        calls = [e["payload"] for e in evs if e["type"] == "tool_call"]
        tools = [c["name"] for c in calls]
        codes += [(c.get("arguments") or {}).get("code") for c in calls
                  if c["name"].endswith("execute_blender_code") and (c.get("arguments") or {}).get("code") not in codes]
        answer = "\n".join(e["payload"].get("text") or "" for e in evs if e["type"] == "assistant").strip()
        usage = [e["payload"] for e in evs if e["type"] == "usage"]
        new_files = sorted((p for p in (outputs.rglob("*") if outputs.exists() else []) if p.is_file() and p.suffix != ".json"
                            and p.stat().st_mtime >= t0), key=lambda p: p.stat().st_mtime)    # new or written over
        run = {"answer": answer, "new_files": new_files}
        ok, why = t.check(await self.state(), run)
        return {"id": t.id, "ok": ok, "why": why, "thread": tid, "events": evs, "seconds": round(time.time() - t0, 1), "tools": tools,
                "code_steps": len(codes), "codes": codes, "answer": answer[:400],
                "prompt_tokens": max((u.get("prompt_tokens") or 0 for u in usage), default=0),
                "files": [str(p) for p in new_files]}


async def main(a: argparse.Namespace) -> int:
    r = Run(a.base, a.model)
    outputs = Path(a.outputs)
    rows = []
    for i in range(a.runs):
        for t in TASKS:
            if a.only and t.id not in a.only.split(","):
                continue
            row = await r.one(t, outputs)
            row["run"] = i
            rows.append(row)
            print(f"{t.id:9} run {i} {'PASS' if row['ok'] else 'FAIL'} {row['seconds']:6.1f}s code_steps={row['code_steps']} "
                  f"tools={row['tools']} :: {row['why']}", flush=True)
    if not a.keep:                         # the chats and the outputs they made, for good (evals/cleanup.py)
        for row in rows:
            await forget(httpx.AsyncClient(base_url=r.base + AGENT_PREFIX), r.c, [row["thread"]], row["events"])
    for row in rows:
        row.pop("events")
    print("summary:", json.dumps({t.id: f"{sum(x['ok'] for x in rows if x['id'] == t.id)}/{sum(1 for x in rows if x['id'] == t.id)}" for t in TASKS}))
    if a.out:
        Path(a.out).write_text(json.dumps({"model": a.model, "rows": rows}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:7000")
    p.add_argument("--model", default="skynet")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--only", default="")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--out", default="")
    p.add_argument("--outputs", default=str(Path(__file__).resolve().parents[3] / "outputs" / "mcp"))
    raise SystemExit(asyncio.run(main(p.parse_args())))
