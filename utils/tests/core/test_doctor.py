"""12.4: `GET /api/doctor` and `aihub doctor`: models, manifests, paths outside the project, ports,
units, disk and offline mods."""

from __future__ import annotations

import re
import socket
from pathlib import Path

import httpx

from utils import doctor
from utils.tests.conftest import free_port
from utils.tests.models.conftest import Models


def test_outside_paths_sorts_each_path(tmp_path, monkeypatch):
    home = Path.home()
    monkeypatch.setattr(doctor, "STAGE_D", [Path("/run/user/1000")])
    got = doctor.outside_paths([
        ("command[0]", str(tmp_path / "services/x/.venv/bin/python")),       # inside: not listed
        ("env A", f"{tmp_path}/a:/etc/thing"),                                 # PYTHONPATH-style: one outside
        ("env B", "~/.local/bin/blender"),                                     # allowlisted
        ("env C", "/usr/bin/ffmpeg"),
        ("env D", "/run/user/1000/lcpp"),                                      # Stage D
        ("env E", "http://127.0.0.1:4000/v1"),                                 # a URL is not a path
        ("env F", "docker.io/kyuz0/image:latest"),                             # a podman image
        ("env G", "expandable_segments:True"),
    ], tmp_path)
    assert got == [("env A", "/etc/thing", "outside"), ("env B", "~/.local/bin/blender", "allowlisted"),
                   ("env C", "/usr/bin/ffmpeg", "allowlisted"), ("env D", "/run/user/1000/lcpp", "stage-d")]
    assert home  # ~ expands against the real home


def _mod(services: Path, mod: str, extra_env: str = "", models: str = "") -> int:
    toml = services / mod / "service.toml"
    port = free_port()
    text = re.sub(r"(?m)^port = \d+", f"port = {port}", toml.read_text())
    if extra_env:
        text = text.replace('FAKE_VERBOSE = "1" }', f'FAKE_VERBOSE = "1", {extra_env} }}')
    toml.write_text(text + models)
    return port


async def test_doctor_reports_each_area(services_dir, root, make_app):
    services = services_dir("fake-ok", "fake-mem")
    _mod(services, "fake-ok", 'ELSEWHERE = "/etc/aihub-doctor-test", HF_HUB_OFFLINE = "1"', '\n[models]\ndirs = ["tts"]\n')
    busy = _mod(services, "fake-mem")
    (services / "broken").mkdir()
    (services / "broken" / "service.toml").write_text('id = "broken"\n')
    m = Models(root)
    m.put("tts/voice.safetensors", 64)
    m.write({"voice": {"kind": "tts", "path": "tts/voice.safetensors", "files": [m.file("tts/voice.safetensors")]},
             "gone": {"kind": "tts", "path": "tts/gone.safetensors", "files": [m.file("tts/gone.safetensors")]}})
    with socket.socket() as s:                                     # something else holds fake-mem's port
        s.bind(("127.0.0.1", busy))
        s.listen()
        app = make_app(port=7000, autostart=False)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
                r = (await c.get("/api/doctor")).json()
    by = {(x["area"], x["title"]): x for x in r["checks"]}
    titles = [t for _, t in by]
    assert r["ok"] is False and r["counts"]["fail"] >= 3
    assert by[("models", "model gone: missing")]["level"] == "fail"
    assert by[("manifests", "broken: invalid")]["level"] == "fail"
    out = by[("paths", "fake-ok: 1 path(s) outside the project")]
    assert out["level"] == "warn" and "ELSEWHERE: /etc/aihub-doctor-test" in out["detail"]
    assert by[("paths", "fake-mem: everything inside the project")]["level"] == "ok"
    taken = by[("ports", f"fake-mem: port {busy} is taken while the mod is stopped")]
    assert taken["level"] == "fail" and "pid" in taken["detail"]
    assert by[("offline", "fake-ok: runs offline without 1 model(s)")]["detail"] == "gone (missing)"
    assert any(t.startswith("logs: in the systemd journal") for t in titles)
    assert any(a == "disk" for a, _ in by)


async def test_doctor_is_clean_on_an_empty_install(client):
    r = (await client.get("/api/doctor")).json()
    assert r["counts"]["fail"] == 0 and r["ok"] is True
    assert [c for c in r["checks"] if c["area"] == "models"][0]["title"].startswith("models registry: 0 models")
