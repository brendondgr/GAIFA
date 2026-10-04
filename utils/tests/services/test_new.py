"""2.8: `aihub new`, the _template mod, and rescan."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import httpx
import pytest

from utils import manifest
from utils.tests.conftest import REPO, free_port, wait_for
from utils.tests.services.conftest import until

AIHUB = REPO / "bin" / "aihub"
HAVE_UV = shutil.which("uv") is not None or (Path.home() / ".local/bin/uv").exists()


def run(*args, root: Path, url: str = "http://127.0.0.1:1", timeout: float = 180):
    env = {**os.environ, "AIHUB_ROOT": str(root), "AIHUB_URL": url, "PATH": f"{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}
    return subprocess.run([str(AIHUB), *args], capture_output=True, text=True, timeout=timeout, env=env)


@pytest.fixture
def ports(root):
    """A private port range for new mods, so tests never collide with real ones."""
    lo = free_port()
    (root / "config.toml").write_text(f"[ports]\nnew_mods = [{lo}, {lo + 30}]\n")
    return lo


def test_new_fills_the_template(root, ports):
    r = run("new", "hello-world", "--no-install", root=root)
    assert r.returncode == 0, r.stderr
    assert f"created services/hello-world (Hello World, port {ports})" in r.stdout
    assert "AIHub isn't running" in r.stdout
    d = root / "services" / "hello-world"
    for path in d.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert not any(t in text for t in ("__ID__", "__NAME__", "__PORT__")), path
    mod = manifest.parse(d)
    assert mod.ok, mod.errors
    m = mod.manifest
    assert (m.id, m.name, m.run.port, m.ui.page, m.ui.widgets[0].id) == ("hello-world", "Hello World", ports, "ui/page.js", "calls")
    assert (d / "install.sh").stat().st_mode & 0o111
    assert not (d / ".venv").exists()


def test_new_picks_the_next_free_port(root, ports):
    assert run("new", "first", "--no-install", root=root).returncode == 0
    with socket.socket() as s:  # something else listens on the next one
        s.bind(("127.0.0.1", ports + 1))
        s.listen()
        r = run("new", "second", "--no-install", root=root)
    assert r.returncode == 0 and f"port {ports + 2}" in r.stdout


@pytest.mark.parametrize(
    "args, error",
    [
        (["new", "Bad_Id"], "isn't a valid mod id"),
        (["new", "x"], "isn't a valid mod id"),
        (["new", "_template"], "isn't a valid mod id"),
        (["new", "ok-id", "--name", 'say "hi"'], "--name must be"),
        (["new", "ok-id", "--port", "70000"], "is not a port"),
    ],
)
def test_new_refuses_bad_input(root, ports, args, error):
    r = run(*args, "--no-install", root=root)
    assert r.returncode == 2 and error in r.stderr
    assert not (root / "services" / "ok-id").exists()


def test_new_refuses_existing_folder_and_taken_ports(root, ports):
    assert run("new", "taken", "--no-install", root=root).returncode == 0
    r = run("new", "taken", "--no-install", root=root)
    assert r.returncode == 2 and "services/taken already exists" in r.stderr
    r = run("new", "other", "--port", str(ports), "--no-install", root=root)
    assert r.returncode == 2 and f"port {ports} is already used by taken" in r.stderr
    with socket.socket() as s:
        s.bind(("127.0.0.1", ports + 5))
        s.listen()
        r = run("new", "other", "--port", str(ports + 5), "--no-install", root=root)
    assert r.returncode == 2 and "in use by another program" in r.stderr


@pytest.mark.skipif(not HAVE_UV, reason="uv is needed to install the template's venv")
def test_template_mod_end_to_end(root, ports, hub_process):
    """aihub new against a running hub: installed, picked up by rescan, started, and usable through the proxy."""
    url = hub_process.url
    r = run("new", "hello", root=root, url=url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "installed hello into .venv" in r.stdout
    assert "AIHub picked it up: hello is ready" in r.stdout
    with httpx.Client(base_url=url, timeout=10) as c:
        assert c.get("/api/s/hello/v1/hello", params={"name": "you"}).json() == {"message": "Hello, you!"}
        ops = {o["id"]: o for o in c.get("/api/services/hello/operations").json()}
        assert {"get_health", "get_v1_status", "get_v1_hello", "post_v1_echo", "post_v1_note", "get_v1_widgets_calls"} <= set(ops)
        assert ops["get_v1_hello"]["tool"] == {"name": "hello", "confirm": False}
        assert ops["post_v1_note"]["body"]["schema"]["required"] == ["text"]
        r = c.post("/api/s/hello/v1/note", json={"text": "Remember the milk", "title": "Milk"})
        assert r.status_code == 201
        out = Path(r.json()["path"])
        assert out.parent.parent == root / "outputs" / "hello" and out.parent.name == datetime.date.today().isoformat()
        assert out.read_text() == "Remember the milk"
        assert json.loads(out.with_name(out.name + ".json").read_text())["title"] == "Milk"
        w = c.get("/api/s/hello/v1/widgets/calls", params={"range": "24h"}).json()
        assert len(w["t"]) == 24 and w["series"][0]["name"] == "Calls"
        d = c.get("/api/services/hello").json()
        assert d["has_page"] and d["has_outputs"] and d["state"] == "ready"
        wait_for(url + "/api/services/hello", ok=lambda r: [s["label"] for s in r.json()["stats"]] == ["Calls", "Notes today"])


async def test_rescan_adds_changes_and_removes(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    assert list(mgr.services) == ["fake-ok"]
    rig.add("fake-ok", as_id="newcomer")
    r = await mgr.rescan(autostart=True)
    assert r == {"added": ["newcomer"], "removed": [], "changed": []}
    await until(lambda: mgr.get("newcomer").state == "ready")
    assert {"type": "resync"} in rig.events
    # Edit a manifest: applies at the next start
    toml = rig.services / "newcomer" / "service.toml"
    toml.write_text(toml.read_text().replace('name = "Fake OK"', 'name = "Renamed"'))
    r = await mgr.rescan()
    assert r["changed"] == ["newcomer"] and mgr.get("newcomer").mod.name == "Renamed"
    assert mgr.get("newcomer").state == "ready"
    # Remove a running mod's folder: it is stopped and dropped
    shutil.rmtree(rig.services / "newcomer")
    r = await mgr.rescan()
    assert r["removed"] == ["newcomer"] and "newcomer" not in mgr.services
    assert await rig.backend.list_ours() == []


async def test_rescan_fixes_and_breaks_manifests(rig):
    d = rig.add("fake-ok")
    good = (d / "service.toml").read_text()
    (d / "service.toml").write_text("broken = [")
    mgr = await rig.manager()
    assert mgr.get("fake-ok").state == "failed"
    (d / "service.toml").write_text(good)
    await mgr.rescan(autostart=False)
    assert mgr.get("fake-ok").state == "stopped" and mgr.get("fake-ok").errors == []
    (d / "service.toml").write_text("broken = [")
    await mgr.rescan()
    assert mgr.get("fake-ok").state == "failed" and "not valid TOML" in mgr.get("fake-ok").errors[0]


def test_cli_rescan_and_install(root, ports, hub_process):
    r = run("rescan", root=root, url=hub_process.url)
    assert (r.returncode, r.stdout) == (0, "no changes\n")
    r = run("install", "nope", root=root)
    assert r.returncode == 2 and "no mod folder services/nope" in r.stderr
