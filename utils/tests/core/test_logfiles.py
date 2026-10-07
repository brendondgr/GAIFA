"""16.1: mods' output in data/logs/<id>.log (rotated), the hub's own log, and the Logs tab reading
the files."""

from __future__ import annotations

import asyncio
import logging
import time

from utils.logfiles import LogFiles, fmt, parse
from utils.tests.tools.conftest import wait_ready


def test_format_round_trip_and_rotation(tmp_path):
    lf = LogFiles(tmp_path, max_bytes=2000, keep=3)
    line = {"ts": time.time(), "text": "hello\nworld", "stream": "stderr"}
    back = parse(fmt(line))
    assert back["text"] == "hello ⏎ world" and back["stream"] == "stderr" and abs(back["ts"] - line["ts"]) < 0.01
    for i in range(200):
        lf.append("m", [{"ts": time.time(), "text": f"line {i:03d} " + "x" * 30, "stream": "stdout"}])
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["m.log", "m.log.1", "m.log.2", "m.log.3"]          # 3 old files kept, no more
    assert all(p.stat().st_size <= 2100 for p in tmp_path.iterdir())
    last = lf.read("m", 60)
    assert len(last) == 60 and last[-1]["text"].startswith("line 199") and last[0]["text"].startswith("line 140")
    assert lf.read("nope", 10) == []


async def test_mod_output_is_shipped_and_read_back(services_dir, root, make_app):
    import re

    import httpx

    from utils.tests.conftest import free_port

    services = services_dir("fake-ok")
    toml = services / "fake-ok" / "service.toml"
    toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text()))
    app = make_app(port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            await wait_ready(c, "fake-ok")
            for i in range(3):
                await c.post("/api/s/fake-ok/v1/echo", json={"i": i})
            logging.getLogger("aihub.test").setLevel(logging.INFO)
            logging.getLogger("aihub.test").info("a line for the hub's own log")
            f = root / "data" / "logs" / "fake-ok.log"
            for _ in range(60):
                if f.exists() and "POST /v1/echo" in f.read_text():
                    break
                await asyncio.sleep(0.1)
            assert "POST /v1/echo" in f.read_text()
            lines = (await c.get("/api/services/fake-ok/logs?lines=50")).json()["lines"]
            assert any("POST /v1/echo" in x["text"] for x in lines)
    assert "a line for the hub's own log" in (root / "data" / "logs" / "aihub.log").read_text()
