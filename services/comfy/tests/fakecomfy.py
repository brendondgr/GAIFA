"""A fake ComfyUI for tests: the HTTP routes the adapter uses, served on a free port in a thread.
`/__fake/start` and `/__fake/quit` stand in for bin/comfyui (see `fake_control`)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect


def PNG_1x1(w: int, h: int) -> bytes:
    """A PNG header with the given size (enough for the adapter, which reads only the size)."""
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeComfy:
    def __init__(self, object_info: dict | None = None, up: bool = True, outputs: Path | None = None):
        self.up = up
        self.outputs = outputs           # where "executed" prompts write their files
        self.history: dict[str, dict] = {}
        self.sockets: list = []
        self.step_s = 0.02               # time per simulated node
        self.fail_node: str | None = None
        self.hold = False                # keep prompts running until released
        self.object_info = object_info or {}
        self.freed = 0
        self.prompts: list[dict] = []
        self.queue_running: list = []
        self.queue_pending: list = []
        self.uploads: dict[str, bytes] = {}
        self.interrupted: list = []
        self.stuck = False      # ignore interrupts (a GPU kernel that never returns)
        self.previews = False   # plan 45.1: send preview frames (event 1, event 4 with metadata, one for another prompt)
        self.deleted: list = []
        self.app = self._app()
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server: uvicorn.Server | None = None

    def _app(self) -> FastAPI:
        app = FastAPI()
        fake = self

        def need_up():
            if not fake.up:
                raise HTTPException(503, "down")

        @app.get("/system_stats")
        def stats():
            need_up()
            return {"system": {"comfyui_version": "0.37.0"}, "devices": []}

        @app.get("/queue")
        def queue():
            need_up()
            return {"queue_running": fake.queue_running, "queue_pending": fake.queue_pending}

        @app.post("/queue")
        async def queue_post(request: Request):
            body = await request.json()
            fake.deleted += body.get("delete", [])
            return {}

        @app.get("/object_info")
        def object_info():
            need_up()
            return fake.object_info

        @app.post("/free")
        def free():
            need_up()
            fake.freed += 1
            return {}

        @app.post("/prompt")
        async def prompt(request: Request):
            need_up()
            body = await request.json()
            pid = f"p{len(fake.prompts) + 1}"
            fake.prompts.append({"id": pid, **body})
            fake.queue_pending.append([len(fake.prompts), pid, body["prompt"], {}, []])
            asyncio.get_running_loop().create_task(fake._execute(pid, body["prompt"]))
            return {"prompt_id": pid, "number": len(fake.prompts), "node_errors": {}}

        @app.get("/history/{pid}")
        def history_one(pid: str):
            return {pid: fake.history[pid]} if pid in fake.history else {}

        @app.get("/history")
        def history_all():
            return fake.history

        @app.websocket("/ws")
        async def ws(socket: WebSocket):
            await socket.accept()
            fake.sockets.append(socket)
            try:
                while True:
                    await socket.receive_text()
            except WebSocketDisconnect:
                fake.sockets.remove(socket)

        @app.post("/interrupt")
        async def interrupt(request: Request):
            fake.interrupted.append(await request.json())
            return {}

        @app.post("/upload/image")
        async def upload(request: Request):
            form = await request.form()
            f = form["image"]
            sub = form.get("subfolder") or ""
            fake.uploads[f"{sub}/{f.filename}" if sub else f.filename] = await f.read()
            return {"name": f.filename, "subfolder": sub, "type": "input"}

        @app.post("/__fake/start")
        def start():
            fake.up = True
            return {}

        @app.post("/__fake/quit")
        def quit_():
            fake.up = False
            fake.queue_running = []
            return {}

        return app

    async def _send(self, type_: str, data: dict) -> None:
        for s in list(self.sockets):
            try:
                await s.send_json({"type": type_, "data": data})
            except Exception:  # noqa: BLE001
                pass

    async def _send_bytes(self, data: bytes) -> None:
        for s in list(self.sockets):
            try:
                await s.send_bytes(data)
            except Exception:  # noqa: BLE001
                pass

    async def _preview(self, pid: str, n: int) -> None:
        """A frame for this prompt (event 1 on odd nodes, event 4 on even ones), then one for a prompt that isn't ours."""
        import json as _json
        import struct

        png = PNG_1x1(8 * n, 6 * n)
        if n % 2:
            await self._send_bytes(struct.pack(">II", 1, 2) + png)
        else:
            meta = _json.dumps({"prompt_id": pid, "node_id": str(n), "image_type": "image/png"}).encode()
            await self._send_bytes(struct.pack(">II", 4, len(meta)) + meta + png)
        meta = _json.dumps({"prompt_id": "not-ours", "image_type": "image/png"}).encode()
        await self._send_bytes(struct.pack(">II", 4, len(meta)) + meta + PNG_1x1(2, 2))

    async def _execute(self, pid: str, graph: dict) -> None:
        """Run a prompt: start, each node with a progress tick, files from save nodes, history."""
        await asyncio.sleep(0.05)
        self.queue_pending = [e for e in self.queue_pending if e[1] != pid]
        self.queue_running.append([0, pid, graph, {}, []])
        await self._send("execution_start", {"prompt_id": pid})
        outputs, interrupted, error = {}, False, None
        for nid, node in graph.items():
            while self.hold and (self.stuck or not self._interrupt(pid)) and self.up:
                await asyncio.sleep(0.02)
            if self._interrupt(pid):
                interrupted = True
                break
            await self._send("executing", {"node": nid, "prompt_id": pid})
            await self._send("progress", {"value": 1, "max": 2, "node": nid, "prompt_id": pid})
            if self.previews:
                await self._preview(pid, list(graph).index(nid) + 1)
            await asyncio.sleep(self.step_s)
            if nid == self.fail_node:
                error = {"node_id": nid, "node_type": node["class_type"], "exception_message": "boom"}
                break
            prefix = node["inputs"].get("filename_prefix")
            if prefix and self.outputs is not None:
                sub, _, base = prefix.rpartition("/")
                ext = ".mp4" if "Video" in node["class_type"] else ".png"
                name = f"{base}_00001_{ext}"
                (self.outputs / sub).mkdir(parents=True, exist_ok=True)
                (self.outputs / sub / name).write_bytes(b"fake")
                outputs[nid] = {"images": [{"filename": name, "subfolder": sub, "type": "output"}]}
        self.queue_running = [e for e in self.queue_running if e[1] != pid]
        if interrupted:
            status = {"status_str": "error", "completed": False, "messages": [["execution_interrupted", {"prompt_id": pid}]]}
            await self._send("execution_interrupted", {"prompt_id": pid})
        elif error:
            status = {"status_str": "error", "completed": False, "messages": [["execution_error", {"prompt_id": pid, **error}]]}
            await self._send("execution_error", {"prompt_id": pid, **error})
        else:
            status = {"status_str": "success", "completed": True, "messages": []}
        self.history[pid] = {"prompt": [0, pid, graph], "outputs": outputs, "status": status}
        if not interrupted and not error:
            await self._send("executing", {"node": None, "prompt_id": pid})
            await self._send("execution_success", {"prompt_id": pid})

    def _interrupt(self, pid: str) -> bool:
        return any((i or {}).get("prompt_id") in (pid, None) for i in self.interrupted)

    def __enter__(self) -> FakeComfy:
        cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning", ws="websockets")
        self._server = uvicorn.Server(cfg)
        threading.Thread(target=self._server.run, daemon=True).start()
        for _ in range(200):
            if self._server.started:
                break
            time.sleep(0.02)
        return self

    def __exit__(self, *exc) -> None:
        if self._server:
            self._server.should_exit = True


