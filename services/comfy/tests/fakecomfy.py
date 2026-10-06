"""A fake ComfyUI for tests: the HTTP routes the adapter uses, served on a free port in a thread.
`/__fake/start` and `/__fake/quit` stand in for bin/comfyui (see `fake_control`)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeComfy:
    def __init__(self, object_info: dict | None = None, up: bool = True):
        self.up = up
        self.object_info = object_info or {}
        self.freed = 0
        self.prompts: list[dict] = []
        self.queue_running: list = []
        self.queue_pending: list = []
        self.uploads: dict[str, bytes] = {}
        self.interrupted: list = []
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
            return {"prompt_id": pid, "number": len(fake.prompts), "node_errors": {}}

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
            return {}

        return app

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
