"""A local test server that plays SearXNG and the web sites, and a fake resolver: `site.test` and
`other.test` are this server (treated as public), the other names resolve to the address classes
the fetch rules refuse."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

import safety
import server

Route = tuple[int, dict[str, str], bytes] | Callable[["Handler"], None]


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, Route] = {}
    seen: list[dict[str, Any]] = []

    def log_message(self, *a: object) -> None:
        pass

    def do_GET(self) -> None:
        u = urlsplit(self.path)
        host = (self.headers.get("Host") or "").split(":")[0]
        self.seen.append({"host": host, "path": u.path, "query": parse_qs(u.query), "ua": self.headers.get("User-Agent")})
        route = self.routes.get(f"{host}{u.path}") or self.routes.get(u.path)
        if route is None:
            self.reply(404, {"Content-Type": "text/plain"}, b"not found")
        elif callable(route):
            route(self)
        else:
            self.reply(*route)

    def reply(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site():
    """{port, routes, seen}: add routes as "path" or "host/path" → (status, headers, body) or a callable."""
    Handler.routes, Handler.seen = {}, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield type("Site", (), {"port": srv.server_address[1], "routes": Handler.routes, "seen": Handler.seen})
    srv.shutdown()
    srv.server_close()


NAMES = {
    "site.test": ["127.0.0.1"],
    "other.test": ["127.0.0.1"],
    "private.test": ["10.0.0.5"],
    "lan.test": ["192.168.1.20"],
    "metadata.test": ["169.254.169.254"],
    "loop6.test": ["::1"],
    "mapped.test": ["::ffff:127.0.0.1"],
    "rebind.test": ["93.184.216.34", "127.0.0.2"],
}


def make_guard(port: int) -> safety.Guard:
    async def resolve(host: str, p: int) -> list[str]:
        if host in NAMES:
            return NAMES[host]
        if host[0].isdigit() or ":" in host:
            return [host]
        raise OSError(f"unknown test name {host}")
    return safety.Guard(resolve, public={("127.0.0.1", port)})


@pytest.fixture
def make_client(site, tmp_path: Path):
    """A TestClient for the web mod, with SearXNG at `searxng` (default: the test server)."""
    clients = []

    def make(searxng: str | None = None) -> TestClient:
        app = server.create_app(searxng or f"http://127.0.0.1:{site.port}", tmp_path / "outputs", make_guard(site.port))
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


def html(title: str, body: str) -> tuple[int, dict[str, str], bytes]:
    page = f"<!doctype html><html><head><title>{title}</title></head><body><nav>Home | About</nav><article>{body}</article><footer>© footer</footer><script>var x = 1;</script></body></html>"
    return 200, {"Content-Type": "text/html; charset=utf-8"}, page.encode()


def searx(results: list[dict[str, Any]], **extra: Any) -> tuple[int, dict[str, str], bytes]:
    return 200, {"Content-Type": "application/json"}, json.dumps({"query": "q", "results": results, "answers": [], "suggestions": [],
                                                                  "unresponsive_engines": [], **extra}).encode()


def slow(seconds: float) -> Callable[[Handler], None]:
    def route(h: Handler) -> None:
        time.sleep(seconds)
        h.reply(*html("Slow", "<p>late</p>"))
    return route
