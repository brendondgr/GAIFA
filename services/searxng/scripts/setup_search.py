"""`gaifa setup searxng`'s search steps (plan capability-enablement 5.3): find a SearXNG of yours, use it, turn its JSON
on, or start GAIFA's own.

    python3 scripts/setup_search.py probe          # stdlib only: {"answer": yours | yours_no_json | none, "url": …}
    python3 scripts/setup_search.py is yours       # exit 0 when that is the answer (an ask_if or skip_if)
    python3 scripts/setup_search.py can-manage     # exit 0 when podman or Docker is here (else says how to get one)
    .venv/bin/python scripts/setup_search.py use-yours | json-on | managed

The probe looks at SEARXNG_URL, 127.0.0.1:8080 and :8888. Answers like the mod's own detect (searx.py), without its venv,
so it can run while the plan is made, before anything is installed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PROBES = ("http://127.0.0.1:8080", "http://127.0.0.1:8888")


def _get(url: str, timeout: float = 4) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 - loopback only
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def probe() -> dict:
    env = (os.environ.get("SEARXNG_URL") or "").rstrip("/")
    for url in ([env] if env else []) + [p for p in PROBES if p != env]:
        if _get(url + "/healthz") == 200:
            code = _get(url + "/search?q=gaifa+setup+check&format=json", timeout=15)
            return {"answer": "yours_no_json" if code == 403 else "yours", "url": url}
    return {"answer": "none", "url": None}


def runtime() -> str:
    return os.environ.get("GAIFA_CONTAINER_RUNTIME") or ("podman" if shutil.which("podman") else "docker" if shutil.which("docker") else "")


def _chosen() -> str | None:
    """The source saved before (source.json: yours | managed), read without the mod's venv."""
    sys.path.insert(0, str(HERE))
    try:
        import source as src
        return (src.load() or {}).get("source")
    except Exception:  # noqa: BLE001: nothing chosen yet, or unreadable
        return None


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "probe"
    if cmd == "probe":
        print(json.dumps(probe()))
        return 0
    chosen = _chosen()
    if chosen == "managed" and cmd in ("is", "use-yours"):      # GAIFA's own is already the one search uses: keep it
        print("GAIFA's own SearXNG is the one search uses (chosen before): kept")
        return 1 if cmd == "is" else 0
    if cmd == "is":
        found = probe()
        if found["answer"] == argv[2]:
            return 0
        print(f"the SearXNG here is {found['answer']}" + (f" ({found['url']})" if found["url"] else ""))
        return 1
    if cmd == "can-manage":
        if runtime() and chosen == "managed":
            return 0                                   # chosen before: the step makes sure it exists and runs
        if runtime():
            if probe()["answer"] == "none":
                return 0
            print("a SearXNG of yours answers: GAIFA uses it")
            return 1
        print("neither podman nor Docker is here: install podman (sudo dnf install podman, or sudo apt install podman), then run gaifa setup searxng again")
        return 1
    sys.path.insert(0, str(HERE))
    import asyncio

    import source as src
    if cmd == "use-yours":
        found = probe()
        if found["answer"] == "none":
            print("no SearXNG of yours answers")
            return 0
        src.save("yours", found["url"])
        print(f"Using your SearXNG at {found['url']}")
        return 0
    if cmd == "json-on":
        import settings as st
        from containers import CliRuntime
        from searx import ChangeFailed, Searx

        async def go() -> int:
            sx = Searx(CliRuntime(), probe()["url"])
            await sx.detect()
            try:
                await sx.change("json_format=True", st.enable_json)
            except ChangeFailed as e:
                print(f"couldn't turn JSON on: {e.detail}")
                return 1
            finally:
                await sx.http.aclose()
            src.save("yours", sx.url)
            print(f"JSON is on in your SearXNG at {sx.url}")
            return 0
        return asyncio.run(go())
    if cmd == "managed":
        from managed import Managed, ManagedError

        async def go() -> int:
            try:
                out = await Managed().create()
            except ManagedError as e:
                print(f"{e.detail}: {e.fix}")
                return 1
            print(f"GAIFA's own SearXNG runs at {out['url']}")
            return 0
        return asyncio.run(go())
    print(f"unknown command {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
