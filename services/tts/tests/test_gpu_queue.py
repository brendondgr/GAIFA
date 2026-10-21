"""Plan 31.3: each synthesis takes AIHub's GPU slot. It waits (listed as a `waiting_gpu` job in the status)
while another mod's work holds the GPU, runs after, and gives the slot back when it ends or its client goes
away. An engine set to the CPU doesn't take it."""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fakegpu import FakeGpu

from localtts import engines, hub
from localtts.gpu_slot import GpuSlot

WORKER = """
import sys, time
sys.path.insert(0, {workers!r})
import _proto
_proto.claim_stdout()

def generate(text, request_id="req", **_):
    for _ in range(3):
        _proto.send_audio([0.0] * 240)
    _proto.send("done", audio_s=0.03)

_proto.send("ready", sample_rate=24000)
_proto.serve({{"generate": generate}})
"""


@pytest.fixture
def fake(monkeypatch):
    f = FakeGpu()
    monkeypatch.setattr(engines, "_GPU", GpuSlot(hub_url="http://hub", service="tts", group="tts",
                                                 transport=httpx.ASGITransport(app=f.app), poll_s=0.1))
    return f


@pytest.fixture
def engine(tmp_path):
    script = tmp_path / "quick_worker.py"
    script.write_text(WORKER.format(workers=str(engines.WORKERS)))
    return engines.Engine("quick", Path(sys.executable), str(script))


async def speak(engine) -> list:
    out = []
    gen = engine.generate(request_id="r1", text="hello")
    try:
        async for item in gen:
            out.append(item)
    finally:
        await gen.aclose()
    return out


def test_a_synthesis_waits_for_the_gpu_then_runs(fake, engine):
    other = fake.hold("comfy", "portrait")

    async def run():
        try:
            task = asyncio.create_task(speak(engine))
            for _ in range(100):
                if engines.WAITING:
                    break
                await asyncio.sleep(0.02)
            job = hub.status()["jobs"][0]
            assert job["stage"] == "waiting_gpu" and job["state"] == "queued" and job["ahead"][0]["service"] == "comfy"
            assert not task.done()
            fake.release(other)
            out = await asyncio.wait_for(task, 10)
            assert isinstance(out[0], bytes) and out[-1]["event"] == "done"
            assert hub.status()["jobs"] == []
        finally:
            await engine.unload()

    asyncio.run(run())
    assert ("granted", "tts", "job") in fake.log and ("released", "tts", "job") in fake.log and not fake.held


def test_a_client_that_goes_away_gives_the_slot_back(fake, engine):
    async def run():
        try:
            gen = engine.generate(request_id="r2", text="hello")
            assert isinstance(await anext(gen), bytes)
            assert [x["service"] for x in fake.held.values()] == ["tts"]
            await gen.aclose()
        finally:
            await engine.unload()

    asyncio.run(run())
    assert not fake.held and ("released", "tts", "job") in fake.log


def test_an_engine_on_the_cpu_takes_no_slot(fake, tmp_path, monkeypatch):
    script = tmp_path / "quick_worker.py"
    script.write_text(WORKER.format(workers=str(engines.WORKERS)))
    cpu = engines.Engine("cpu", Path(sys.executable), str(script), env={"BREEZE_DEVICE": "cpu"}, device_env="BREEZE_DEVICE")
    fake.hold("comfy")

    async def run():
        try:
            assert (await asyncio.wait_for(speak(cpu), 10))[-1]["event"] == "done"
        finally:
            await cpu.unload()

    asyncio.run(run())
    assert not [e for e in fake.log if e[1] == "tts"]


def test_cancelled_in_the_gpu_queue(fake, engine):
    fake.hold("comfy")

    async def run():
        task = asyncio.create_task(speak(engine))
        for _ in range(100):
            if fake.waiting:
                break
            await asyncio.sleep(0.02)
        fake.waiting.clear()                    # the queue's Cancel
        with pytest.raises(engines.EngineError, match="cancelled in the GPU queue"):
            await asyncio.wait_for(task, 10)
        assert engines.WAITING == {}

    asyncio.run(run())
