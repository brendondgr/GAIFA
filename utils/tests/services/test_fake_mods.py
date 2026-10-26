"""The fake mods behave as the plan says, so later phases can rely on them."""

import json
import re
import time
import tomllib
import wave
from io import BytesIO
from pathlib import Path

import httpx
import pytest

FAKE_MODS = Path(__file__).resolve().parents[1] / "fixtures" / "mods"
OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"
ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")


def rss_kb(pid: int) -> int:
    if not Path("/proc/self").exists():      # macOS (plan 37.5)
        import psutil

        return psutil.Process(pid).memory_info().rss // 1024
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


@pytest.mark.parametrize("folder", sorted(p.name for p in FAKE_MODS.iterdir() if p.is_dir() and not p.name.startswith("_")))
def test_manifests_follow_the_contract(folder):
    m = tomllib.loads((FAKE_MODS / folder / "service.toml").read_text())
    assert m["id"] == folder and ID_RE.fullmatch(folder)
    assert m["run"]["health"] == "/health"
    assert 5100 <= m["run"]["port"] <= 5199
    assert (FAKE_MODS / folder / m["run"]["command"][1]).resolve() == FAKE_MODS / "_fakemod.py"


def test_all_four_exist():
    assert {p.name for p in FAKE_MODS.iterdir() if p.is_dir() and not p.name.startswith("_")} == {"fake-ok", "fake-slow", "fake-crash", "fake-mem", "fake-tools", "fake-perms", "fake-ws", "fake-engine"}


@pytest.mark.parametrize("name", ["tts", "gen3d", "lcpp", "relay"])
def test_openapi_captures(name):
    spec = json.loads((OPENAPI / f"{name}.json").read_text())
    assert spec["openapi"].startswith("3.") and spec["paths"]


def test_fake_ok_routes(fake_mod):
    m = fake_mod("ok")
    assert httpx.get(m.url + "/health").json() == {"status": "ok", "mode": "ok"}
    status = httpx.get(m.url + "/v1/status").json()
    assert status["loaded"] is None and len(status["stats"]) <= 4
    assert "/v1/speech" in httpx.get(m.url + "/openapi.json").json()["paths"]

    echo = httpx.post(m.url + "/v1/echo?a=1", json={"x": [1, 2]}).json()
    assert echo["json"] == {"x": [1, 2]} and echo["query"] == {"a": ["1"]}

    r = httpx.post(m.url + "/v1/speech", json={"text": "hi"})
    assert r.headers["content-type"] == "audio/wav"
    with wave.open(BytesIO(r.content)) as w:
        assert w.getnframes() == 4000

    with httpx.stream("GET", m.url + "/v1/events") as r:
        assert r.headers["content-type"] == "text/event-stream"
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events == [{"n": 0}, {"n": 1}, {"n": 2}]

    path = Path(httpx.post(m.url + "/v1/outputs", json={"text": "Good morning!"}).json()["path"])
    assert path.parent.parent == m.outputs
    assert re.fullmatch(r"\d{6}-good-morning\.txt", path.name) and path.read_text() == "Good morning!"
    assert json.loads(path.with_name(path.name + ".json").read_text())["kind"] == "text"
    assert not list(path.parent.glob("*.part"))
    assert httpx.get(m.url + "/v1/status").json()["stats"][1]["value"] == 1


def test_fake_slow_becomes_healthy_after_3s(fake_mod):
    m = fake_mod("slow", FAKE_SLOW_S="1")
    assert httpx.get(m.url + "/health").status_code == 503
    time.sleep(1.1)
    assert httpx.get(m.url + "/health").status_code == 200


def test_fake_slow_default_is_3s(fake_mod):
    m = fake_mod("slow")
    time.sleep(2)
    assert httpx.get(m.url + "/health").status_code == 503


def test_fake_crash_exits(fake_mod):
    m = fake_mod("crash")
    assert m.proc.wait(timeout=5) == 1


def test_fake_mem_allocates_and_frees(fake_mod):
    m = fake_mod("mem", FAKE_MEM_MB="48")
    base = rss_kb(m.proc.pid)
    assert httpx.post(m.url + "/v1/load").json() == {"loaded": True, "mb": 48}
    assert rss_kb(m.proc.pid) - base > 40 * 1024
    assert httpx.get(m.url + "/v1/status").json()["loaded"] is True
    httpx.post(m.url + "/v1/unload")
    assert httpx.get(m.url + "/v1/status").json()["loaded"] is False
    assert rss_kb(m.proc.pid) - base < 8 * 1024


async def test_conftest_client(client, root):
    assert (await client.get("/api/system")).json()["paths"]["root"] == str(root.resolve())


def test_services_dir_copies_mods(services_dir):
    d = services_dir("fake-ok", "fake-mem")
    assert sorted(p.name for p in d.iterdir()) == ["_fakemod.py", "_fakepage.py", "_fakews.py", "fake-mem", "fake-ok"]
