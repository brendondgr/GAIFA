"""Fake mods for tests and `app.py --demo-mods`. Standard library only, like any
mod could be: the hub sees nothing but HTTP.

    python3 _fakemod.py ok|slow|crash|mem|tools|perms      (port from FAKE_PORT, outputs from FAKE_OUTPUTS)

ok     health, status, openapi, echo, audio, SSE, jobs and a route that writes an output
slow   like ok, but /health answers 503 for the first FAKE_SLOW_S (3) seconds
crash  like ok, but the process exits with status 1 after FAKE_CRASH_S (1) seconds
mem    like ok, plus /v1/load allocates FAKE_MEM_MB (64) MB and /v1/unload frees it
tools  like ok, plus routes for agent tools (plan 13): items, an image output, speech with a saved
       path, a render job (GET /v1/render/{rid}, cancel), multipart upload, and GET /v1/tools
       (POST /v1/tools/doodle adds a tool there, and status's tools_rev goes 1 → 2; plan 51.1)
perms  like ok, plus network and execute tools (plan 25): POST /v1/search, /v1/fetch, /v1/python
       and /v1/run echo what they were sent as {"ran": <route>, "arguments": {...}}
ws     like ok, plus a workspace mod in miniature with its preflight /v1/limits (plan 27.4; _fakews.py)
engine like ok, plus the [llm] engine contract (plan llm-servers 3.1): GET /v1/llm/catalog (two models),
       GET /v1/llm/engine, POST /v1/llm/load {id} (202; unknown: 404), POST /v1/llm/unload {id?}

POST /v1/upload reads the body in chunks and returns its size and sha256 (for big uploads).
GET /v1/events?n=3&gap=0.05 streams n server-sent events, gap seconds apart.
GET /v1/redirect answers 307 to /v1/status.
GET /v1/widgets/requests?range=24h is a WidgetData (fake-ok's dashboard widget); it counts its own
calls in `calls`, and FAKE_BAD_WIDGET=1 makes it malformed.
POST /v1/fail answers 500 {"detail": ...} (an upstream error); DELETE /v1/jobs/{id} removes a job (destructive).
POST /v1/jobs {"label", "seconds"} starts a job that /v1/status reports with progress
(busy while it runs). FAKE_BAD_STATUS=1 makes /v1/status return a malformed body; FAKE_TOOLS_OFF (JSON) is its tools_off.
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
OUTPUTS = Path(os.environ.get("FAKE_OUTPUTS") or os.environ.get("GAIFA_OUTPUTS") or "outputs")
STARTED = time.time()
STATE = {"last_used": time.time(), "requests": 0, "outputs": 0, "memory": None, "doodle": False}
JOBS: dict[str, dict] = {}
ENGINE_MODELS = [{"id": "tiny-gguf", "name": "Tiny (GGUF)", "format": "gguf", "size_gb": 0.5, "memory_gb": 1.0, "context": 8192,
                  "downloaded": True, "relay_model": "tiny"},
                 {"id": "small-hf", "name": "Small (HF)", "format": "hf", "size_gb": 2.0, "memory_gb": 6.0, "context": 32768,
                  "downloaded": False, "relay_model": "small-vllm"}]
LOADED: set[str] = set()
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
        "/v1/widgets/requests": {"get": {**op("Requests (dashboard widget)"), "parameters": [
            {"name": "range", "in": "query", "required": False, "schema": {"type": "string", "default": "24h"}}]}},
        "/v1/jobs/{jid}": {"delete": {"summary": "Delete a job", "parameters": [{"name": "jid", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
        "/v1/jobs": {"post": op("Start a job that runs for `seconds`", {"type": "object", "properties": {"label": {"type": "string"}, "seconds": {"type": "number"}}})},
    }
    if MODE == "tools":
        paths.update(tool_paths())
    if MODE == "perms":
        paths.update(perm_paths())
    if MODE == "ws":
        import _fakews

        paths.update(_fakews.paths())
    if MODE == "engine":
        paths["/v1/llm/catalog"] = {"get": op("What this engine can run")}
        paths["/v1/llm/engine"] = {"get": op("What runs now")}
        paths["/v1/llm/load"] = {"post": op("Start a model", {"type": "object", "properties": {"id": {"type": "string"}}})}
        paths["/v1/llm/unload"] = {"post": op("Stop a model, or all", {"type": "object", "properties": {"id": {"type": "string"}}})}
    if MODE == "mem":
        paths["/v1/load"] = {"post": op("Allocate memory")}
        paths["/v1/unload"] = {"post": op("Free memory")}
    return {"openapi": "3.1.0", "info": {"title": f"fake-{MODE}", "version": "1.0.0"}, "paths": paths, "components": COMPONENTS}


def tool_paths() -> dict:
    def ok(summary, body=None, params=None, response="application/json", method="post"):
        o = {"summary": summary, "responses": {"200": {"content": {response: {"schema": {}}}}}}
        if body:
            o["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
        if params:
            o["parameters"] = params
        return {method: o}

    item = [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "verbose", "in": "query", "required": False, "schema": {"type": "boolean", "default": False}}]
    image = {"$ref": "#/components/schemas/ImageReq"}
    return {
        "/v1/items/{item_id}": ok("Get one item", params=item, method="get"),
        "/v1/images": ok("Make an image (a PNG output)", image),
        "/v1/say": ok("Speak text: WAV bytes, saved to outputs", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, response="audio/wav"),
        "/v1/beep": ok("A WAV the mod doesn't save", {"type": "object", "properties": {}}, response="audio/wav"),
        "/v1/render": ok("Start a render job", {"type": "object", "properties": {"prompt": {"type": "string"}, "seconds": {"type": "number", "default": 0.5}, "fail": {"type": "boolean", "default": False}}, "required": ["prompt"]}),
        "/v1/render/{rid}": ok("A render job", params=[{"name": "rid", "in": "path", "required": True, "schema": {"type": "string"}}], method="get"),
        "/v1/render/{rid}/cancel": ok("Cancel a render", params=[{"name": "rid", "in": "path", "required": True, "schema": {"type": "string"}}]),
        "/v1/mesh": {"post": {"summary": "Upload a mesh", "requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object", "properties": {"mesh": {"type": "string", "format": "binary"}, "note": {"type": "string"}}, "required": ["mesh"]}}}}, "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}},
        "/v1/big": ok("A large JSON result", method="get"),
        "/v1/tools": ok("Runtime tools", method="get"),
        "/v1/tools/{name}/call": ok("Call a runtime tool", {"type": "object"}, [{"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}]),
    }


def perm_paths() -> dict:
    def body(props: dict, required: list[str]) -> dict:
        return {"post": {"summary": "", "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "properties": props, "required": required}}}}, "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}}

    s = {"type": "string"}
    return {
        "/v1/search": body({"query": s}, ["query"]),
        "/v1/fetch": body({"url": s, "max_chars": {"type": "integer", "default": 2000}}, ["url"]),
        "/v1/python": body({"code": {**s, "description": "the Python to run"}, "folder": s}, ["code"]),
        "/v1/run": body({"folder": s, "command": {**s, "description": "a shell command"}}, ["folder", "command"]),
    }


COMPONENTS = {"schemas": {"ImageReq": {"type": "object", "title": "ImageReq", "properties": {
    "prompt": {"type": "string", "title": "Prompt", "description": "what to draw"},
    "aspect": {"type": "string", "enum": ["1:1", "16:9", "9:16"], "default": "1:1"},
    "steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
    "reference": {"anyOf": [{"type": "string", "format": "gaifa-file"}, {"type": "null"}], "description": "an image to follow"},
}, "required": ["prompt"]}}}
RENDERS: dict[str, dict] = {}


# A tool whose engine choices declare what they need (plan 20.1).
SHAPE = {"type": "object", "properties": {
    "prompt": {"type": "string"}, "image": {"type": "string", "format": "gaifa-file"},
    "engine": {"type": "string", "enum": ["words", "picture", "body"], "x-options": {
        "words": {"label": "From words", "needs": ["prompt"], "excludes": ["image"], "default": True, "good_for": "text only"},
        "picture": {"label": "From a picture", "needs": ["image"], "default": True, "good_for": "objects", "allows": {"preset": ["base", "fast"]}},
        "body": {"label": "Body", "needs": ["image"], "good_for": "a person's body", "allows": {"preset": ["base"]}}}},
    "preset": {"type": "string", "enum": ["base", "fast", "draft"], "x-depends-on": "engine", "x-options": {
        "fast": {"quality": "fast", "when": "only when the user asks for a quick result"}, "draft": {"quality": "draft"}}}},
    "additionalProperties": False}


def png(w: int = 4, h: int = 4) -> bytes:
    import zlib
    raw = b"".join(b"\x00" + b"\xff\x80\x00" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def save(name: str, data: bytes, meta: dict) -> Path:
    now = datetime.now()
    day = OUTPUTS / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "output"
    path = day / f"{now.strftime('%H%M%S')}-{slug}-{len(list(day.iterdir()))}{Path(name).suffix or '.bin'}"
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    path.with_name(path.name + ".json").write_text(json.dumps(meta))
    part.rename(path)
    return path


def render_state(r: dict) -> dict:
    if r["state"] == "running":
        p = (time.time() - r["start"]) / r["seconds"]
        if p >= 1:
            if r["fail"]:
                r.update(state="failed", error="the fake render failed")
            else:
                f = save(r["prompt"] + ".png", png(), {"title": r["prompt"], "prompt": r["prompt"], "kind": "image"})
                r.update(state="done", outputs=[{"path": str(f.relative_to(OUTPUTS.parent)), "kind": "image"}])
        else:
            r["progress"] = round(p, 2)
    out = {k: v for k, v in r.items() if k not in ("start",)}
    if r["state"] == "running":           # plan 44.2: a live shape with a new preview frame per quarter
        step = min(4, int(p * 4) + 1)
        out["live"] = {"stage": "sampling", "step": step, "steps": 4, "eta_s": round(r["seconds"] * (1 - p), 1),
                       "preview": {"url": f"/v1/render/{r['id']}/preview", "seq": step, "w": 64, "h": 48}, "junk": "x" * 10}
    return out


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
        if url.path == "/v1/widgets/requests":
            return self.send(200, widget(parse_qs(url.query).get("range", ["24h"])[0]))
        if MODE == "engine" and url.path == "/v1/llm/catalog":
            return self.send(200, {"models": [{**m, "loaded": m["id"] in LOADED} for m in ENGINE_MODELS]})
        if MODE == "engine" and url.path == "/v1/llm/engine":
            return self.send(200, {"state": "ready" if LOADED else "idle", "loaded": sorted(LOADED)})
        if MODE == "tools":
            m = re.fullmatch(r"/v1/items/([^/]+)", url.path)
            if m:
                return self.send(200, {"id": m.group(1), "verbose": parse_qs(url.query).get("verbose", ["false"])[0]})
            m = re.fullmatch(r"/v1/render/([^/]+)", url.path)
            if m:
                r = RENDERS.get(m.group(1))
                return self.send(200, render_state(r)) if r else self.send(404, {"detail": "no render"})
            if url.path == "/v1/big":
                return self.send(200, {"rows": [{"i": i, "text": "x" * 50} for i in range(400)]})
            if url.path == "/v1/tools":
                return self.send(200, {"tools": [
                    {"type": "function", "function": {"name": "paint", "description": "Paint a picture (runtime tool).",
                     "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}, "image": {"type": "string", "format": "gaifa-file"},
                                                                    "style": {"type": "string", "enum": ["oil", "ink"]}}, "required": ["prompt"]}},
                     "op": "POST /v1/tools/paint/call", "job": {"status": "GET /v1/render/{job_id}", "cancel": "POST /v1/render/{job_id}/cancel"},
                     "risk": "generate", "ask": ["style"], "examples": [{"prompt": "a fox", "style": "ink"}]},
                    {"type": "function", "function": {"name": "styles", "description": "List styles.", "parameters": {"type": "object", "properties": {}}},
                     "op": "POST /v1/tools/styles/call", "job": None, "risk": "read", "core": True, "group": "fake-tools:looks"},
                    {"type": "function", "function": {"name": "shape", "description": "Make a shape (x-options, plan 20.1).", "parameters": SHAPE},
                     "op": "POST /v1/tools/shape/call", "job": None, "risk": "generate", "ask": ["engine", "preset"]},
                    {"type": "function", "function": {"name": "sketch", "description": "Sketch (another style enum).", "parameters": {
                        "type": "object", "properties": {"prompt": {"type": "string"}, "style": {"type": "string", "enum": ["pencil", "charcoal"]}}}},
                     "op": "POST /v1/tools/shape/call", "job": None, "risk": "read"},
                    {"type": "function", "function": {"name": "strict", "description": "Always refused, with the mod's own fix.",
                                                      "parameters": {"type": "object", "properties": {}}},
                     "op": "POST /v1/tools/strict/call", "job": None, "risk": "read"}] + ([
                    {"type": "function", "function": {"name": "doodle", "description": "Doodle (appears after POST /v1/tools/doodle).",
                                                      "parameters": {"type": "object", "properties": {}}},
                     "op": "POST /v1/tools/styles/call", "job": None, "risk": "read"}] if STATE["doodle"] else [])})
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
        if MODE == "engine" and url.path in ("/v1/llm/load", "/v1/llm/unload"):
            mid = self.body().get("id")
            if url.path.endswith("load") and not url.path.endswith("unload"):
                if mid not in {m["id"] for m in ENGINE_MODELS}:
                    return self.send(404, {"detail": f"no model {mid}"})
                LOADED.add(mid)
                return self.send(202, {"id": mid, "state": "loading"})
            LOADED.difference_update({mid} if mid else set(LOADED))
            return self.send(200, {"loaded": sorted(LOADED)})
        if url.path == "/v1/jobs":
            b = self.body()
            jid = f"j_{len(JOBS) + 1}"
            JOBS[jid] = {"id": jid, "label": b.get("label") or jid, "start": time.time(), "seconds": float(b.get("seconds") or 1)}
            return self.send(202, {"id": jid})
        if MODE == "ws":
            import _fakews

            out = _fakews.handle(url.path, self.body(), json.loads(self.headers.get("X-GAIFA-Origin") or "{}"))
            if out is not None:
                return self.send(200, out)
        if MODE == "perms" and url.path in ("/v1/search", "/v1/fetch", "/v1/python", "/v1/run"):
            origin = json.loads(self.headers.get("X-GAIFA-Origin") or "{}")
            b = self.body()
            out = {"ran": url.path.rsplit("/", 1)[1], "arguments": b, "dry_run": bool(origin.get("dry_run"))}
            urls = [w for w in str(b.get("query") or "").split() if w.startswith(("http://", "https://"))] if isinstance(b, dict) else []
            if url.path == "/v1/search" and urls:                # URLs in the query come back as results, as the web mod's
                out["results"] = [{"title": "x", "url": u} for u in urls]
            return self.send(200, out)
        if MODE == "tools":
            if url.path == "/v1/tools/doodle":         # plan 51.1: a tool that appears while the mod runs
                STATE["doodle"] = True
                return self.send(200, {"ok": True})
            if url.path == "/v1/images":
                b = self.body()
                f = save(b.get("prompt", "image") + ".png", png(), {"title": b.get("prompt"), "prompt": b.get("prompt"), "kind": "image",
                                                                    "params": {"aspect": b.get("aspect"), "steps": b.get("steps"), "reference": b.get("reference")}})
                return self.send(200, {"path": str(f), "aspect": b.get("aspect"), "steps": b.get("steps"), "reference": b.get("reference")})
            if url.path == "/v1/say":
                b = self.body()
                f = save(b.get("text", "speech") + ".wav", tone(), {"title": b.get("text"), "kind": "audio"})
                data = tone()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("X-GAIFA-Output", str(f))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if url.path == "/v1/beep":
                self.body()
                return self.send(200, tone(), "audio/wav")
            if url.path in ("/v1/render", "/v1/tools/paint/call"):
                b = self.body()
                if url.path.startswith("/v1/tools/"):      # a tools_source call: {"arguments": {...}}
                    extra = set(b) - {"arguments"}
                    if extra:
                        return self.send(422, {"detail": f"unknown fields {sorted(extra)}"})
                    b = b.get("arguments") or {}
                rid = f"r_{len(RENDERS) + 1}"
                RENDERS[rid] = {"id": rid, "state": "running", "prompt": b.get("prompt") or "x", "start": time.time(),
                                "seconds": float(b.get("seconds") or 0.5), "fail": bool(b.get("fail")), "progress": 0.0,
                                "style": b.get("style"), "image": b.get("image")}
                return self.send(202, {"id": rid, "state": "running"} if url.path == "/v1/render" else {"status": "running", "job_id": rid})
            if url.path == "/v1/tools/shape/call":
                return self.send(200, {"ran": (self.body().get("arguments") or {})})
            if url.path == "/v1/tools/strict/call":
                self.body()
                return self.send(422, {"detail": {"detail": "the picture needs a plain background", "fix": "run remove_background on it first"}})
            if url.path == "/v1/tools/styles/call":
                self.body()
                return self.send(200, {"styles": ["oil", "ink"]})
            m = re.fullmatch(r"/v1/render/([^/]+)/cancel", url.path)
            if m and m.group(1) in RENDERS:
                RENDERS[m.group(1)]["state"] = "cancelled"
                STATE["cancelled"] = STATE.get("cancelled", 0) + 1
                return self.send(200, {"id": m.group(1), "state": "cancelled"})
            if url.path == "/v1/mesh":
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n)
                return self.send(200, {"bytes": len(data), "has_glb_name": b'filename="' in data, "content_type": self.headers.get("Content-Type", "")[:30]})
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


def widget(rng: str) -> dict:
    STATE["widget_calls"] = STATE.get("widget_calls", 0) + 1
    if os.environ.get("FAKE_BAD_WIDGET"):
        return {"series": [{"name": "Requests", "values": [1, "x"]}]}
    n, step = (24, 3600) if rng == "24h" else (7, 86400)
    end = int(time.time()) // step * step
    return {"unit": "requests", "t": [end - (n - 1 - i) * step for i in range(n)],
            "series": [{"name": "Requests", "values": [None] * (n - 1) + [STATE["requests"]]},
                       {"name": "Calls", "values": [STATE["widget_calls"]] * n, "axis": "right"}]}


def jobs() -> list[dict]:
    out = []
    for j in JOBS.values():
        p = min(1.0, (time.time() - j["start"]) / j["seconds"])
        job = {"id": j["id"], "label": j["label"], "progress": round(p, 3), "state": "done" if p >= 1 else "running"}
        if j["label"].startswith("live") and p < 1:     # plan 44.2: any job may carry live progress
            job["live"] = {"stage": "sampling", "preview": {"url": f"/v1/jobs/{j['id']}/preview", "seq": int(p * 10)}}
        out.append(job)
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
    if MODE == "tools" and not os.environ.get("FAKE_NO_TOOLS_REV"):
        s["tools_rev"] = "2" if STATE["doodle"] else "1"    # plan 51.1
    if os.environ.get("FAKE_TOOLS_OFF"):                 # capability-enablement 1.6: tools the mod says are off
        s["tools_off"] = json.loads(os.environ["FAKE_TOOLS_OFF"])
    if MODE == "mem":
        s["memory_estimate_gb"] = float(os.environ.get("FAKE_ESTIMATE_GB") or round(int(os.environ.get("FAKE_MEM_MB", "64")) / 1024, 3))
    return s


def main() -> None:
    if MODE not in {"ok", "slow", "crash", "mem", "tools", "perms", "ws", "engine"}:
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
