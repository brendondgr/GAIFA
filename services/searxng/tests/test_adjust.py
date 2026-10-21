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
    r = client.post("/v1/settings", json={"json_format": True})
    assert r.status_code == 200 and r.json()["changed"], r.text
    assert _doc(folder)["search"]["formats"] == ["html", "json"] and fake.json
    assert fake.queries[-1]["format"] == "json"                                  # the check searched as JSON


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
