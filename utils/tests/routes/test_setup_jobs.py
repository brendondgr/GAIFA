"""capability-enablement 3.1: setup as a hub job, with a fake `gaifa`: the plan, a job's events, report, rescan and start;
needs_you; busy; cancel; a mod's test; refused from the network."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest

from utils import config
from utils.lan import limits
from utils.tests.conftest import FAKE_MODS, free_port
from utils.tests.services.conftest import until

PLAN = {"stage": "plan", "setups": ["fresh"], "mods": ["fresh"], "disk_gb": 0.1, "images": {}, "steps": [
    {"id": "fresh/1", "setup": "fresh", "mod": "fresh", "run": "gaifa install fresh", "what": "makes .venv/ (70 MB)"}],
    "questions": [], "suggestions": [], "host": [], "checks": [], "variants": [], "unavailable": [], "smokes": []}


class FakeGaifa:
    """Plays `bin/gaifa`: records each call; `setup` makes the mod's venv unless told to stop or ask."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.rc = 0
        self.hold: asyncio.Event | None = None
        self.answers: list[dict] = []

    async def __call__(self, args, root: Path, on_line, on_proc):
        self.calls.append(args)
        if args[:2] == ["setup", "--plan"]:
            return 0, json.dumps(PLAN)
        if args[0] == "__smoke__":
            return (0, "spoke one sentence\n") if args[1] == "fresh" else (1, "boom\n")
        f = Path(args[args.index("--answers") + 1])
        self.answers.append(json.loads(f.read_text()))
        assert oct(f.stat().st_mode & 0o777) == "0o600"
        on_line("==> fresh: makes .venv/")
        if self.hold is not None:
            await self.hold.wait()
        if self.rc == 2:
            return 2, json.dumps({"stage": "report", "questions": [{"id": "fresh/licence", "text": "Accept the licence?"}]})
        if self.rc:
            return 1, json.dumps({"stage": "report", "failed": [{"setup": "fresh", "step": "fresh/1", "run": "gaifa install fresh"}]})
        venv = root / "services" / "fresh" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").symlink_to(shutil.which("python3"))
        on_line("==> fresh: check passed")
        return 0, json.dumps({"stage": "report", "done": ["fresh"], "failed": []})


def _fresh(root: Path) -> None:
    for helper in FAKE_MODS.glob("_*.py"):
        shutil.copy(helper, root / "services" / helper.name)
    d = root / "services" / "fresh"
    shutil.copytree(FAKE_MODS / "fake-ok", d)
    text = (d / "service.toml").read_text().replace('id = "fake-ok"', 'id = "fresh"')
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", text)
    text = text.replace('command = ["python3", "../_fakemod.py", "ok"]', 'command = [".venv/bin/python", "../_fakemod.py", "ok"]')
    (d / "service.toml").write_text(text)
    (d / "setup").mkdir()
    (d / "setup" / "fresh.md").write_text('<!-- gaifa-setup\nid = "fresh"\ntitle = "Fresh"\nsummary = "Fresh: fake"\n'
                                          'recommended = true\nsmoke = "echo hi"\n-->\n# Fresh\n')


@pytest.fixture
async def hub(root, make_app):
    _fresh(root)
    fake = FakeGaifa()
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=False, setup_runner=fake)
    events: list[dict] = []
    async with app.router.lifespan_context(app):
        sub = app.state.hub.bus.subscribe()

        async def pump():
            async for ev in sub:
                events.append(ev)
        t = asyncio.create_task(pump())
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            yield app, c, fake, events
        t.cancel()


async def test_the_plan_says_what_will_happen(hub):
    app, c, fake, _ = hub
    r = await c.get("/api/setup/plan", params={"ids": "fresh"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["steps"][0]["what"] == "makes .venv/ (70 MB)" and fake.calls[0] == ["setup", "--plan", "--json", "fresh"]
    about = p["about"][0]
    assert about["id"] == "fresh" and about["folder"] == "services/fresh" and about["recommended"] is True and about["installed"] is False
    assert (await c.get("/api/setup/plan", params={"ids": "../x"})).status_code == 422


async def test_a_job_runs_reports_rescans_and_starts(hub, root):
    app, c, fake, events = hub
    r = await c.post("/api/setup", json={"ids": ["fresh"], "answers": {"models": {"fresh": ["none"]}}})
    assert r.status_code == 202 and r.json()["state"] == "running"
    await until(lambda: app.state.hub.setup.job["state"] != "running", timeout=30)
    job = (await c.get("/api/setup/job")).json()["job"]
    assert job["state"] == "done" and "==> fresh: check passed" in job["lines"], job
    assert job["report"]["done"] == ["fresh"] and job["started"] == [{"id": "fresh", "state": "ready"}]
    assert fake.answers == [{"yes": True, "models": {"fresh": ["none"]}}]
    assert not list((root / "data" / "state" / "setup").glob("answers-*.json"))      # removed after
    states = [e["job"]["state"] for e in events if e["type"] == "setup"]
    assert states[0] == "running" and states[-1] == "done"
    svc = (await c.get("/api/services/fresh")).json()
    assert svc["availability"]["status"] == "on"
    await app.state.hub.services.stop("fresh", wait=True)


async def test_needs_you_and_failed(hub):
    app, c, fake, _ = hub
    fake.rc = 2
    await c.post("/api/setup", json={"ids": ["fresh"]})
    await until(lambda: app.state.hub.setup.job["state"] != "running", timeout=10)
    job = (await c.get("/api/setup/job")).json()["job"]
    assert job["state"] == "needs_you" and job["needs"]["questions"][0]["id"] == "fresh/licence"
    fake.rc = 1
    await c.post("/api/setup", json={"ids": ["fresh"]})
    await until(lambda: app.state.hub.setup.job["state"] != "running", timeout=10)
    job = (await c.get("/api/setup/job")).json()["job"]
    assert job["state"] == "failed" and job["error"] == "fresh: fresh/1 failed (gaifa install fresh)"


async def test_one_at_a_time_and_cancel(hub):
    app, c, fake, _ = hub
    fake.hold = asyncio.Event()
    await c.post("/api/setup", json={"ids": ["fresh"]})
    r = await c.post("/api/setup", json={"ids": ["fresh"]})
    assert r.status_code == 409 and r.json()["code"] == "setup_busy"
    r = await c.delete("/api/setup/job")
    assert r.json()["job"]["state"] == "cancelled"
    assert (await c.get("/api/setup/job")).json()["job"]["state"] == "cancelled"


async def test_a_mods_test(hub):
    app, c, fake, _ = hub
    r = await c.post("/api/setup/test", params={"id": "fresh"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["passed"] is True and t["run"] == "echo hi" and t["log"] == "data/state/setup/logs/fresh/test.log"
    assert fake.calls[-1] == ["__smoke__", "fresh", "echo hi"]
    r = await c.post("/api/setup/test", params={"id": "nosuch"})
    assert r.status_code == 404 and r.json()["code"] == "no_test"


def test_refused_from_the_network():
    assert "on the GAIFA machine" in limits.refused("POST", "/api/setup", {"ids": ["web"]})
    assert limits.refused("DELETE", "/api/setup/job") and limits.refused("POST", "/api/setup/test")
    assert limits.refused("GET", "/api/setup/plan") is None
