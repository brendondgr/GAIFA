"""The web UI as served by the daemon, and UI ↔ API route consistency."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from lcpp.daemon.app import create_app
from lcpp.paths import REPO_ROOT

API_JS = REPO_ROOT / "web/assets/api.js"
CALL_RE = re.compile(r"req\('(GET|POST|PUT|DELETE)',\s*[`'](/api/[^`'?]*)")
SSE_RE = re.compile(r"new EventSource\(base \+ `(/api/[^`?]*)`")


def ui_calls() -> set[tuple[str, str]]:
    src = API_JS.read_text()
    calls = {(m, p) for m, p in CALL_RE.findall(src)}
    calls |= {("GET", p) for p in SSE_RE.findall(src)}
    calls.add(("POST", "/api/chat"))  # issued with fetch() directly (streaming)
    return {(m, re.sub(r"\$\{[^}]+\}", "X", p)) for m, p in calls}


def route_regex(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")


def test_every_ui_call_has_a_route(fake_home):
    # The OpenAPI schema is the stable list of routes (included routers are
    # not flattened into app.routes in every FastAPI version).
    spec = create_app(fake_home).openapi()
    routes = [({m.upper() for m in ops}, route_regex(path)) for path, ops in spec["paths"].items()]
    missing = [(m, p) for m, p in sorted(ui_calls())
               if not any(m in methods and rx.match(p) for methods, rx in routes)]
    assert len(ui_calls()) >= 28  # the parser still sees the whole client
    assert missing == []


def test_real_ui_is_served_live(fake_home):
    import shutil

    shutil.copytree(REPO_ROOT / "web", fake_home.root / "web")
    with TestClient(create_app(fake_home)) as c:
        index = c.get("/").text
        assert '<script src="config.js"></script>' in index
        assert c.get("/config.js").text.strip() == "window.LCPP_API_BASE = '';"
        for asset in ("assets/app.js", "assets/api.js", "assets/components.js", "assets/tokens.css"):
            assert c.get(f"/{asset}").status_code == 200, asset
        assert "typeof window.LCPP_API_BASE === 'string'" in c.get("/assets/app.js").text
