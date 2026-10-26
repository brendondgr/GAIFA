"""The hub's watch over the submodule mods (plan mod-repos 3.3): `/api/repos`, alerts raised and cleared
per problem, `[repos] notify`, `fetch_every_h`, an update through the route with its progress and its
rollback, and the 409s. A GAIFA-like project on throwaway repositories, the hub app over ASGI."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from utils import config
from utils.backends.subprocess import SubprocessBackend
from utils.server import Options, create_app
from utils.tests.conftest import FAKE_MODS, free_port
from utils.tests.repos.gitfix import ENV, adopted, commit, g, upstream_commit


def manifest() -> str:
    return (f'id = "mo"\nname = "Mo"\n\n[run]\ncommand = ["python3", "{FAKE_MODS / "_fakemod.py"}", "ok"]\n'
            f'port = {free_port()}\nhealth = "/health"\nrestart = "no"\n')


@pytest.fixture
def project(tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    root, mod, bare = adopted(tmp_path, manifest(), sid="mo")
    monkeypatch.setenv("GAIFA_ROOT", str(root))
    return root, mod, bare


class Hub:
    def __init__(self, root, cfg_text: str = ""):
        (root / "config.toml").write_text(cfg_text)
        cfg = config.load(root / "config.toml")
        self.app = create_app(config.build_paths(cfg, root), cfg, backend=SubprocessBackend(),
                              options=Options(port=7000, autostart=False, extra_hosts=("hub",)))

    async def __aenter__(self):
        self._ctx = self.app.router.lifespan_context(self.app)
        await self._ctx.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url="http://hub")
        self.hub = self.app.state.hub
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()
        await self._ctx.__aexit__(*exc)

    def alerts(self):
        return {a["id"]: a for a in self.hub.alerts.list() if a["id"].startswith("repos.")}

    async def wait_update(self, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            body = (await self.client.get("/api/repos")).json()
            if body["update"] and not body["update"]["running"]:
                return body
            assert time.monotonic() < deadline, body["update"]
            await asyncio.sleep(0.05)


async def test_get_repos(project):
    root, *_ = project
    async with Hub(root) as h:
        body = (await h.client.get("/api/repos")).json()
    [m] = body["repos"]
    assert m["id"] == "mo" and m["initialized"] and m["checkout_vs_pin"] == "same" and m["problems"] == []
    assert body["settings"] == {"fetch_every_h": 24, "notify": "warnings", "check_on_start": True}
    assert body["update"] is None and "repos" in h.hub.live_areas


async def test_alerts_follow_the_problems(project):
    root, mod, _ = project
    async with Hub(root) as h:
        assert h.alerts() == {}
        (mod / "service.toml").write_text(manifest() + "# edited\n")
        await h.client.get("/api/repos", params={"refresh": 1})
        a = h.alerts()["repos.mo.dirty"]
        assert a["level"] == "warn" and "Fix: commit them in services/mo" in a["text"] and a["service"] == "mo"
        assert a["action"]["route"] == "#/settings/services/repositories"
        g(mod, "checkout", "--", "service.toml")
        await h.client.get("/api/repos", params={"refresh": 1})
        assert h.alerts() == {}


async def test_notify_levels(project, tmp_path):
    root, _, bare = project
    upstream_commit(tmp_path, bare, "u1")
    async with Hub(root) as h:                                   # warnings: an update is no alert…
        await h.client.post("/api/repos/fetch")
        assert h.alerts() == {}
        acts = [a["text"] for a in h.hub.activity._recent]
        assert any("mo: 1 new commit on main" in t for t in acts)   # …but it's in the activity log, once
    async with Hub(root, '[repos]\nnotify = "all"\n') as h:
        assert h.alerts()["repos.mo.updates_available"]["level"] == "warn"
    async with Hub(root, '[repos]\nnotify = "off"\n') as h:
        assert h.alerts() == {}


async def test_fetch_every_h(project):
    root, *_ = project
    async with Hub(root, '[repos]\nfetch_every_h = 0\n') as h:
        assert not h.hub.repos.due()                             # 0: never contacts GitHub
    async with Hub(root) as h:
        assert h.hub.repos.due()                                 # never fetched
        await h.client.post("/api/repos/fetch", params={"id": "mo"})
        assert not h.hub.repos.due() and h.hub.repos.due(now=time.time() + 25 * 3600)


async def test_check_on_start_off(project):
    root, mod, _ = project
    (mod / "service.toml").write_text(manifest() + "# edited\n")
    async with Hub(root, '[repos]\ncheck_on_start = false\n') as h:
        assert h.alerts() == {} and h.hub.repos.states == []


async def test_update_through_the_route(project, tmp_path):
    root, mod, bare = project
    new = upstream_commit(tmp_path, bare, "u1")
    async with Hub(root) as h:
        events = h.hub.bus.subscribe()
        r = await h.client.post("/api/repos/mo/update", json={})
        assert r.status_code == 202 and r.json()["running"] is True
        body = await h.wait_update()
        res = body["update"]["result"]
        assert res["ok"] and res["new"] == new and res["staged"] and not res["rolled_back"], res["message"]
        assert [s["text"] for s in body["update"]["steps"]][:2] == ["fetching " + str(bare) + " main", f"checking out {new[:10]}"]
        assert g(root, "ls-files", "-s", "services/mo").split()[1] == new
        seen = []
        while not events.queue.empty():
            seen.append(events.queue.get_nowait())
        assert any(e.get("type") == "repos" and e.get("done") for e in seen)


async def test_update_rolls_back_on_a_failed_check(project, tmp_path):
    root, mod, bare = project
    old = g(mod, "rev-parse", "HEAD")
    upstream_commit(tmp_path, bare, "broken", {"service.toml": 'id = "mo"\n[run]\nport = "not a number"\n'})
    async with Hub(root) as h:
        await h.client.post("/api/repos/mo/update", json={})
        res = (await h.wait_update())["update"]["result"]
    assert not res["ok"] and res["rolled_back"] and "gaifa check failed" in res["message"]
    assert g(mod, "rev-parse", "HEAD") == old


async def test_refusals_are_409(project):
    root, mod, _ = project
    commit(mod, "local only", {"x.py": "x"})
    async with Hub(root) as h:
        r = await h.client.post("/api/repos/mo/update", json={})
        assert r.status_code == 409 and r.json()["code"] == "repo_refused" and r.json()["data"]["refused"] == ["unpushed"]
        assert r.headers["x-gaifa-error"] == "repo_refused"
        r = await h.client.post("/api/repos/mo/pin")
        assert r.status_code == 409 and r.json()["data"]["refused"] == ["unpushed"]
        r = await h.client.post("/api/repos/nope/update", json={})
        assert r.status_code == 404 and r.json()["code"] == "repo_not_found"


async def test_one_update_at_a_time(project, tmp_path):
    root, _, bare = project
    upstream_commit(tmp_path, bare, "u1")
    async with Hub(root) as h:
        h.hub.repos.update_job = {"id": "mo", "running": True, "steps": [], "result": None, "started": 0}
        r = await h.client.post("/api/repos/mo/update", json={})
        assert r.status_code == 409 and r.json()["code"] == "repo_update_running"


async def test_pin_through_the_route(project):
    root, mod, _ = project
    commit(mod, "local", {"x.py": "x"})
    g(mod, "push", "-q", "origin", "main")
    async with Hub(root) as h:
        r = await h.client.post("/api/repos/mo/pin")
        assert r.status_code == 200 and r.json()["staged"] and r.json()["new"] == g(mod, "rev-parse", "HEAD")
        m = (await h.client.get("/api/repos")).json()["repos"][0]
        assert m["staged_pin"] == g(mod, "rev-parse", "HEAD")


async def test_a_project_without_submodules(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    (root / "services").mkdir(parents=True)
    monkeypatch.setenv("GAIFA_ROOT", str(root))
    async with Hub(root) as h:
        body = (await h.client.get("/api/repos")).json()
    assert body["repos"] == [] and body["last_fetch_ts"] is None
