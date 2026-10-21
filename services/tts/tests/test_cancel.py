"""A request whose client goes away is cancelled in the worker, not run to its end."""

import asyncio
import sys
import time
from pathlib import Path

from localtts import engines

# A worker on the real protocol that would talk for ~100 s unless cancelled.
WORKER = """
import sys, time
sys.path.insert(0, {workers!r})
import _proto
_proto.claim_stdout()

def generate(text, request_id="req", **_):
    sent = 0
    for _ in range(10_000):
        if _proto.cancelled(request_id):
            break
        _proto.send_audio([0.0] * 240)
        sent += 1
        time.sleep(0.01)
    _proto.send("done", audio_s=sent * 0.01, cancelled=_proto.cancelled(request_id))

_proto.send("ready", sample_rate=24000)
_proto.serve({{"generate": generate}})
"""


def test_an_abandoned_request_stops_in_the_worker(tmp_path, monkeypatch):
    script = tmp_path / "slow_worker.py"
    script.write_text(WORKER.format(workers=str(engines.WORKERS)))
    monkeypatch.setattr(engines, "DRAIN_TIMEOUT_S", 5.0)
    engine = engines.Engine("slow", Path(sys.executable), str(script))

    async def run():
        try:
            gen = engine.generate(request_id="first", text="a long text")
            assert isinstance(await anext(gen), bytes)
            await gen.aclose()                      # the client went away after one chunk
            assert engine._stale
            pid = engine.proc.pid
            t0 = time.monotonic()
            gen = engine.generate(request_id="second", text="next")
            assert isinstance(await anext(gen), bytes)   # the leftovers were read off quickly...
            await gen.aclose()
            assert time.monotonic() - t0 < 3
            assert engine.alive and engine.proc.pid == pid   # ...without restarting the worker
        finally:
            await engine.unload()

    asyncio.run(run())
