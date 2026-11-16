"""capability-enablement 5.2: GAIFA's own SearXNG with a fake container runtime: the create command (name, the image by
digest, 127.0.0.1 and the port, the mount), the settings file, the port fallback, the refusal while yours is chosen,
start and stop with the mod, and removal."""

from __future__ import annotations

import json

import pytest

import source as src
from managed import IMAGE, NAME, Managed, ManagedError


class FakeRt:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.exists = False
        self.running = False

    async def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        cmd = argv[1]
        if cmd == "inspect":
            return (0, "running" if self.running else "exited") if self.exists else (1, "no such container")
        if cmd == "run":
            self.exists = self.running = True
            return 0, "abc123"
        if cmd == "start":
            self.running = self.exists
            return 0, NAME
        if cmd == "stop":
            self.running = False
            return 0, NAME
        if cmd == "rm":
            self.exists = self.running = False
            return 0, NAME
        if cmd == "rmi":
            return 0, "untagged"
        return 1, f"unknown {cmd}"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))
    return tmp_path


async def test_create_command_settings_and_choice(root):
    rt = FakeRt()
    m = Managed(run=rt, runtime="podman", port_free=lambda p: True)
    out = await m.create()
    run = next(c for c in rt.calls if c[1] == "run")
    assert run[:5] == ["podman", "run", "-d", "--name", NAME] and IMAGE in run and "@sha256:" in IMAGE
    assert "127.0.0.1:5200:8080" in run and "--network" not in run and "host" not in " ".join(run)
    assert f"{root}/data/state/searxng/managed:/etc/searxng:Z" in run
    settings = (root / "data/state/searxng/managed/settings.yml").read_text()
    assert "use_default_settings: true" in settings and "- json" in settings and "limiter: false" in settings
    assert 'secret_key: "' in settings and "not-a-secret" not in settings
    assert out["running"] is True and out["url"] == "http://127.0.0.1:5200"
    assert json.loads((root / "data/state/searxng/managed.json").read_text())["port"] == 5200   # outside the mounted folder
    assert json.loads((root / "data/state/searxng/source.json").read_text()) == {"source": "managed", "url": "http://127.0.0.1:5200"}
    again = await m.create()                                   # already there: no second run
    assert [c[1] for c in rt.calls].count("run") == 1 and again["running"]


async def test_the_next_free_port_never_8080(root):
    rt = FakeRt()
    taken = {5200, 5201}
    m = Managed(run=rt, runtime="podman", port_free=lambda p: p not in taken)
    await m.create()
    assert "127.0.0.1:5202:8080" in next(c for c in rt.calls if c[1] == "run") and m.port() == 5202
    m2 = Managed(run=FakeRt(), runtime="podman", folder=root / "other", port_free=lambda p: False)
    with pytest.raises(ManagedError) as e:
        await m2.create()
    assert e.value.code == "no_port"


async def test_refused_while_yours_is_chosen_and_without_a_runtime(root):
    src.save("yours", "http://127.0.0.1:8080")
    with pytest.raises(ManagedError) as e:
        await Managed(run=FakeRt(), runtime="podman").create()
    assert e.value.code == "yours_chosen"
    (root / "data/state/searxng/source.json").unlink()
    with pytest.raises(ManagedError) as e:
        await Managed(run=FakeRt(), runtime="").create()
    assert e.value.code == "no_runtime" and "podman" in e.value.fix


async def test_remove_and_its_image(root):
    rt = FakeRt()
    m = Managed(run=rt, runtime="docker", port_free=lambda p: True)
    await m.create()
    out = await m.remove(image=True)
    assert out == {"removed": True, "image_removed": True}
    assert ["docker", "rmi", IMAGE] in rt.calls and not (root / "data/state/searxng/source.json").exists()
    assert (root / "data/state/searxng/managed/settings.yml").exists()        # the settings stay


def test_it_starts_and_stops_with_the_mod(root, runtime, fake):
    from fastapi.testclient import TestClient

    import server
    rt = FakeRt()
    rt.exists = True
    m = Managed(run=rt, runtime="podman", port_free=lambda p: True)
    (root / "data/state/searxng").mkdir(parents=True)
    (root / "data/state/searxng/managed.json").write_text('{"port": 5200}')
    src.save("managed", "http://127.0.0.1:5200")
    app = server.create_app(runtime, env_url=fake.url, watch_s=3600, query_s=3600, ready_s=2, managed=m)
    with TestClient(app) as c:
        assert ["podman", "start", NAME] in rt.calls
        assert c.get("/v1/managed").json()["running"] is True
        assert c.get("/v1/endpoint").json()["url"] == "http://127.0.0.1:5200"
    assert ["podman", "stop", "-t", "5", NAME] in rt.calls


def test_the_routes_refuse_while_yours_is_chosen(root, runtime, fake):
    from fastapi.testclient import TestClient

    import server
    src.save("yours", fake.url)
    app = server.create_app(runtime, env_url=fake.url, watch_s=3600, query_s=3600, ready_s=2, managed=Managed(run=FakeRt(), runtime="podman"))
    with TestClient(app) as c:
        r = c.post("/v1/managed", json={})
        assert r.status_code == 409 and r.json()["code"] == "yours_chosen"
