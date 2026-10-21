"""Every adjustment backs up settings.yml, writes it, restarts SearXNG and checks a search; a check
that fails puts the backup back (plan 26.3)."""

from __future__ import annotations

from ruamel.yaml import YAML

from containers import BACKUP_RE
from conftest import SETTINGS


def _doc(folder):
    return YAML(typ="safe").load((folder / "settings.yml").read_text())


def _backups(folder):
    return sorted(p.name for p in folder.iterdir() if BACKUP_RE.match(p.name))


def test_engine_off_and_on(client, folder, fake, runtime):
    r = client.post("/v1/engines/bing", json={"enabled": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True and BACKUP_RE.match(body["backup"]) and "test search answered" in body["detail"]
    assert {"name": "bing", "disabled": True} in _doc(folder)["engines"]
    assert next(e for e in fake.engines if e["name"] == "bing")["enabled"] is False
    assert (folder / body["backup"]).read_text() == SETTINGS                     # the backup is the file before
    assert runtime.log == [f"backup {body['backup']}", "write", "restart"]
    on = client.post("/v1/engines/bing", json={"enabled": True}).json()
    assert on["changed"] is True and next(e for e in fake.engines if e["name"] == "bing")["enabled"] is True
    assert len(_backups(folder)) == 2 and runtime.restarts == 2
    engines = {e["name"]: e for e in client.get("/v1/engines").json()["engines"]}
    assert engines["bing"]["enabled"] and engines["brave"]["errors"][0]["type"] == "SearxEngineTooManyRequestsException"


def test_comments_and_other_keys_stay(client, folder):
    client.post("/v1/engines/wikipedia", json={"enabled": False})
    text = (folder / "settings.yml").read_text()
    assert '# the test\'s own' in text and 'secret_key: "not-a-secret"' in text and "use_default_settings: true" in text
    assert "  - name: google\n    engine: google\n    disabled: false" in text


def test_already_set_changes_nothing(client, folder, runtime):
    r = client.post("/v1/engines/google", json={"enabled": True}).json()
    assert r["changed"] is False and r["detail"] == "already set"
    assert _backups(folder) == [] and runtime.restarts == 0


def test_every_setting(client, folder, fake):
    r = client.post("/v1/settings", json={"safe_search": 2, "default_lang": "de-DE", "request_timeout": 6.5,
                                          "engine_timeouts": {"google": 5}})
    assert r.status_code == 200 and r.json()["changed"], r.text
    d = _doc(folder)
    assert d["search"]["safe_search"] == 2 and d["search"]["default_lang"] == "de-DE"
    assert d["outgoing"]["request_timeout"] == 6.5
    assert next(e for e in d["engines"] if e["name"] == "google")["timeout"] == 5.0
    assert fake.safe == 2 and next(e for e in fake.engines if e["name"] == "google")["timeout"] == 5.0
    assert len(_backups(folder)) == 1                                            # one backup for the lot


def test_json_format_on(client, folder, fake):
    (folder / "settings.yml").write_text(SETTINGS.replace("    - json\n", ""))
    fake.reload()
    assert client.get("/v1/settings").json()["settings"]["json"] is False
    before = len(fake.queries)
    r = client.post("/v1/settings", json={"json_format": True})
    assert r.status_code == 200 and r.json()["changed"], r.text
    assert _doc(folder)["search"]["formats"] == ["html", "json"] and fake.json
    # the change's check searched as JSON; the app's own watch loop may query (as HTML) in between
    assert any(q["format"] == "json" for q in fake.queries[before:])


def test_a_change_that_breaks_searxng_is_rolled_back(client, folder, fake, runtime):
    r = client.post("/v1/settings", json={"default_lang": "xx"})
    assert r.status_code == 409 and r.json()["code"] == "change_failed", r.text
    detail = r.json()["detail"]
    assert "healthz didn't answer" in detail and "the backup is back" in detail
    assert (folder / "settings.yml").read_text() == SETTINGS and fake.up
    backup = r.json()["data"]["backup"]
    assert runtime.log == [f"backup {backup}", "write", "restart", f"restore {backup}", "restart"]
    changes = client.get("/v1/settings").json()["changes"]
    assert changes[0]["rolled_back"] is True and changes[0]["backup"] == backup


def test_a_change_that_doesnt_take_effect_is_rolled_back(client, folder, fake):
    r = client.post("/v1/engines/stubborn", json={"enabled": False})
    assert r.status_code == 409 and "still has stubborn on" in r.json()["detail"]
    assert (folder / "settings.yml").read_text() == SETTINGS


def test_refusals(client, runtime):
    assert client.post("/v1/engines/nope", json={"enabled": False}).json()["code"] == "no_engine"
    assert client.post("/v1/settings", json={}).json()["code"] == "nothing_to_change"
    assert client.post("/v1/settings", json={"engine_timeouts": {"nope": 2}}).json()["code"] == "no_engine"
    assert client.post("/v1/settings", json={"safe_search": 3}).status_code == 422
    assert client.post("/v1/settings", json={"default_lang": "../etc"}).status_code == 422
    assert client.post("/v1/settings", json={"json_format": False}).status_code == 422
    runtime.running = False
    client.post("/v1/detect")
    r = client.post("/v1/engines/bing", json={"enabled": False})
    assert r.status_code == 409 and "exited" in r.json()["detail"] and "docker start" in r.json()["fix"]
    assert runtime.restarts == 0


def test_a_backup_that_fails_changes_nothing_and_says_so(client, folder, runtime):
    """The backup step failing (e.g. Docker's containerd down) is a clear 503, and nothing is written."""
    from containers import RuntimeError_

    async def broken(c):
        raise RuntimeError_('docker exec abc123 cp: Unavailable: connection error: dial unix /run/containerd/containerd.sock')
    runtime.backup = broken
    r = client.post("/v1/engines/bing", json={"enabled": False})
    assert r.status_code == 503, r.text
    b = r.json()
    assert b["code"] == "backup_failed" and "nothing was changed" in b["detail"] and "containerd" in b["detail"] and b["fix"]
    assert (folder / "settings.yml").read_text() == SETTINGS and runtime.restarts == 0 and _backups(folder) == []
    assert client.get("/v1/settings").json()["changes"][0]["detail"].startswith("couldn't back up")


def test_a_read_that_fails_changes_nothing_and_says_so(client, runtime):
    async def broken(c):
        raise OSError(5, "Input/output error")
    runtime.read = broken
    r = client.post("/v1/settings", json={"safe_search": 1})
    assert r.status_code == 503 and r.json()["code"] == "read_failed" and "Input/output error" in r.json()["detail"]
    assert runtime.restarts == 0


BROKEN = "use_default_settings: true\nserver:\n  secret_key: 'half-edited\n  limiter: [\n"   # a quote never closed


def test_a_settings_file_that_doesnt_parse_is_reported_and_left_alone(folder, fake, runtime):
    """The mod starts and says where the file breaks; changes are refused until it's fixed (it crash-looped)."""
    from fastapi.testclient import TestClient

    import server
    (folder / "settings.yml").write_text(BROKEN)
    with TestClient(server.create_app(runtime, env_url=fake.url, watch_s=3600, query_s=3600, ready_s=2)) as c:
        hint = next(x for x in c.get("/v1/status").json()["stats"] if x["label"] == "SearXNG")["hint"]
        assert "settings.yml doesn't parse" in hint and "line 5, column 1" in hint and "line 3, column 15" in hint
        assert "doesn't parse" in c.get("/v1/found").json()["settings_problem"]
        r = c.get("/v1/settings")
        assert r.status_code == 409 and r.json()["code"] == "settings_invalid", r.text
        assert "line 5, column 1" in r.json()["detail"] and str(folder / "settings.yml") in r.json()["fix"]
        r = c.post("/v1/engines/bing", json={"enabled": False})
        assert r.status_code == 409 and r.json()["code"] == "settings_invalid" and "nothing was changed" in r.json()["detail"]
        assert (folder / "settings.yml").read_text() == BROKEN and runtime.restarts == 0 and _backups(folder) == []
        (folder / "settings.yml").write_text("- a list\n- not a mapping\n")
        r = c.get("/v1/settings")
        assert r.status_code == 409 and "isn't a mapping (its top level is a list)" in r.json()["detail"]
        (folder / "settings.yml").write_text(SETTINGS)                          # fixed by hand
        assert c.get("/v1/settings").status_code == 200 and c.get("/v1/found").json()["settings_problem"] is None
        assert c.post("/v1/engines/bing", json={"enabled": False}).json()["changed"] is True


def test_startup_survives_a_runtime_that_fails(fake):
    """Whatever the first look runs into, the server starts (and the watch loop looks again)."""
    from fastapi.testclient import TestClient

    import server

    class Broken:
        async def find(self):
            raise RuntimeError("the container went away")
    with TestClient(server.create_app(Broken(), env_url=fake.url, watch_s=3600)) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/v1/found").json()["container"] is None


def test_old_backups_are_pruned(client, folder, runtime):
    """A change keeps the newest 10 of this mod's backups; files it didn't name stay."""
    old = [f"settings.yml.aihub-2026-01-{d:02d}T120000" for d in range(1, 13)] + ["settings.yml.aihub-2026-01-12T120000-2"]
    for n in old:
        (folder / n).write_text("old")
    others = ["settings.yml.aihub-mine", "settings.yml.bak", "settings.yml.aihub-2026-01-01T120000.txt"]
    for n in others:
        (folder / n).write_text("not ours")
    r = client.post("/v1/engines/bing", json={"enabled": False}).json()
    assert r["changed"] is True
    left = runtime.backups(None)
    assert len(left) == 10 and left[0] == r["backup"] and left[1] == "settings.yml.aihub-2026-01-12T120000-2"
    assert sorted(r["pruned"]) == [f"settings.yml.aihub-2026-01-{d:02d}T120000" for d in range(1, 5)]
    assert all((folder / n).exists() for n in others)
