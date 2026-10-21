"""Detection (SEARXNG_URL, the probe, the container through a fake Docker) and the watch loop (plan 26.3)."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from conftest import SETTINGS, FakeRuntime
from containers import BACKUP_RE, CliRuntime, RuntimeError_
from searx import Searx


@pytest.fixture
def dead():
    """URLs nothing answers on. Each port stays bound (not listening) until the test ends, so a
    connection is always refused: closing it at once let another process take it before the probe."""
    held: list[socket.socket] = []

    def make() -> str:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        held.append(s)
        return f"http://127.0.0.1:{s.getsockname()[1]}"

    yield make
    for s in held:
        s.close()


async def test_detect_env_probe_and_container(fake, folder, dead):
    _dead = dead
    rt = FakeRuntime(folder, fake)
    a = Searx(rt, env_url=fake.url + "/")
    assert (await a.detect())["found_by"] == "SEARXNG_URL" and a.url == fake.url
    b = Searx(rt, probes=(_dead(), fake.url))
    found = await b.detect()
    assert found["found_by"] == "probe" and found["url"] == fake.url
    assert found["settings_file"] == str(folder / "settings.yml") and found["compose_dir"] == str(folder) and found["can_adjust"]
    c = Searx(rt, probes=(_dead(),))
    assert (await c.detect())["found_by"] == "container" and c.url == fake.url
    d = Searx(FakeRuntime(folder, None), probes=(_dead(),))
    assert (await d.detect())["url"] is None
    for s in (a, b, c, d):
        await s.http.aclose()


async def test_watch_round(fake, folder):
    s = Searx(FakeRuntime(folder, fake), env_url=fake.url, query_s=0)
    await s.detect()
    await s.tick()
    assert s.health["up"] is True and s.health["ms"] >= 0
    assert s.last_query["ok"] and s.last_query["format"] == "json" and s.last_query["results"] == 1
    assert s.last_query["unresponsive"] == ["brave"]
    names = {e["name"]: e for e in s.engines}
    assert names["arxiv"]["enabled"] is False and names["brave"]["errors"][0]["percentage"] == 100
    assert len(s.history) == 1 and s.history[0]["up"]
    fake.up = False
    await s.tick()
    assert s.health["up"] is False and "502" in s.health["detail"] and s.history[-1]["up"] is False
    await s.http.aclose()


async def test_test_search_waits_for_its_interval(fake, folder):
    s = Searx(FakeRuntime(folder, fake), env_url=fake.url, query_s=3600)
    await s.detect()
    await s.tick()
    await s.tick()
    assert len(fake.queries) == 1                                 # the first round, then not for an hour
    await s.http.aclose()


def test_status_and_endpoint(client, fake):
    st = client.get("/v1/status").json()
    stats = {x["label"]: x for x in st["stats"]}
    assert stats["SearXNG"]["value"] == "up" and stats["Engines on"]["value"] == 7
    assert stats["Engines failing"]["value"] == 1 and "brave" in stats["Engines failing"]["hint"]
    assert st["found"]["container"]["name"] == "searxng"
    assert client.get("/v1/endpoint").json() == {"url": fake.url, "found_by": "SEARXNG_URL", "up": True}
    assert client.get("/health").status_code == 200


# ---- the real CLI runtime against a fake `docker` ------------------------------------------------

FAKE_DOCKER = r'''
import json, os, shutil, subprocess, sys
log = os.environ["FAKE_DOCKER_LOG"]; host = os.environ["FAKE_DOCKER_DIR"]
open(log, "a").write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
a = sys.argv[1:]
def host_path(p): return p.replace("/etc/searxng", host)
if a[0] == "ps":
    print(json.dumps({"ID": "0ther", "Image": "postgres:16", "Names": "db", "State": "running"}))
    print(json.dumps({"ID": "996a05fd5cd3", "Image": "searxng/searxng:latest", "Names": "searxng", "State": "running"}))
elif a[0] == "inspect":
    if os.environ.get("FAKE_DOCKER_GONE"):
        sys.exit("Error: No such object: " + a[1])
    print(json.dumps([{"Id": a[1] + "aaaa", "Name": "/searxng", "State": {"Status": "running"},
        "Config": {"Image": "searxng/searxng:latest", "Env": ["BIND_ADDRESS=127.0.0.1:8080", "GRANIAN_HOST=::",
                   "__SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml"],
                   "Labels": {"com.docker.compose.project.working_dir": os.environ["FAKE_COMPOSE"], "com.docker.compose.service": "searxng"}},
        "HostConfig": {"NetworkMode": "host"},
        "Mounts": [{"Type": "bind", "Source": host, "Destination": "/etc/searxng"},
                   {"Type": "volume", "Source": "/var/lib/docker/volumes/x", "Destination": "/var/cache/searxng"}]}]))
elif a[0] == "exec":
    rest = [x for x in a[1:] if x != "-i"][1:]
    if rest[0] == "cp":
        shutil.copy2(host_path(rest[2]), host_path(rest[3]))
    elif rest[:2] == ["sh", "-c"]:
        args = [host_path(x) for x in rest[3:]]
        cut = os.environ.get("FAKE_DOCKER_CUT")
        if cut and "-i" in a:       # the exec's stdin breaks off after `cut` bytes
            sys.exit(subprocess.run(["sh", "-c", rest[2], *args], input=sys.stdin.buffer.read()[:int(cut)]).returncode)
        sys.exit(subprocess.run(["sh", "-c", rest[2], *args], stdin=sys.stdin).returncode)
    elif rest[0] == "rm":
        for x in rest[1:]:
            if x not in ("-f", "--"):
                os.remove(host_path(x))
    elif rest[0] == "cat":
        sys.stdout.write(open(host_path(rest[1])).read())
elif a[0] in ("compose", "restart"):
    pass
else:
    sys.exit(f"unknown {a}")
'''


@pytest.fixture
def docker(tmp_path, folder, monkeypatch):
    script = tmp_path / "bin" / "docker"
    script.parent.mkdir()
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(FAKE_DOCKER))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    compose = tmp_path / "compose"
    compose.mkdir()
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_DIR", str(folder))
    monkeypatch.setenv("FAKE_COMPOSE", str(compose))
    return CliRuntime(str(script)), log, compose


def _calls(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()]


async def test_cli_runtime_finds_the_container(docker, folder):
    rt, log, compose = docker
    c = await rt.find()
    assert (c.name, c.image, c.state, c.runtime) == ("searxng", "searxng/searxng:latest", "running", "docker")
    assert c.settings_in == "/etc/searxng/settings.yml" and c.settings_host == str(folder / "settings.yml")
    assert c.compose_dir == str(compose) and c.compose_service == "searxng" and c.url == "http://127.0.0.1:8080"
    assert [x["args"][0] for x in _calls(log)] == ["ps", "inspect"]


async def test_cli_runtime_backup_write_restore_restart(docker, folder):
    rt, log, compose = docker
    c = await rt.find()
    assert await rt.read(c) == SETTINGS
    name = await rt.backup(c)
    assert BACKUP_RE.match(name) and (folder / name).read_text() == SETTINGS and rt.backups(c) == [name]
    again = await rt.backup(c)
    assert again == name + "-2" or again != name
    mode = os.stat(folder / "settings.yml").st_mode
    await rt.write(c, "use_default_settings: true\n")
    assert (folder / "settings.yml").read_text() == "use_default_settings: true\n"
    assert os.stat(folder / "settings.yml").st_mode == mode                          # the same mode after the rename
    await rt.restore(c, name)
    assert (folder / "settings.yml").read_text() == SETTINGS
    await rt.restart(c)
    calls = _calls(log)
    assert calls[-1]["args"] == ["compose", "restart", "searxng"] and calls[-1]["cwd"] == str(compose)
    execs = [x["args"] for x in calls if x["args"][0] == "exec"]
    assert execs[0] == ["exec", c.id, "cp", "-p", "/etc/searxng/settings.yml", f"/etc/searxng/{name}"]
    assert all("/etc/searxng/" in " ".join(e) for e in execs)                        # only the settings folder
    with pytest.raises(Exception):
        await rt.restore(c, "../../etc/passwd")


async def test_cli_runtime_without_docker():
    assert await CliRuntime("/nonexistent/docker").find() is None


async def test_cli_runtime_finds_nothing_when_the_container_goes_before_inspect(docker, monkeypatch):
    rt, log, compose = docker
    monkeypatch.setenv("FAKE_DOCKER_GONE", "1")
    assert await rt.find() is None
    assert [x["args"][0] for x in _calls(log)] == ["ps", "inspect"]


async def test_cli_runtime_write_is_all_or_nothing(docker, folder, monkeypatch):
    """A write cut short (the exec's stdin broke off) leaves settings.yml as it was: the new text goes to
    a copy that is checked, then renamed over it (it used to be truncated in place)."""
    rt, log, compose = docker
    c = await rt.find()
    f = folder / "settings.yml"
    f.chmod(0o640)
    inode = f.stat().st_ino
    new = SETTINGS.replace("safe_search: 0", "safe_search: 2")
    monkeypatch.setenv("FAKE_DOCKER_CUT", "10")
    with pytest.raises(RuntimeError_) as e:
        await rt.write(c, new)
    assert "settings.yml is unchanged" in e.value.detail
    assert f.read_text() == SETTINGS and sorted(p.name for p in folder.iterdir()) == ["settings.yml"]
    monkeypatch.delenv("FAKE_DOCKER_CUT")
    await rt.write(c, new)
    assert f.read_text() == new and f.stat().st_ino != inode and stat.S_IMODE(f.stat().st_mode) == 0o640
    assert sorted(p.name for p in folder.iterdir()) == ["settings.yml"]          # no temp file left


async def test_cli_runtime_prunes_its_own_backups_only(docker, folder):
    rt, log, compose = docker
    c = await rt.find()
    ours = [f"settings.yml.aihub-2026-01-01T1200{s:02d}" for s in range(12)] + [
        "settings.yml.aihub-2026-01-01T120011-2", "settings.yml.aihub-2026-01-01T120011-10"]
    for n in ours + ["settings.yml.aihub-keep", "settings.yml.bak"]:
        (folder / n).write_text("x")
    assert rt.backups(c)[:3] == ["settings.yml.aihub-2026-01-01T120011-10", "settings.yml.aihub-2026-01-01T120011-2",
                                 "settings.yml.aihub-2026-01-01T120011"]
    gone = await rt.prune(c, 10)
    assert sorted(gone) == [f"settings.yml.aihub-2026-01-01T1200{s:02d}" for s in range(4)]
    assert len(rt.backups(c)) == 10 and (folder / "settings.yml.aihub-keep").exists() and (folder / "settings.yml.bak").exists()
    rm = [x["args"] for x in _calls(log) if x["args"][:3] == ["exec", c.id, "rm"]]
    assert len(rm) == 1 and all(a.startswith("/etc/searxng/settings.yml.aihub-") for a in rm[0][5:])
    assert await rt.prune(c, 10) == []