def fake_control(path: Path, url: str) -> Path:
    """A bin/comfyui stand-in that flips the fake up and down."""
    path.write_text(f"""#!/usr/bin/env python3
import sys, urllib.request
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
route = {{"start": "start", "quit": "quit", "stop": "quit"}}.get(cmd)
if route:
    urllib.request.urlopen(urllib.request.Request("{url}/__fake/" + route, method="POST"))
    print("[comfyui] fake", cmd)
""")
    path.chmod(0o755)
    return path


class FakeHub(FakeComfy):
    """The AIHub routes the adapter calls: memory acquire, its own memory, outputs."""

    def __init__(self):
        self.acquires: list[dict] = []
        self.room = True
        self.used = 5e9
        self.files: dict[str, tuple[str, bytes]] = {}
        self.registered: list[dict] = []
        self.gpu_busy = False                      # another mod holds the GPU slot: acquires wait (202)
        self.gpu_acquires: list[dict] = []
        self.gpu_released: list[str] = []
        self.gpu_held: set[str] = set()
        super().__init__()

    def _app(self) -> FastAPI:
        app = FastAPI()
        hub = self

        @app.post("/api/memory/acquire")
        async def acquire(request: Request):
            body = await request.json()
            hub.acquires.append({**body, "make_room": request.query_params.get("make_room")})
            if not hub.room and request.query_params.get("make_room") != "1":
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not enough memory", "code": "needs_room",
                                     "data": {"plan": {"unload": ["gen3d"]}}}, status_code=409)
            return {"granted": True, "freed": [], "plan": {}}

        @app.post("/api/gpu/acquire")
        async def gpu_acquire(request: Request):
            import asyncio
            from fastapi.responses import JSONResponse
            body = await request.json()
            hub.gpu_acquires.append(body)
            if hub.gpu_busy and not body.get("parent"):
                await asyncio.sleep(min(float(request.query_params.get("wait") or 0), 0.05))
                return JSONResponse({"lease": body["lease"], "state": "waiting", "eta_s": 240,
                                     "ahead": [{"id": "gl_other", "service": "gen3d", "label": "a model", "state": "held",
                                                "eta_s": 240}]}, status_code=202)
            hub.gpu_held.add(body["lease"])
            return {"lease": body["lease"], "state": "granted"}

        @app.post("/api/gpu/{lease}/renew")
        def gpu_renew(lease: str):
            return {"lease": lease, "state": "granted"}

        @app.post("/api/gpu/{lease}/release")
        def gpu_release(lease: str):
            hub.gpu_released.append(lease)
            hub.gpu_held.discard(lease)
            return {"lease": lease, "state": "released"}

        @app.get("/api/services/comfy")
        def svc():
            return {"memory": {"used_bytes": hub.used}}

        @app.get("/api/outputs/{oid}")
        def output(oid: str):
            if oid not in hub.files:
                raise HTTPException(404)
            return {"id": oid, "path": hub.files[oid][0]}

        @app.get("/api/outputs/{oid}/file")
        def output_file(oid: str):
            from fastapi.responses import Response
            return Response(hub.files[oid][1], media_type="image/png")

        @app.get("/api/models")
        def models():
            return {"models": []}

        @app.post("/api/models")
        async def add_model(request: Request):
            hub.registered.append(await request.json())
            return {"id": "new-model"}

        @app.get("/files/{name}")
        def serve(name: str):
            from fastapi.responses import Response
            return Response(b"x" * 1000, media_type="application/octet-stream")

        return app
