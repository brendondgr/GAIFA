"""3.3: verifying checksums in the background, with progress, mismatches and cancelling."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time

import pytest

from utils.events import ActivityLog
from utils.registry import RegistryError
from utils.registry import verify as verify_mod
from utils.registry.verify import Verifier
from utils.tests.models.conftest import Models
from utils.tests.services.conftest import until


class SlowSha:
    """hashlib.sha256 that takes `delay` per update, so progress can be watched."""

    delay = 0.005

    def __init__(self) -> None:
        self._h = hashlib.sha256()

    def update(self, b) -> None:
        time.sleep(self.delay)
        self._h.update(b)

    def hexdigest(self) -> str:
        return self._h.hexdigest()


@pytest.fixture
def slow(monkeypatch):
    monkeypatch.setattr(verify_mod, "CHUNK", 64 * 1024)
    monkeypatch.setattr(verify_mod, "HASH", SlowSha)
    return SlowSha


@pytest.fixture
async def ver(reg):
    v = Verifier(reg, progress_every_s=0.03)
    v.start()
    yield v
    await v.close()


def seed(models: Models, size: int = 4096):
    models.put("llm/m/a.gguf", size)
    models.put("llm/m/b.gguf", 100)
    models.write({"m": {"name": "M", "kind": "llm", "path": "llm/m", "files": [models.file("llm/m/a.gguf"), models.file("llm/m/b.gguf")]}})


async def done(reg, mid="m"):
    await until(lambda: mid not in reg.progress, timeout=10)
    return reg.view(mid)


async def test_first_verify_records_checksums(reg, models, ver):
    seed(models)
    reg.load()
    v = ver.request("m")
    assert v["status"] == "verifying" and v["progress"] == 0
    v = await done(reg)
    assert v["status"] == "ok" and all(f["verified"] for f in v["files"])
    stored = models.read()["models"]["m"]["files"][0]
    assert stored["sha256"] == hashlib.sha256((models.dir / "llm/m/a.gguf").read_bytes()).hexdigest()
    assert stored["verified_at"] and stored["size_bytes"] == 4096


async def test_a_corrupted_file_ends_as_checksum_mismatch(reg, models, ver, bus):
    seed(models)
    reg.load()
    ver.request("m")
    await done(reg)
    p = models.dir / "llm/m/a.gguf"
    data = bytearray(p.read_bytes())
    data[100] ^= 0xFF  # same size, one byte flipped
    st = p.stat()
    p.write_bytes(bytes(data))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # even with the old mtime, verify catches it
    assert reg.view("m")["status"] == "ok"  # nothing on disk says it changed…
    ver.request("m")
    v = await done(reg)  # …until it is hashed again
    assert v["status"] == "checksum_mismatch"
    assert v["problems"][0].startswith("Checksum mismatch: sha256 of llm/m/a.gguf is ")
    assert models.read()["models"]["m"]["files"][0]["actual_sha256"] == hashlib.sha256(bytes(data)).hexdigest()
    ver.request("m", reset=True)  # accept the file as it is now
    v = await done(reg)
    assert v["status"] == "ok" and "actual_sha256" not in models.read()["models"]["m"]["files"][0]


async def test_progress_events_every_tick(reg, models, ver, bus, slow):
    seed(models, size=2 * 1024 * 1024)  # 32 slow chunks ≈ 0.2 s
    reg.load()
    sub = bus.subscribe()
    ver.request("m")
    await done(reg)
    events = []
    while not sub.queue.empty():
        ev = sub.queue.get_nowait()
        if ev["type"] == "model":
            events.append(ev["model"])
    progress = [e["progress"] for e in events if e["status"] == "verifying"]
    assert len(progress) >= 3 and progress[0] == 0 and progress == sorted(progress) and progress[-1] < 1
    assert len(set(progress)) >= 3
    assert events[-1]["status"] == "ok" and "progress" not in events[-1]


async def test_one_at_a_time_and_repeat_requests(reg, models, ver, slow):
    seed(models, size=1024 * 1024)
    models.put("vae/x.safetensors", 1024 * 1024)
    doc = models.read()["models"]
    doc["x"] = {**doc["m"], "path": "vae/x.safetensors", "files": [models.file("vae/x.safetensors")]}
    models.write(doc)
    reg.load()
    ver.request("m")
    ver.request("x")
    assert ver.request("x")["progress"] == 0  # asking again doesn't queue it twice
    await until(lambda: ver.current == "m")
    assert reg.view("x")["status"] == "verifying" and reg.progress["x"] == 0  # waiting its turn
    await done(reg, "x")
    assert reg.view("m")["status"] == reg.view("x")["status"] == "ok"


async def test_missing_files_cant_be_verified(reg, models, ver):
    models.write({"gone": {"files": [{"path": "llm/nope.gguf"}]}})
    reg.load()
    with pytest.raises(RegistryError) as e:
        ver.request("gone")
    assert (e.value.status, e.value.code) == (409, "model_files_missing")
    with pytest.raises(RegistryError) as e:
        ver.request("nope")
    assert e.value.code == "model_not_found"


async def test_deleting_a_model_cancels_its_verification(reg, models, ver, slow):
    seed(models, size=4 * 1024 * 1024)
    reg.load()
    ver.request("m")
    await until(lambda: ver.current == "m")
    await reg.delete("m")
    assert "m" not in reg.progress
    await until(lambda: ver.current is None, timeout=2)
    assert models.read()["models"] == {}


async def test_shutdown_stops_hashing_quickly(reg, models, slow):
    seed(models, size=16 * 1024 * 1024)  # ≈ 1.3 s of slow hashing
    reg.load()
    v = Verifier(reg)
    v.start()
    v.request("m")
    await until(lambda: v.current == "m")
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await v.close()
    assert time.monotonic() - t0 < 0.5 and reg.progress == {}
    assert models.read()["models"]["m"]["files"][0]["sha256"] is None  # nothing half-recorded


async def test_activity_for_results(models, bus, root):
    from utils.db import Database
    from utils.registry import Registry

    db = Database(models.paths.hub_db)
    db.open()
    try:
        act = ActivityLog(db, bus)
        reg = Registry(models.paths, bus, act)
        seed(models)
        reg.load()
        v = Verifier(reg)
        v.start()
        v.request("m")
        await done(reg)
        await v.close()
        assert act.recent(1)[0]["text"] == "Verified M" and act.recent(1)[0]["route"] == "#/models/m"
    finally:
        db.close()


async def test_verify_route(root, client):
    m = Models(root)
    seed(m)
    r = await client.post("/api/models/m/verify")
    assert r.status_code == 202 and r.json()["status"] == "verifying"
    for _ in range(200):
        v = (await client.get("/api/models/m")).json()
        if v["status"] != "verifying":
            break
        await asyncio.sleep(0.02)
    assert v["status"] == "ok"
    assert (await client.post("/api/models/nope/verify")).status_code == 404
