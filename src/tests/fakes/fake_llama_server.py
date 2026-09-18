"""A stand-in for llama-server: same argv, same HTTP shapes, no model.

- ``/health`` answers 503 while "loading" (FAKE_LOAD_S, default 0.3 s), then 200.
- A ``--model`` path containing "fail" logs a load error and exits 1.
- Router mode (``--models-preset``) serves ``/models`` and ``/models/load|unload``.
- ``/v1/chat/completions`` streams a short reply as OpenAI SSE chunks.
"""

from __future__ import annotations

import configparser
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def arg(name: str, default: str | None = None) -> str | None:
    argv = sys.argv[1:]
    return argv[argv.index(name) + 1] if name in argv else default


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


PORT = int(arg("--port", "8080"))
ALIASES = (arg("--alias") or "fake").split(",")
MODEL = arg("--model")
PRESET = arg("--models-preset")
LOAD_S = float(os.environ.get("FAKE_LOAD_S", "0.3"))
STATE = {"ready": False, "loaded": []}
ROUTER_MODELS: list[str] = []
if PRESET:
    cp = configparser.ConfigParser()
    cp.read_string("[__top__]\n" + open(PRESET).read())
    ROUTER_MODELS = [s for s in cp.sections() if s != "__top__"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            if STATE["ready"]:
                return self._json(200, {"status": "ok"})
            return self._json(503, {"error": {"message": "Loading model"}})
        if self.path == "/v1/models":
            ids = ROUTER_MODELS or ALIASES[:1]
            return self._json(200, {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
        if self.path == "/models" and PRESET:
            return self._json(200, {"data": [
                {"id": m, "status": {"value": "loaded" if m in STATE["loaded"] else "unloaded"}}
                for m in ROUTER_MODELS]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self.path in ("/models/load", "/models/unload") and PRESET:
            m = body.get("model")
            if m not in ROUTER_MODELS:
                return self._json(400, {"error": {"message": f"unknown model {m}"}})
            if self.path.endswith("load") and not self.path.endswith("unload"):
                STATE["loaded"] = [m]
            elif m in STATE["loaded"]:
                STATE["loaded"].remove(m)
            say(f"srv  {self.path}: {m}")
            return self._json(200, {"success": True})
        if self.path == "/v1/chat/completions":
            words = ["Hello", " from", " the", " fake", " server."]
            if not body.get("stream"):
                return self._json(200, {"choices": [{"message": {"role": "assistant", "content": "".join(words)}}],
                                        "usage": {"prompt_tokens": 5, "completion_tokens": len(words)}})
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for w in words:
                chunk = {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": w}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.01)
            final = {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 5, "completion_tokens": len(words)}}
            self.wfile.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode())
            return
        self._json(404, {"error": {"message": "not found"}})


def main() -> None:
    say(f"main: fake llama-server starting on port {PORT}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if MODEL:
        say(f"srv  load_model: loading model '{MODEL}'")
    time.sleep(LOAD_S)
    if MODEL and "fail" in os.path.basename(MODEL):
        say("ggml_vulkan: failed to allocate buffer: out of device memory")
        say("srv  load_model: failed to load model")
        sys.exit(1)
    STATE["ready"] = True
    say(f"main: server is listening on http://127.0.0.1:{PORT}")
    threading.Event().wait()


if __name__ == "__main__":
    main()
