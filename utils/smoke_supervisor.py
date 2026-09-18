"""Live check of the supervisor with the real llama-server under systemd.

    uv run python utils/smoke_supervisor.py [model] [port]

Launches the model as a transient unit, waits for readiness, runs one chat
completion, prints the footprint and a log tail, stops it, and verifies the
unit is gone and the port is free. Uses a scratch state directory so it never
touches a running lcpp daemon's records.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from lcpp import proc, settings
from lcpp.backends import make_backend
from lcpp.catalog import Catalog
from lcpp.paths import Paths
from lcpp.supervisor import Supervisor


async def main(model: str, port: int) -> int:
    paths = Paths(root=Paths.default().root, state=Path(tempfile.mkdtemp(prefix="lcpp-smoke-")))
    sup = Supervisor(paths, make_backend(paths, "systemd"), settings.load(paths), Catalog.load(paths))
    await sup.start()
    t0 = time.monotonic()
    inst, warnings = await sup.launch({"model_id": model, "port": port, "name": f"smoke-{port}",
                                       "relay": {"enabled": False}}, remember=False)
    print(f"launched {inst.name} pid={inst.pid} warnings={warnings}")
    while inst.state == "starting":
        await asyncio.sleep(0.25)
    print(f"state={inst.state} after {time.monotonic() - t0:.1f}s")
    ok = inst.state == "ready"
    if ok:
        async with httpx.AsyncClient(timeout=120) as c:
            models = (await c.get(f"{inst.url}/models")).json()
            print("models:", [m["id"] for m in models["data"]])
            r = await c.post(f"{inst.url}/chat/completions", json={
                "model": inst.model_id, "max_tokens": 24,
                "messages": [{"role": "user", "content": "Reply with exactly: ok"}]})
            print("completion:", r.json()["choices"][0]["message"].get("content"))
        v = await sup.view(inst)
        print(f"footprint: {(v['rss_bytes'] or 0) / 1024**3:.2f} GB")
    else:
        print("last_error:", inst.last_error)
    for line in sup.logs(inst.name, 5):
        print("  log:", line["text"])
    await sup.stop(inst.name)
    while inst.name in sup.instances:
        await asyncio.sleep(0.1)
    await sup.close()
    unit = subprocess.run(["systemctl", "--user", "show", "-p", "LoadState", "--value",
                           f"lcpp-{inst.name}.service"], capture_output=True, text=True).stdout.strip()
    free = proc.port_free(port)
    print(f"after stop: unit={unit} port_free={free}")
    return 0 if ok and unit == "not-found" and free else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "minicpm",
                              int(sys.argv[2]) if len(sys.argv) > 2 else 7071)))
