"""4.5: one activity item per new output, batched when a mod makes more than 5 at once."""

from __future__ import annotations

import asyncio

from utils.events import ActivityLog
from utils.outputs.announce import Announcer


def out(i: int, service: str = "gen3d") -> dict:
    return {"id": f"o{i}", "service": service, "title": f"thing {i}"}


async def test_a_few_outputs_get_an_item_each(db, bus):
    act = ActivityLog(db, bus)
    a = Announcer(act, {"tts": "Speech"}.get, quiet_s=0.05, window_s=0.5)
    for i in range(3):
        a.add(out(i, "tts"))
    await asyncio.sleep(0.2)
    assert [(x["text"], x["route"], x["service"]) for x in reversed(act.recent())] == [
        ('Speech created "thing 0"', "#/outputs/o0", "tts"),
        ('Speech created "thing 1"', "#/outputs/o1", "tts"),
        ('Speech created "thing 2"', "#/outputs/o2", "tts"),
    ]


async def test_a_burst_becomes_one_item_per_mod(db, bus):
    act = ActivityLog(db, bus)
    a = Announcer(act, lambda s: {"gen3d": "3D Generate"}.get(s, s), quiet_s=0.05, window_s=0.5)
    for i in range(8):
        a.add(out(i))
    a.add(out(99, "tts"))
    await asyncio.sleep(0.2)
    texts = sorted(x["text"] for x in act.recent())
    assert texts == ["3D Generate created 8 outputs", 'tts created "thing 99"']
    assert next(x for x in act.recent() if x["service"] == "gen3d")["route"] == "#/outputs"


async def test_the_window_closes_after_10s_even_without_a_pause(db, bus):
    act = ActivityLog(db, bus)
    a = Announcer(act, quiet_s=0.1, window_s=0.3)
    for i in range(12):  # one every 0.05 s for 0.6 s: never quiet, so the window caps it
        a.add(out(i))
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)
    counts = sorted(x["text"] for x in act.recent())
    assert len(counts) >= 2 and all("created" in t for t in counts)
    total = sum(int(t.split()[2]) if t.endswith("outputs") else 1 for t in counts)
    assert total == 12


async def test_close_writes_what_is_waiting(db, bus):
    act = ActivityLog(db, bus)
    a = Announcer(act, quiet_s=5, window_s=10)
    a.add(out(1))
    await a.close()
    assert [x["text"] for x in act.recent()] == ['gen3d created "thing 1"']
