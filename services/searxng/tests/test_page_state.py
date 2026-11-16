"""capability-enablement 5.4: the state the SearXNG and Web pages read (GET /v1/search-state): yours, GAIFA's own, or
none, its URL, whether it answers, and the buttons that make sense."""

from __future__ import annotations

from fastapi.testclient import TestClient

import server
import source as src
from managed import Managed
from test_managed import FakeRt


def app_with(runtime, url, rt, root, monkeypatch):
    monkeypatch.setenv("GAIFA_ROOT", str(root))
    return server.create_app(runtime, env_url=url, watch_s=3600, query_s=3600, ready_s=2,
                             managed=Managed(run=rt, runtime="podman", port_free=lambda p: True))


def test_yours(runtime, fake, tmp_path, monkeypatch):
    with TestClient(app_with(runtime, fake.url, FakeRt(), tmp_path, monkeypatch)) as c:
        s = c.get("/v1/search-state").json()
    assert (s["using"], s["url"], s["up"], s["json"]) == ("yours", fake.url, True, True)
    assert s["actions"] == ["start_managed", "use_port"]


def test_none(runtime, tmp_path, monkeypatch):
    with TestClient(app_with(runtime, "http://127.0.0.1:9", FakeRt(), tmp_path, monkeypatch)) as c:
        s = c.get("/v1/search-state").json()
    assert (s["using"], s["url"], s["up"]) == ("none", None, False) and "start_managed" in s["actions"]


def test_managed(runtime, tmp_path, monkeypatch):
    rt = FakeRt()
    rt.exists = rt.running = True
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))
    (tmp_path / "data/state/searxng").mkdir(parents=True)
    (tmp_path / "data/state/searxng/managed.json").write_text('{"port": 9}')    # a port nothing listens on (5200 may be a real one)
    src.save("managed", "http://127.0.0.1:9")
    with TestClient(app_with(runtime, "http://127.0.0.1:9", rt, tmp_path, monkeypatch)) as c:
        s = c.get("/v1/search-state").json()
    assert (s["using"], s["url"]) == ("managed", "http://127.0.0.1:9") and s["up"] is False   # its health: nothing listens in the test
    assert s["actions"] == ["use_port", "remove_managed"] and s["managed"]["running"] is True


def test_yours_without_json(runtime, fake, folder, tmp_path, monkeypatch):
    from conftest import SETTINGS
    (folder / "settings.yml").write_text(SETTINGS.replace("    - json\n", ""))
    fake.reload()
    with TestClient(app_with(runtime, fake.url, FakeRt(), tmp_path, monkeypatch)) as c:
        s = c.get("/v1/search-state").json()
    assert s["using"] == "yours" and s["json"] is False and s["answer"] == "yours_no_json"
