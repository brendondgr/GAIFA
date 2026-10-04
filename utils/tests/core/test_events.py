import asyncio
import json

import pytest

from utils.db import Database
from utils.events import ACTIVITY_MAX_AGE_S, RESYNC, ActivityLog, Alerts, EventBus, sse_frame, sse_stream


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "hub.db")
    d.open()
    yield d
    d.close()


def drain(sub):
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def test_fan_out_to_every_subscriber():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish({"type": "x", "n": 1})
    bus.publish({"type": "x", "n": 2})
    assert drain(a) == drain(b) == [{"type": "x", "n": 1}, {"type": "x", "n": 2}]
    a.close()
    bus.publish({"type": "x", "n": 3})
    assert drain(a) == [] and drain(b) == [{"type": "x", "n": 3}]
    assert bus.subscribers == 1


def test_overflow_replaces_backlog_with_resync():
    bus = EventBus(queue_size=5)
    slow, fast = bus.subscribe(), bus.subscribe()
    for n in range(5):
        bus.publish({"n": n})
    drain(fast)
    bus.publish({"n": 5})
    assert drain(slow) == [RESYNC, {"n": 5}]
    assert drain(fast) == [{"n": 5}]  # other subscribers are unaffected
    for n in range(6, 20):
        bus.publish({"n": n})
    got = drain(slow)
    assert got[0] == RESYNC and got[-1] == {"n": 19} and len(got) <= 5


async def test_subscription_iterates():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish({"type": "a"})
    assert await anext(aiter(sub)) == {"type": "a"}


def test_sse_frame():
    assert sse_frame({"type": "alert_cleared", "id": "x"}) == 'data: {"type":"alert_cleared","id":"x"}\n\n'


async def test_sse_stream_framing_and_ping():
    bus = EventBus()
    gen = sse_stream(bus, ping_s=0.05)
    assert await anext(gen) == "retry: 3000\n\n"
    assert bus.subscribers == 1
    assert await anext(gen) == ": ping\n\n"
    bus.publish({"type": "job", "job": {"id": "1"}})
    frame = await anext(gen)
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:]) == {"type": "job", "job": {"id": "1"}}
    await gen.aclose()
    assert bus.subscribers == 0


async def test_activity_persists_and_publishes(db):
    bus = EventBus()
    sub = bus.subscribe()
    log = ActivityLog(db, bus)
    await log.load()
    item = await log.add("Speech started", service="tts", route="/services/tts")
    assert item["id"] == "1" and item["level"] == "info" and item["route"] == "/services/tts"
    assert drain(sub) == [{"type": "activity", "item": item}]
    await log.add("Disk low", level="warn")
    assert [a["text"] for a in log.recent()] == ["Disk low", "Speech started"]

    again = ActivityLog(db, EventBus())
    await again.load()
    assert again.recent() == log.recent()
    assert "route" not in again.recent()[0]


async def test_activity_keeps_500_in_memory(db):
    log = ActivityLog(db, EventBus())
    for i in range(510):
        await log.add(f"e{i}")
    assert len(log.recent(1000)) == 500
    assert log.recent(1)[0]["text"] == "e509"
    assert (await db.fetchone("SELECT count(*) AS n FROM activity"))["n"] == 510


async def test_activity_pruned_after_30_days(db):
    log = ActivityLog(db, EventBus())
    await db.execute("INSERT INTO activity (ts, level, text) VALUES (?, 'info', 'old')", (1.0,))
    await log.add("new")
    await log.load()
    assert [a["text"] for a in log.recent()] == ["new"]
    future = log.recent()[0]["ts"] + ACTIVITY_MAX_AGE_S + 1
    assert await log.prune(now=future) == 1
    assert log.recent() == []


def test_alerts_publish_changes_only():
    bus = EventBus()
    sub = bus.subscribe()
    alerts = Alerts(bus)
    a = alerts.set("disk", "warn", "Disk 90% full", action={"label": "Open", "route": "/settings"})
    alerts.set("disk", "warn", "Disk 90% full", action={"label": "Open", "route": "/settings"})
    assert drain(sub) == [{"type": "alert", "alert": a}]
    alerts.set("disk", "error", "Disk 98% full")
    assert drain(sub)[0]["alert"]["level"] == "error"
    assert alerts.list() == [{"id": "disk", "level": "error", "text": "Disk 98% full"}]
    assert alerts.clear("disk") is True
    assert alerts.clear("disk") is False
    assert drain(sub) == [{"type": "alert_cleared", "id": "disk"}]
