"""Running packs (plan 11.7): memory, ComfyUI's queue, progress over its websocket, results with
sidecars, cancel. Runs are rows in comfy.db; a run that was going when the adapter restarted is
finished from ComfyUI's history."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import websockets

from .client import ComfyClient, ComfyError
from .config import Settings
from .db import DB
from .detect import memory_estimate
from .library import Library
from .resolve import InputError, patch, resolve, slugify
from .schema import input_schema

log = logging.getLogger("comfy")
DEFAULT_GB = 24.0
LOOP_S = 2.0                     # reconcile and peak sampling; tests patch this down
ACTIVE = ("queued", "running")
KIND_BY_EXT = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "video",
               ".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video", ".wav": "audio", ".flac": "audio",
               ".mp3": "audio", ".glb": "model3d", ".obj": "model3d"}


ROOM_WAIT_S = 5.0     # between asks for memory after freeing ComfyUI's models (memory comes back in a few seconds)
INTERRUPT_GRACE_S = 90.0   # after an interrupt, how long ComfyUI may keep running the prompt before it is unloaded as stuck

OUTPUT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
OUTSIDE = ("a file input is an output id (output:<id>), an upload (upload:<name>, from POST /v1/uploads) or a "
           "file name inside ComfyUI's input folder; absolute paths, '..', '\\' and names that lead out of it "
           "aren't accepted (upload the file, or pass its output id)")


def inside(root: Path, name: str) -> bool:
    """`name` is a plain relative path that stays inside `root` (symlinks followed). Decided before
    anything looks for the file, so a refusal never tells whether it exists."""
    if not name or "\x00" in name or "\\" in name or name.startswith("~"):
        return False
    p = Path(name)
    if p.is_absolute() or ".." in p.parts:
        return False
    try:
        return (root / p).resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


class NeedsRoom(Exception):
    def __init__(self, detail: str, plan: Any):
        super().__init__(detail)
        self.detail, self.plan = detail, plan


class Runner:
    def __init__(self, settings: Settings, db: DB, client: ComfyClient, library: Library, control):
        self.s, self.db, self.client, self.lib, self.control = settings, db, client, library, control
        self.client_id = uuid.uuid4().hex
        self.events: dict[str, asyncio.Event] = {}
        self.last_pack: str | None = None
        self.live: dict[str, dict] = {}          # run id → {total, done, node_frac, cached}
        self.by_prompt: dict[str, str] = {}      # ComfyUI prompt id → run id
        self._peaks: dict[str, float] = {}
        self._ws_connected = False

    # ---- submitting -------------------------------------------------------------------------
    async def submit(self, workflow: str, inputs: dict | None, preset: str | None = None, make_room: bool = False) -> dict:
        lib = self.lib
        lib.packs.scan()
        pack = lib.packs.get(workflow)
        if pack is None:
            raise InputError(f"no workflow {workflow!r}")
        conv, issues = lib.analysed(pack)
        errors = [i for i in issues if i.level == "error"]
        if pack.draft:
            raise InputError(f"{workflow} is a draft: save its workflow.toml first (review it on the page, or "
                             f"comfyui workflows suggest {workflow} --write)")
        if errors or conv is None:
            raise InputError(f"{workflow} has problems: " + "; ".join(i.detail for i in errors), [i.detail for i in errors])
        schema = input_schema(pack, conv, lib.catalog, lib.tasks)
        values = resolve(pack, schema, inputs, preset)
        files = {k for k, p in schema["properties"].items() if p.get("format") == "aihub-file" or
                 (p.get("type") == "array" and (p.get("items") or {}).get("format") == "aihub-file")}
        for k in files & set(values):
            values[k] = await self.materialize(values[k])
        label = str(values.get("prompt") or pack.name)[:80]
        graph = patch(pack, conv, values, lib.catalog, slugify(label, pack.id))     # refuses a bad value before any loading
        needs = self.needs_gb(pack, conv)
        if self.last_pack and self.last_pack != pack.id and await self.client.up():
            # Another workflow's models are still loaded: free them, so AIHub sees the room and this
            # run's measured peak is its own (not the two added together).
            log.info("switching %s → %s: freeing ComfyUI's models first", self.last_pack, pack.id)
            await self.client.free()
            await asyncio.sleep(ROOM_WAIT_S / 2)
        self.last_pack = pack.id
        try:
            await self.acquire(needs, make_room, f"{pack.name}")
        except NeedsRoom:
            # ComfyUI may still hold models AIHub counts as used: free them (this mod can't be
            # unloaded to make room for itself) and ask again while the memory comes back (up to 30 s).
            if not await self.client.up():
                raise
            log.info("not enough room for %s: freeing ComfyUI's own models first", pack.id)
            await self.client.free()
            for attempt in range(6):
                await asyncio.sleep(ROOM_WAIT_S)
                try:
                    await self.acquire(needs, make_room, f"{pack.name}")
                    break
                except NeedsRoom:
                    if attempt == 5:
                        raise
        if not await self.client.up():
            await self.control.load()
        self.control.touch()
        await self._copy_assets(pack)
        for _ in range(40):                      # progress comes over the websocket: be listening first
            if self._ws_connected:
                break
            await asyncio.sleep(0.05)
        rid = "r-" + uuid.uuid4().hex[:10]
        self.db.add_run(rid, pack.id, label, values)
        self.events[rid] = asyncio.Event()
        try:
            r = await self.client.prompt(graph, self.client_id, {"extra_pnginfo": {"aihub": {"workflow": pack.id, "run": rid}}})
        except ComfyError as e:
            self.db.update_run(rid, state="failed", error=_node_errors(e.data) or e.detail, finished=time.time())
            self.events[rid].set()
            raise
        pid = r["prompt_id"]
        self.by_prompt[pid] = rid
        self.live[rid] = {"total": len(graph), "done": set(), "frac": 0.0, "cached": set()}
        self.db.update_run(rid, prompt_id=pid)
        log.info("run %s: %s queued as %s (needs %.1f GB)", rid, pack.id, pid, needs)
        return self.db.run(rid)

    def needs_gb(self, pack, conv) -> float:
        m = pack.manifest
        if m and m.memory_gb:
            return m.memory_gb
        peak = self.db.peak_gb(pack.id)
        if peak:
            return round(peak * 1.1, 1)
        return memory_estimate(conv, self.lib.catalog, self.lib.sizes()) or DEFAULT_GB

    async def acquire(self, gb: float, make_room: bool, reason: str) -> None:
        if not self.s.hub_url:
            return
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=180)) as c:
                r = await c.post(f"{self.s.hub_url}/api/memory/acquire", params={"make_room": "1"} if make_room else None,
                                 json={"service": "comfy", "needs_bytes": int(gb * 1e9), "reason": reason})
        except httpx.HTTPError as e:
            log.warning("AIHub not reachable for memory acquire (%s); running anyway", e)
            return
        if r.status_code == 409:
            body = r.json()
            raise NeedsRoom(body.get("detail") or "Not enough free memory", (body.get("data") or {}).get("plan"))
        if r.status_code >= 400:
            log.warning("memory acquire answered %s: %s", r.status_code, r.text[:200])

    async def materialize(self, value: Any) -> Any:
        """A file input → a name ComfyUI's LoadImage takes (a file in its input folder). ComfyUI
        itself only checks that input/<name> exists, so a name that could leave the folder
        ("../…", "upload:../…") is refused here, before anything looks for it."""
        if isinstance(value, list):
            return [await self.materialize(v) for v in value]
        v = str(value)
        inp = self.s.input
        if "\x00" in v:
            raise InputError(f"{v!r}: {OUTSIDE}")
        if v.startswith("upload:"):
            name = v[len("upload:"):]
            if not inside(inp / "aihub", name):
                raise InputError(f"{v!r}: {OUTSIDE}")
            if not (inp / "aihub" / name).is_file():
                raise InputError(f"no uploaded file {name!r}")
            return f"aihub/{name}"
        oid = v[len("output:"):] if v.startswith("output:") else None
        if oid is None and v.startswith("/api/outputs/"):
            oid = v.split("/")[3]
        if oid is not None and not OUTPUT_ID.fullmatch(oid):
            raise InputError(f"{v!r}: not an output id (output:<id>, as hub_search_outputs or a job's result gives it)")
        if oid:
            if not self.s.hub_url:
                raise InputError("output ids need AIHub")
            async with httpx.AsyncClient(timeout=60) as c:
                meta = await c.get(f"{self.s.hub_url}/api/outputs/{oid}")
                if meta.status_code != 200:
                    raise InputError(f"no output {oid!r}")
                r = await c.get(f"{self.s.hub_url}/api/outputs/{oid}/file")
            if r.status_code != 200:
                raise InputError(f"output {oid!r}: its file couldn't be read ({r.status_code})")
            name = f"{oid}-{Path(meta.json().get('main') or meta.json().get('path') or 'image.png').name}"
            (inp / "aihub").mkdir(parents=True, exist_ok=True)
            (inp / "aihub" / name).write_bytes(r.content)
            return f"aihub/{name}"
        p = Path(v)
        if p.is_absolute():
            outputs_root = self.s.outputs.parent.resolve()
            if not p.resolve().is_relative_to(outputs_root) or not p.is_file():
                raise InputError(f"{v}: only files under AIHub's outputs can be used")
            (inp / "aihub").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, inp / "aihub" / p.name)
            return f"aihub/{p.name}"
        if not inside(inp, v):
            raise InputError(f"{v!r}: {OUTSIDE}")
        rel = self.s.outputs.parent / v                    # a result's path, as jobs report it ("comfy/<date>/…")
        if inside(self.s.outputs.parent, v) and rel.is_file():
            (inp / "aihub").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(rel, inp / "aihub" / p.name)
            return f"aihub/{p.name}"
        if (inp / v).is_file():
            return v
        raise InputError(f"{v!r}: not an output id (output:<id>), an upload (upload:<name>) or a file in ComfyUI's input folder")

    async def _copy_assets(self, pack) -> None:
        if not pack.assets:
            return
        for f in pack.assets.rglob("*"):
            if f.is_file():
                dest = self.s.input / f.relative_to(pack.assets)
                if not dest.exists() or dest.stat().st_size != f.stat().st_size:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, dest)

    # ---- progress -----------------------------------------------------------------------------
    async def listen(self) -> None:
        """ComfyUI's websocket: progress for our prompts. Reconnects; history covers gaps."""
        url = self.s.comfy_url.replace("http", "ws", 1) + f"/ws?clientId={self.client_id}"
        while True:
            if not self.control.up and not await self.client.up():
                await asyncio.sleep(1)
                continue
            try:
                async with websockets.connect(url, max_size=None, open_timeout=5) as ws:
                    self._ws_connected = True
                    log.info("listening to ComfyUI's progress")
                    async for raw in ws:
                        if isinstance(raw, str):
                            await self.on_message(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.debug("websocket: %s", e)
            self._ws_connected = False
            await asyncio.sleep(1)

    async def on_message(self, msg: dict) -> None:
        t, d = msg.get("type"), msg.get("data") or {}
        rid = self.by_prompt.get(d.get("prompt_id", ""))
        if rid is None:
            return
        live = self.live.setdefault(rid, {"total": 1, "done": set(), "frac": 0.0, "cached": set()})
        if t == "execution_start":
            self.db.update_run(rid, state="running", started=time.time())
            self._peaks[rid] = 0.0
        elif t == "execution_cached":
            live["cached"] |= set(d.get("nodes") or [])
        elif t == "executing":
            if d.get("node") is not None:
                live["done"].add(str(d["node"]))       # nodes started; all but the current one are done
                live["frac"] = 0.0
        elif t == "progress":
            mx = d.get("max") or 1
            live["frac"] = min(1.0, (d.get("value") or 0) / mx)
        elif t in ("execution_success", "execution_error", "execution_interrupted"):
            await self.finish(rid, d.get("prompt_id"))
            return
        total = max(1, live["total"] - len(live["cached"]))
        done = max(0, len(live["done"]) - 1)
        self.db.update_run(rid, progress=round(min(0.99, (done + live["frac"]) / total), 3))

    async def reconcile(self) -> None:
        """Finish runs whose end we didn't hear (websocket gap, adapter restart)."""
        for run in self.db.runs(states=ACTIVE, limit=50):
            pid = run.get("prompt_id")
            if not pid:
                if time.time() - run["created"] > 60:
                    self.db.update_run(run["id"], state="failed", error="never reached ComfyUI", finished=time.time())
                continue
            self.by_prompt.setdefault(pid, run["id"])
            try:
                h = await self.client.history(pid)
            except ComfyError:
                if not self.control.up and run["state"] in ACTIVE:
                    self.db.update_run(run["id"], state="failed", error="ComfyUI stopped", finished=time.time())
                    self._done(run["id"])
                continue
            if h and pid in h:
                await self.finish(run["id"], pid, h[pid])

    async def sample_peaks(self) -> None:
        active = {r["id"] for r in self.db.runs(states=("running",), limit=50)}
        for rid in set(self._peaks) - active:
            self._peaks.pop(rid, None)               # finished or cancelled without our noticing
        if not self.s.hub_url or not self._peaks:
            return
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{self.s.hub_url}/api/services/comfy")
            used = ((r.json().get("memory") or {}).get("used_bytes") or 0) / 1e9
        except (httpx.HTTPError, ValueError):
            return
        for rid in self._peaks:
            self._peaks[rid] = max(self._peaks[rid], used)

    # ---- finishing ----------------------------------------------------------------------------
    async def finish(self, rid: str, prompt_id: str | None, entry: dict | None = None) -> None:
        run = self.db.run(rid)
        if run is None or run["state"] not in ACTIVE:
            return
        if entry is None and prompt_id:
            for _ in range(10):                  # history lands a moment after the websocket says so
                try:
                    h = await self.client.history(prompt_id)
                except ComfyError:
                    h = {}
                if h and prompt_id in h:
                    entry = h[prompt_id]
                    break
                await asyncio.sleep(0.3)
        status = (entry or {}).get("status") or {}
        ok = status.get("status_str") == "success" or (entry is not None and status.get("completed") and not status.get("status_str"))
        files = self._files(entry or {})
        fields: dict[str, Any] = {"finished": time.time(), "progress": 1.0 if ok else run.get("progress")}
        if ok:
            pack = self.lib.packs.get(run["workflow"])
            outs = [self._sidecar(f, run, pack) for f in files]
            fields.update(state="done", outputs=outs)
        else:
            interrupted = any(m[0] == "execution_interrupted" for m in status.get("messages") or [] if m)
            fields.update(state="cancelled" if interrupted else "failed",
                          error=_history_error(status) or ("cancelled" if interrupted else "ComfyUI reported an error"))
        peak = self._peaks.pop(rid, 0.0)
        if peak:
            fields["peak_gb"] = round(peak, 2)
        self.db.update_run(rid, **fields)
        self.live.pop(rid, None)
        if prompt_id:
            self.by_prompt.pop(prompt_id, None)
        self.control.touch()
        self._done(rid)
        log.info("run %s: %s (%d file(s))", rid, fields["state"], len(fields.get("outputs") or []))

    def _done(self, rid: str) -> None:
        ev = self.events.pop(rid, None)
        if ev:
            ev.set()

    def _files(self, entry: dict) -> list[Path]:
        out = []
        for node_out in (entry.get("outputs") or {}).values():
            for key, items in node_out.items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and it.get("type") == "output" and it.get("filename"):
                        p = self.s.outputs / (it.get("subfolder") or "") / it["filename"]
                        if p not in out:
                            out.append(p)
        return out

    def _sidecar(self, f: Path, run: dict, pack) -> dict:
        kind = KIND_BY_EXT.get(f.suffix.lower(), "file")
        inputs = run.get("inputs") or {}
        side = {"title": (str(inputs.get("prompt") or pack.name if pack else run["workflow"]))[:80], "kind": kind,
                "prompt": inputs.get("prompt"), "seed": inputs.get("seed"), "model": pack.name if pack else run["workflow"],
                "params": {k: v for k, v in inputs.items() if k not in ("prompt",)},
                "source": {"service": "comfy", "workflow": run["workflow"], "run": run["id"], "task": pack.task if pack else None},
                "seconds": round(time.time() - (run.get("started") or run["created"]), 1)}
        try:
            tmp = f.with_name(f.name + ".json.part")
            tmp.write_text(json.dumps(side, indent=1))
            os.replace(tmp, f.with_name(f.name + ".json"))
        except OSError as e:
            log.warning("sidecar for %s not written: %s", f, e)
        try:
            rel = str(f.relative_to(self.s.outputs.parent))
        except ValueError:
            rel = str(f)
        return {"path": rel, "kind": kind, "name": f.name}

    # ---- cancel and wait ----------------------------------------------------------------------
    async def cancel(self, rid: str) -> dict:
        run = self.db.run(rid)
        if run is None:
            raise KeyError(rid)
        if run["state"] not in ACTIVE:
            return run
        pid = run.get("prompt_id")
        if pid:
            q = await self.client.queue()
            running = {e[1] for e in q.get("queue_running") or []}
            if pid in running:
                await self.client.interrupt(pid)
                asyncio.create_task(self._unstick(pid))
            else:
                await self.client.delete_queued([pid])
        self.db.update_run(rid, state="cancelled", finished=time.time(), error="cancelled")
        self.live.pop(rid, None)
        self._peaks.pop(rid, None)
        self._done(rid)
        return self.db.run(rid)

    async def _unstick(self, pid: str) -> None:
        """An interrupt only lands between steps. If the prompt is still running after the grace time,
        ComfyUI is stuck inside one (seen: a GPU kernel that never returned while the LLM shared the
        GPU), so ComfyUI is unloaded; the next job starts it fresh."""
        deadline = time.monotonic() + INTERRUPT_GRACE_S
        while time.monotonic() < deadline:
            await asyncio.sleep(min(5.0, INTERRUPT_GRACE_S / 10))
            try:
                if pid not in {e[1] for e in (await self.client.queue()).get("queue_running") or []}:
                    return
            except Exception:  # noqa: BLE001 - ComfyUI went away: nothing to unstick
                return
        log.warning("ComfyUI didn't stop prompt %s within %.0f s of the interrupt; unloading it", pid, INTERRUPT_GRACE_S)
        try:
            await self.control.unload()
        except Exception as e:  # noqa: BLE001
            log.error("couldn't unload a stuck ComfyUI: %s", e)

    async def wait(self, rid: str, secs: float) -> dict | None:
        run = self.db.run(rid)
        if run is None or run["state"] not in ACTIVE or secs <= 0:
            return run
        ev = self.events.setdefault(rid, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), secs)
        except TimeoutError:
            pass
        return self.db.run(rid)

    async def loop(self) -> None:
        while True:
            try:
                await self.sample_peaks()
                if not self._ws_connected or self.db.runs(states=ACTIVE, limit=1):
                    await self.reconcile()
            except Exception:  # noqa: BLE001
                log.exception("run loop")
            await asyncio.sleep(LOOP_S)


def _node_errors(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    parts = []
    err = data.get("error")
    if isinstance(err, dict):
        parts.append(err.get("message") or "")
    for nid, ne in (data.get("node_errors") or {}).items():
        for e in ne.get("errors") or []:
            parts.append(f"node {nid} ({ne.get('class_type')}): {e.get('message')} {e.get('details') or ''}".strip())
    return "; ".join(p for p in parts if p)


def _history_error(status: dict) -> str:
    for m in status.get("messages") or []:
        if m and m[0] == "execution_error":
            d = m[1] or {}
            return f"node {d.get('node_id')} ({d.get('node_type')}): {d.get('exception_message', '').strip()}"
    return ""
