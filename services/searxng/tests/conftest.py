"""A fake SearXNG and a fake container runtime.

The fake SearXNG reads the settings file each time the fake runtime "restarts" it: engines turned
off in it are off in `/config`, `search.formats` without json makes `format=json` a 403, and a
`default_lang` of `xx` makes it fail to come up (so a change has to be rolled back). The engine
`stubborn` never turns off (a change that doesn't take effect).
"""

from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from ruamel.yaml import YAML

from containers import BACKUP_RE, Container, backup_name

SETTINGS = """\
use_default_settings: true

server:
  secret_key: "not-a-secret"   # the test's own
  limiter: false

search:
  safe_search: 0
  formats:
    - html
    - json

engines:
  - name: google
    engine: google
    disabled: false
"""

ENGINES = [("google", ["general"]), ("bing", ["general"]), ("duckduckgo", ["general"]), ("brave", ["general"]),
           ("wikipedia", ["general"]), ("github", ["it"]), ("stubborn", ["general"]), ("arxiv", ["science"])]
DEFAULT_OFF = {"arxiv"}


class FakeSearx:
    def __init__(self, settings_file: Path) -> None:
        self.file = settings_file
        self.queries: list[dict[str, Any]] = []
        self.reload()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        srv.daemon_threads = True
        self.srv = srv
        self.url = f"http://127.0.0.1:{srv.server_address[1]}"
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def reload(self) -> None:
        doc = YAML(typ="safe").load(self.file.read_text()) or {}
        search = doc.get("search") or {}
        self.up = search.get("default_lang") != "xx"
        self.safe = search.get("safe_search", 0)
        self.json = "json" in (search.get("formats") or ["html"])
        over = {e["name"]: e for e in doc.get("engines") or [] if isinstance(e, dict)}
        self.engines = []
        for name, cats in ENGINES:
            o = over.get(name, {})
            off = o.get("disabled", name in DEFAULT_OFF)
            if name == "stubborn":
                off = False
            self.engines.append({"name": name, "enabled": not off, "categories": cats, "shortcut": name[:2],
                                 "timeout": float(o.get("timeout", 3.0))})

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def send(self, status: int, body: Any, ctype: str = "application/json") -> None:
                data = json.dumps(body).encode() if ctype == "application/json" else body.encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if not fake.up:
                    return self.send(502, "down", "text/plain")
                if u.path == "/healthz":
                    return self.send(200, "OK", "text/plain")
                if u.path == "/config":
                    return self.send(200, {"engines": fake.engines, "safe_search": fake.safe, "version": "fake"})
                if u.path == "/stats/errors":
                    return self.send(200, {"brave": [{"exception_classname": "searx.exceptions.SearxEngineTooManyRequestsException",
                                                      "log_parameters": ["Too many request (suspended_time=180)"], "percentage": 100}]})
                if u.path == "/search":
                    fake.queries.append(q)
                    if q.get("format") == "json":
                        if not fake.json:
                            return self.send(403, "Forbidden", "text/html")
                        return self.send(200, {"query": q.get("q"), "results": [{"url": "https://e.org/", "title": "t"}],
                                               "unresponsive_engines": [["brave", "too many requests"]]})
                    return self.send(200, "<html>results</html>", "text/html")
                return self.send(404, "no", "text/plain")
        return H


class FakeRuntime:
    """The container runtime over a folder: the settings file, its backups, and a restart that makes
    the fake SearXNG read the file again."""

    def __init__(self, folder: Path, searx: FakeSearx | None = None, running: bool = True) -> None:
        self.folder, self.searx, self.running = folder, searx, running
        self.restarts = 0
        self.log: list[str] = []

    @property
    def file(self) -> Path:
        return self.folder / "settings.yml"

    async def find(self) -> Container | None:
        return Container("fake", "abc123", "searxng", "searxng/searxng:latest", "running" if self.running else "exited",
                         settings_host=str(self.file), compose_dir=str(self.folder), compose_service="searxng",
                         url=self.searx.url if self.searx else None)

    async def read(self, c: Container) -> str:
        return self.file.read_text()

    async def backup(self, c: Container) -> str:
        name = backup_name()
        n = 2
        while (self.folder / name).exists():
            name = f"{backup_name()}-{n}"
            n += 1
        shutil.copy2(self.file, self.folder / name)
        self.log.append(f"backup {name}")
        return name

    async def write(self, c: Container, text: str) -> None:
        self.file.write_text(text)
        self.log.append("write")

    async def restore(self, c: Container, backup: str) -> None:
        self.file.write_text((self.folder / backup).read_text())
        self.log.append(f"restore {backup}")

    def backups(self, c: Container) -> list[str]:
        return sorted((p.name for p in self.folder.iterdir() if BACKUP_RE.match(p.name)), reverse=True)

    async def restart(self, c: Container) -> None:
        self.restarts += 1
        self.log.append("restart")
        if self.searx:
            self.searx.reload()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    d = tmp_path / "searxng"
    d.mkdir()
    (d / "settings.yml").write_text(SETTINGS)
    return d


@pytest.fixture
def fake(folder: Path):
    s = FakeSearx(folder / "settings.yml")
    yield s
    s.close()


@pytest.fixture
def runtime(folder: Path, fake: FakeSearx) -> FakeRuntime:
    return FakeRuntime(folder, fake)


@pytest.fixture
def client(runtime: FakeRuntime, fake: FakeSearx):
    from fastapi.testclient import TestClient

    import server
    app = server.create_app(runtime, env_url=fake.url, watch_s=3600, query_s=0.001, ready_s=2)
    with TestClient(app) as c:
        yield c
