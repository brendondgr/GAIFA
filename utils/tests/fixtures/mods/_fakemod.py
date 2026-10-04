"""Fake mods for tests and `app.py --demo-mods`. Standard library only, like any
mod could be: the hub sees nothing but HTTP.

    python3 _fakemod.py ok|slow|crash|mem      (port from FAKE_PORT, outputs from FAKE_OUTPUTS)

ok     health, status, openapi, echo, audio, SSE, jobs and a route that writes an output
slow   like ok, but /health answers 503 for the first FAKE_SLOW_S (3) seconds
crash  like ok, but the process exits with status 1 after FAKE_CRASH_S (1) seconds
mem    like ok, plus /v1/load allocates FAKE_MEM_MB (64) MB and /v1/unload frees it

POST /v1/upload reads the body in chunks and returns its size and sha256 (for big uploads).
GET /v1/events?n=3&gap=0.05 streams n server-sent events, gap seconds apart.
GET /v1/redirect answers 307 to /v1/status.
POST /v1/fail answers 500 {"detail": ...} (an upstream error); DELETE /v1/jobs/{id} removes a job (destructive).
POST /v1/jobs {"label", "seconds"} starts a job that /v1/status reports with progress
(busy while it runs). FAKE_BAD_STATUS=1 makes /v1/status return a malformed body.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import struct
import sys
import threading
import time
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MODE = sys.argv[1] if len(sys.argv) > 1 else "ok"
PORT = int(os.environ.get("FAKE_PORT", "5190"))
OUTPUTS = Path(os.environ.get("FAKE_OUTPUTS") or os.environ.get("AIHUB_OUTPUTS") or "outputs")
STARTED = time.time()
STATE = {"last_used": time.time(), "requests": 0, "outputs": 0, "memory": None}
JOBS: dict[str, dict] = {}
MB = 1024 * 1024


def openapi() -> dict:
    def op(summary, body=None, response="application/json"):
        o = {"summary": summary, "responses": {"200": {"content": {response: {"schema": {}}}}}}
        if body:
            o["requestBody"] = {"content": {"application/json": {"schema": body}}}
        return o

    text = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    paths = {
        "/health": {"get": op("Health")},
        "/v1/status": {"get": op("Status")},
        "/v1/echo": {"post": op("Echo the body and query", {"type": "object"})},
        "/v1/speech": {"post": op("A short sine tone as WAV", text, "audio/wav")},
        "/v1/events": {"get": {**op("Server-sent events (3 by default)", response="text/event-stream"), "parameters": [
            {"name": "n", "in": "query", "required": False, "schema": {"type": "integer", "default": 3, "minimum": 1}},
            {"name": "gap", "in": "query", "required": False, "schema": {"type": "number", "default": 0.05}}]}},
        "/v1/outputs": {"post": op("Write a text output", text)},
        "/v1/upload": {"post": {"summary": "Upload a file", "requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}}}}, "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
        "/v1/fail": {"post": op("Always fails with HTTP 500")},
        "/v1/jobs/{jid}": {"delete": {"summary": "Delete a job", "parameters": [{"name": "jid", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
        "/v1/jobs": {"post": op("Start a job that runs for `seconds`", {"type": "object", "properties": {"label": {"type": "string"}, "seconds": {"type": "number"}}})},
    }
    if MODE == "mem":
        paths["/v1/load"] = {"post": op("Allocate memory")}
        paths["/v1/unload"] = {"post": op("Free memory")}
    return {"openapi": "3.1.0", "info": {"title": f"fake-{MODE}", "version": "1.0.0"}, "paths": paths}


def tone(seconds: float = 0.25, hz: float = 440.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(n)))
    return buf.getvalue()


def write_output(text: str) -> Path:
    """Per architecture §4.7: <date>/<HHMMSS>-<slug>.txt, via .part, with a sidecar."""
    now = datetime.now()
    day = OUTPUTS / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "output"
    path = day / f"{now.strftime('%H%M%S')}-{slug}.txt"
    part = path.with_name(path.name + ".part")
    part.write_text(text)
    part.rename(path)
    meta = {"title": text[:60], "kind": "text", "prompt": text, "source": {"service": f"fake-{MODE}"}}
    path.with_name(path.name + ".json").write_text(json.dumps(meta))
    return path


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet unless FAKE_VERBOSE
        if os.environ.get("FAKE_VERBOSE"):
            super().log_message(fmt, *args)

    def send(self, status: int, body: bytes | dict | list, ctype: str = "application/json") -> None:
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/health":
            if MODE == "slow" and time.time() - STARTED < float(os.environ.get("FAKE_SLOW_S", "3")):
                return self.send(503, {"status": "starting"})
            return self.send(200, {"status": "ok", "mode": MODE})
        if url.path == "/v1/status":
            return self.send(200, status())
        if url.path == "/openapi.json":
            return self.send(200, openapi())
        if url.path == "/v1/events":
            q = parse_qs(url.query)
            return self.sse(int(q.get("n", ["3"])[0]), float(q.get("gap", ["0.05"])[0]))
        if url.path == "/v1/redirect":
            self.send_response(307)
            self.send_header("Location", "/v1/status")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send(404, {"detail": f"no route {url.path}"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        STATE["requests"] += 1
        STATE["last_used"] = time.time()
        if url.path == "/v1/echo":
            return self.send(200, {"json": self.body(), "query": parse_qs(url.query), "headers": dict(self.headers)})
        if url.path == "/v1/speech":
            self.body()
            return self.send(200, tone(), "audio/wav")
        if url.path == "/v1/outputs":
            path = write_output(self.body().get("text") or "hello")
            STATE["outputs"] += 1
            return self.send(201, {"path": str(path)})
        if url.path == "/v1/upload":
            import hashlib

            n = int(self.headers.get("Content-Length") or 0)
            h, size = hashlib.sha256(), 0
            while size < n:
                chunk = self.rfile.read(min(1 << 20, n - size))
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
            return self.send(200, {"size": size, "sha256": h.hexdigest(), "content_type": self.headers.get("Content-Type", "")})
        if url.path == "/v1/fail":
            return self.send(500, {"detail": "fake failure: this route always fails"})
        if url.path == "/v1/jobs":
            b = self.body()
            jid = f"j_{len(JOBS) + 1}"
            JOBS[jid] = {"id": jid, "label": b.get("label") or jid, "start": time.time(), "seconds": float(b.get("seconds") or 1)}
            return self.send(202, {"id": jid})
        if MODE == "mem" and url.path == "/v1/load":
            mb = int(self.body().get("mb") or os.environ.get("FAKE_MEM_MB", "64"))
            block = bytearray(mb * MB)
            for i in range(0, len(block), 4096):  # touch every page so it counts as RSS
                block[i] = 1
            STATE["memory"] = block
            return self.send(200, {"loaded": True, "mb": mb})
        if MODE == "mem" and url.path == "/v1/unload":
            STATE["memory"] = None
            return self.send(200, {"loaded": False})
        self.send(404, {"detail": f"no route {url.path}"})

    def do_DELETE(self) -> None:
        url = urlsplit(self.path)
        STATE["last_used"] = time.time()
        if url.path.startswith("/v1/jobs/"):
            jid = url.path.rsplit("/", 1)[1]
            if JOBS.pop(jid, None) is None:
                return self.send(404, {"detail": f"no job {jid}"})
            return self.send(200, {"deleted": jid})
        self.send(404, {"detail": f"no route {url.path}"})

    def sse(self, n: int = 3, gap: float = 0.05) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for i in range(n):
                self.wfile.write(f"data: {json.dumps({'n': i})}\n\n".encode())
                self.wfile.flush()
                time.sleep(gap)
        except (BrokenPipeError, ConnectionResetError):
            STATE["sse_aborted"] = STATE.get("sse_aborted", 0) + 1
        self.close_connection = True


def jobs() -> list[dict]:
    out = []
    for j in JOBS.values():
        p = min(1.0, (time.time() - j["start"]) / j["seconds"])
        out.append({"id": j["id"], "label": j["label"], "progress": round(p, 3), "state": "done" if p >= 1 else "running"})
    return out


def status() -> dict:
    if os.environ.get("FAKE_BAD_STATUS"):
        return {"loaded": "yes", "stats": [{"value": 1}, 3, {"label": "x", "value": [1]}], "jobs": {"id": 1}}
    js = jobs()
    s: dict = {
        "sse_aborted": STATE.get("sse_aborted", 0),
        "loaded": STATE["memory"] is not None if MODE == "mem" else None,
        "busy": any(j["state"] == "running" for j in js),
        "idle_s": round(time.time() - STATE["last_used"], 1),
        "stats": [
            {"label": "Requests", "value": STATE["requests"]},
            {"label": "Outputs today", "value": STATE["outputs"], "reset": "daily"},
        ],
        "jobs": js,
    }
    if MODE == "mem":
        s["memory_estimate_gb"] = round(int(os.environ.get("FAKE_MEM_MB", "64")) / 1024, 3)
    return s


def main() -> None:
    if MODE not in {"ok", "slow", "crash", "mem"}:
        sys.exit(f"unknown mode {MODE!r}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    if MODE == "crash":
        threading.Timer(float(os.environ.get("FAKE_CRASH_S", "1")), lambda: os._exit(1)).start()
    print(f"fake-{MODE} listening on 127.0.0.1:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
