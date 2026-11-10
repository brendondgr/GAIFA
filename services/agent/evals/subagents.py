"""When sub-agents help (plan agent-workflows 5.1): the same tasks with the `agent` tool and without it, graded on the
answer, with the tokens (the chat's and its sub-agents'), the time and the sub-agents started.

Cases where splitting should help (a survey of several files, a comparison of several files) and where it shouldn't be
used (one lookup, two edits that build on each other). Live chats on a hub with the workspace mod, a fixture folder
added at Edit for the run and removed after; sub-agents on or off through the hub's `[agent.workflows] enabled`
(restored after). Run from services/agent with its venv, against a hub whose model is remote (the GPU here does one
thing at a time):

    .venv/bin/python -m evals.subagents --hub http://127.0.0.1:7078 --runs 1 --out /tmp/subagents.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

MODULES = {
    "store.py": "def load(path):\n    return open(path).read().split()\n\n\ndef total(items):\n    return len(items)\n",
    "prices.py": "def price(item, table):\n    return table.get(item, 0)\n\n\ndef discount(amount, pct):\n    return amount * (1 - pct / 100)\n",
    "report.py": "def header(title):\n    return f'# {title}'\n\n\ndef row(name, value):\n    return f'{name}: {value}'\n",
    "cli.py": "import sys\n\n\ndef main(argv=None):\n    args = argv or sys.argv[1:]\n    print(' '.join(args))\n",
}
EDIT_A = "def greet(name):\n    return 'hi ' + name\n"
EDIT_B = "from greet import greet\n\nprint(greet('ann'))\n"


@dataclass
class Case:
    id: str
    kind: str                      # split: sub-agents should help; single: they shouldn't be used
    prompt: str
    grade: Callable[[str, Path], bool]
    mode: str = "accept_edits"
    notes: list[str] = field(default_factory=list)


def has_all(*words: str) -> Callable[[str, Path], bool]:
    return lambda answer, _d: all(w.lower() in answer.lower() for w in words)


def renamed(answer: str, d: Path) -> bool:
    a, b = (d / "greet.py").read_text(), (d / "app.py").read_text()
    return "def welcome(" in a and "welcome" in b and "greet(" not in b.replace("from greet import", "")


CASES = [
    Case("survey", "split", "In the workspace folder {folder}, list every function in each of the four modules in src/ (store.py, "
         "prices.py, report.py, cli.py), one line each saying what it does.",
         has_all("load", "total", "price", "discount", "header", "row", "main")),
    Case("compare", "split", "In the workspace folder {folder}, for each module in src/ say how many functions it defines, then "
         "say which module has a function that takes a percentage.", has_all("discount", "prices")),
    Case("lookup", "single", "In the workspace folder {folder}, what does the function total in src/store.py return?",
         has_all("len")),
    Case("rename", "single", "In the workspace folder {folder}, rename the function greet in lib/greet.py to welcome, then "
         "update its use in lib/app.py to match. Keep the import working.", lambda a, d: renamed(a, d / "lib")),
]


async def fixture(hub: httpx.AsyncClient) -> tuple[str, Path]:
    d = Path(tempfile.mkdtemp(prefix="gaifa-eval-sub-"))
    (d / "src").mkdir()
    (d / "lib").mkdir()
    for name, text in MODULES.items():
        (d / "src" / name).write_text(text)
    (d / "lib" / "greet.py").write_text(EDIT_A)
    (d / "lib" / "app.py").write_text(EDIT_B)
    r = await hub.post("/api/s/workspace/v1/folders", json={"path": str(d), "level": "edit", "id": d.name.lower()[:40]})
    r.raise_for_status()
    return r.json()["id"], d


async def tokens_of(agent: httpx.AsyncClient, tid: str) -> int:
    n = 0
    for e in (await agent.get(f"/v1/threads/{tid}/events")).json():
        if e["type"] == "usage":
            n += int(e["payload"].get("prompt_tokens") or 0) + int(e["payload"].get("completion_tokens") or 0)
    return n


async def run_case(hub: httpx.AsyncClient, agent: httpx.AsyncClient, case: Case, on: bool, timeout: float = 900) -> dict[str, Any]:
    folder, d = await fixture(hub)
    t0 = time.monotonic()
    out: dict[str, Any] = {"case": case.id, "kind": case.kind, "sub_agents": on}
    tid = None
    try:
        r = await agent.post("/v1/threads", json={"mode": case.mode, "settings": {"environment": "default"},
                                                  "message": {"text": case.prompt.format(folder=folder)}})
        r.raise_for_status()
        tid = r.json()["id"]
        while time.monotonic() - t0 < timeout:
            t = (await agent.get(f"/v1/threads/{tid}/tree")).json()
            busy = [t["root"]] + t["children"]
            if all(n["state"] not in ("running", "queued") for n in busy):
                await asyncio.sleep(2)
                t = (await agent.get(f"/v1/threads/{tid}/tree")).json()
                if all(n["state"] not in ("running", "queued") for n in [t["root"]] + t["children"]):
                    break
            await asyncio.sleep(3)
        evs = (await agent.get(f"/v1/threads/{tid}/events")).json()
        answer = next((e["payload"].get("text") or "" for e in reversed(evs) if e["type"] == "assistant"), "")
        kids = t["children"]
        toks = await tokens_of(agent, tid) + sum([await tokens_of(agent, k["id"]) for k in kids])
        out.update(passed=case.grade(answer, d), seconds=round(time.monotonic() - t0, 1), tokens=toks, spawned=len(kids),
                   state=t["root"]["state"], answer=answer[:600])
    except Exception as e:  # noqa: BLE001: one case failing never stops the run
        out.update(passed=False, error=f"{type(e).__name__}: {e}"[:300], seconds=round(time.monotonic() - t0, 1))
    finally:
        if tid:
            await agent.delete(f"/v1/threads/{tid}")
        await hub.delete(f"/api/s/workspace/v1/folders/{folder}")
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in ("split", "single"):
        for on in (True, False):
            rs = [r for r in rows if r["kind"] == kind and r["sub_agents"] is on]
            if not rs:
                continue
            out[f"{kind}/{'on' if on else 'off'}"] = {
                "passed": f"{sum(bool(r.get('passed')) for r in rs)}/{len(rs)}",
                "tokens": round(sum(r.get("tokens", 0) for r in rs) / len(rs)),
                "seconds": round(sum(r.get("seconds", 0) for r in rs) / len(rs), 1),
                "spawned": sum(r.get("spawned", 0) for r in rs)}
    return out


async def main(hub_url: str, runs: int, out: str | None, cases: list[str] | None) -> dict[str, Any]:
    picked = [c for c in CASES if not cases or c.id in cases]
    async with httpx.AsyncClient(base_url=hub_url, timeout=60, trust_env=False) as hub, \
            httpx.AsyncClient(base_url=hub_url + "/api/s/agent", timeout=60, trust_env=False) as agent:
        before = (await hub.get("/api/settings")).json()["workflows"]["enabled"]
        rows = []
        try:
            for on in (True, False):
                await hub.put("/api/settings", json={"workflows": {"enabled": on}})
                await asyncio.sleep(31)                       # the agent reads the limits at most every 30 s
                for _ in range(runs):
                    for c in picked:                          # one at a time: a fair clock for each
                        r = await run_case(hub, agent, c, on)
                        print(json.dumps({k: r.get(k) for k in ("case", "sub_agents", "passed", "spawned", "tokens", "seconds", "error")}), flush=True)
                        rows.append(r)
        finally:
            await hub.put("/api/settings", json={"workflows": {"enabled": before}})
    result = {"runs": runs, "summary": summarise(rows), "rows": rows}
    if out:
        Path(out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hub", default="http://127.0.0.1:7078")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--case", action="append")
    a = ap.parse_args()
    asyncio.run(main(a.hub, a.runs, a.out, a.case))
