"""3.5: registry alerts follow missing, partial and checksum-mismatch models."""

from __future__ import annotations

import asyncio

from utils.events import Alerts
from utils.registry import Registry
from utils.registry.alerts import Watcher, refresh


def ids(alerts: Alerts) -> dict[str, str]:
    return {a["id"]: a["text"] for a in alerts.list()}


def test_alerts_follow_the_statuses(models, bus):
    alerts = Alerts(bus)
    alerts.set("svc-x", "error", "unrelated alert stays")
    models.put("a.gguf", 10)
    models.put("b.gguf", 5)
    bad = models.file("b.gguf", verified=True) | {"actual_sha256": "1" * 64}
    models.write({
        "gone1": {"name": "Gone 1", "files": [models.file("x/gone1.gguf")]},
        "gone2": {"name": "Gone 2", "files": [models.file("x/gone2.gguf")]},
        "half": {"name": "Half", "files": [models.file("a.gguf"), models.file("x/nope.gguf")]},
        "bad": {"name": "Bad", "files": [bad]},
    })
    reg = Registry(models.paths, bus, alerts=alerts)
    reg.load()
    refresh(reg)
    assert ids(alerts) == {
        "svc-x": "unrelated alert stays",
        "models-missing": "2 models have missing files",
        "models-partial": "1 model is incomplete",
        "sum-bad": "Checksum mismatch: Bad",
    }
    a = {x["id"]: x for x in alerts.list()}
    assert a["models-missing"]["action"] == {"label": "Review", "route": "#/models?status=missing"} and a["models-missing"]["level"] == "warn"
    assert a["sum-bad"]["action"]["route"] == "#/models/bad" and a["sum-bad"]["level"] == "error"
    sub = bus.subscribe()
    models.put("x/gone1.gguf", 1000)  # the right size now: no longer missing
    models.put("x/nope.gguf", 1000)
    reg.list()  # reading the list keeps alerts in step
    assert ids(alerts) == {"svc-x": "unrelated alert stays", "models-missing": "1 model has missing files", "sum-bad": "Checksum mismatch: Bad"}
    events = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    assert {"type": "alert_cleared", "id": "models-partial"} in events
    reg.entries.clear()
    refresh(reg)
    assert ids(alerts) == {"svc-x": "unrelated alert stays"}


def test_unreadable_registry_alert(models, bus):
    alerts = Alerts(bus)
    models.paths.registry.write_text("{nope")
    reg = Registry(models.paths, bus, alerts=alerts)
    reg.load()
    refresh(reg)
    assert ids(alerts)["registry-invalid"].startswith("Models registry: registry.json can't be read")
    models.write({"x y": {"files": []}})
    reg.load()
    refresh(reg)
    assert ids(alerts)["registry-invalid"].startswith("registry.json: 1 entry can't be read (x y: not a valid model id")
    models.write({})
    reg.load()
    refresh(reg)
    assert "registry-invalid" not in ids(alerts)


async def test_watcher_notices_files_vanishing(models, bus):
    alerts = Alerts(bus)
    p = models.put("a.gguf", 10)
    models.write({"a": {"files": [models.file("a.gguf")]}})
    reg = Registry(models.paths, bus, alerts=alerts)
    reg.load()
    w = Watcher(reg, every=0.05)
    w.start()
    sub = bus.subscribe()
    try:
        assert "models-missing" not in ids(alerts)
        p.unlink()
        for _ in range(100):
            if "models-missing" in ids(alerts):
                break
            await asyncio.sleep(0.02)
        assert ids(alerts)["models-missing"] == "1 model has missing files"
        events = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
        changed = [e["model"]["status"] for e in events if e["type"] == "model"]
        assert changed == ["missing"]  # the UI hears about it without reloading
    finally:
        await w.close()


async def test_alerts_through_the_hub(root, client, app):
    from utils.tests.models.conftest import Models

    m = Models(root)
    m.put("vae/v.safetensors", 64)
    r = await client.post("/api/models", json={"path": "vae/v.safetensors", "name": "V", "kind": "vae"})
    assert r.status_code == 201
    (m.dir / "vae/v.safetensors").unlink()
    await client.get("/api/models")
    recent = (await client.get("/api/events/recent")).json()
    assert any(a["id"] == "models-missing" for a in recent["alerts"])
    assert (await client.delete("/api/models/v")).status_code == 204
    recent = (await client.get("/api/events/recent")).json()
    assert not any(a["id"] == "models-missing" for a in recent["alerts"])
