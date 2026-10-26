"""`python -m evals.memory [--model skynet] [--llm http://127.0.0.1:4000/v1] [--runs 2] [--out file.json]`

The structured memory's eval (plan structured-memory 6.1). Each scenario seeds a fresh memory, asks one question in a
new chat and checks the answer: a project renamed midway (asked by its old name), a preference that changed, a fact
that ended, a question memory can't answer (the agent must say it doesn't know), and a project's fact reached by an
alias. The agent runs in this process with its own throwaway database and the tests' stand-in hub (so this machine's
memory and chats are never touched); the model is real, through the relay. The stand-in hub's search by meaning
matches words, so this measures what names, keywords, the profile and recall give a small model.

Measures per scenario: right (an expected phrase, none of the stale ones), stale (a replaced or ended value in the
answer), tool calls, prompt tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from agent.loop import Config
from agent.memory.store import MemoryStore
from agent.server import create_app
from tests.conftest import serve
from tests.fakehub import FakeHub


@dataclass
class Scenario:
    id: str
    seed: Callable[[MemoryStore], None]
    question: str
    expect: list[str]                       # one of these (regex, case-insensitive) must be in the answer
    stale: list[str] = field(default_factory=list)   # none of these may be


def _rename(m: MemoryStore) -> None:
    g = m.create_entity("project", "AIHub", summary="the user's local AI hub")
    m.add_fact("Its mods use ports 5100 to 5199", about=[g["id"]])
    m.add_fact("The hub listens on 127.0.0.1:7000", about=[g["id"]])
    m.update_entity(g["id"], name="GAIFA")


def _changed(m: MemoryStore) -> None:
    old = m.add_fact("Prefers 16:9 images", kind="preference")
    m.add_fact("Prefers 4:3 images", kind="preference", replaces=old["id"], valid_from="2026-10-01")


def _ended(m: MemoryStore) -> None:
    m.add_fact("Is in Lisbon this week", valid_until="2020-01-08")
    m.add_fact("Lives in Tallahassee")


def _unknown(m: MemoryStore) -> None:
    m.add_fact("Prefers short replies", kind="preference")
    m.create_entity("project", "Ariadne", summary="a personal website")


def _alias(m: MemoryStore) -> None:
    a = m.create_entity("project", "Ariadne", aliases=["the website"], summary="the user's personal site")
    m.add_fact("Ariadne deploys from the main branch to Netlify", about=[a["id"]])
    for i in range(12):                     # enough other memory that the profile doesn't hold it all
        p = m.create_entity("project", f"Side project {i}")
        m.add_fact(f"Side project {i} is written in language number {i}", about=[p["id"]])


SCENARIOS = [
    Scenario("rename", _rename, "Which ports do AIHub's mods use?", [r"5100"], []),
    Scenario("changed", _changed, "What aspect ratio do I like for images? One short answer.", [r"4\s*:\s*3"], [r"16\s*:\s*9(?!.*4\s*:\s*3)"]),
    Scenario("ended", _ended, "Where am I this week? Answer from what you know about me.",
             [r"don.?t know|not sure|no (record|information)|haven.?t (told|said|mentioned)|Tallahassee|can.?t tell"], [r"Lisbon(?!.*(was|last|earlier|no longer|ended))"]),
    Scenario("abstain", _unknown, "What's my dog's name?",
             [r"don.?t (know|have)|not sure|no (record|information)|haven.?t (told|said|mentioned)|didn.?t (tell|mention)|not (in|something)"], []),
    Scenario("alias", _alias, "Which branch does the website deploy from?", [r"\bmain\b"], [r"\bmaster\b"]),
]


async def run_one(s: Scenario, model: str, llm_url: str, timeout: float = 240) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        hub = FakeHub()
        hs, ht, hport = await serve(hub.app)
        cfg = Config(model=model, data=Path(tmp) / "data" / "agent", default_window=32768, max_steps=6)
        app = create_app(cfg, db=Path(tmp) / "agent.db", hub_url=f"http://127.0.0.1:{hport}", llm_url=llm_url)
        hub.agent_app = app
        t0 = time.time()
        try:
            async with app.router.lifespan_context(app):
                agent = app.state.agent
                s.seed(agent.memory)
                await agent.memory_index.flush()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent", timeout=60) as c:
                    tid = (await c.post("/v1/threads", json={"mode": "auto"})).json()["id"]
                    await c.post(f"/v1/threads/{tid}/messages", json={"text": s.question})
                    deadline = time.monotonic() + timeout
                    await asyncio.sleep(0.2)
                    while agent.running(tid) and time.monotonic() < deadline:
                        await asyncio.sleep(0.5)
                    evs = agent.store.events(tid)
        finally:
            hs.should_exit = True
            await asyncio.gather(ht, return_exceptions=True)
    answer = "\n".join(e["payload"].get("text") or "" for e in evs if e["type"] == "assistant").strip()
    tools = [e["payload"]["name"] for e in evs if e["type"] == "tool_call"]
    usage = [e["payload"] for e in evs if e["type"] == "usage"]
    recalled = next((e["payload"].get("memory") for e in evs if e["type"] == "user"), None)
    right = any(re.search(p, answer, re.I | re.S) for p in s.expect)
    stale = any(re.search(p, answer, re.I | re.S) for p in s.stale)
    return {"id": s.id, "ok": right and not stale, "right": right, "stale": stale, "answer": answer[:600], "tools": tools,
            "recalled": [r["text"] for r in recalled or []], "prompt_tokens": max((u.get("prompt_tokens") or 0 for u in usage), default=0),
            "seconds": round(time.time() - t0, 1)}


async def main(a: argparse.Namespace) -> int:
    rows = []
    for i in range(a.runs):
        for s in SCENARIOS:
            if a.only and s.id not in a.only.split(","):
                continue
            r = await run_one(s, a.model, a.llm)
            r["run"] = i
            rows.append(r)
            print(f"{s.id:8} run {i} {'PASS' if r['ok'] else 'FAIL'} {r['seconds']:5.1f}s tools={r['tools']} "
                  f"tokens={r['prompt_tokens']} recalled={len(r['recalled'])} :: {r['answer'][:140]!r}", flush=True)
    by: dict[str, list[bool]] = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r["ok"])
    summary = {k: f"{sum(v)}/{len(v)}" for k, v in by.items()}
    print("summary:", json.dumps(summary))
    if a.out:
        Path(a.out).write_text(json.dumps({"model": a.model, "rows": rows, "summary": summary}, indent=1))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="skynet")
    p.add_argument("--llm", default="http://127.0.0.1:4000/v1")
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--only", default="")
    p.add_argument("--out", default="")
    raise SystemExit(asyncio.run(main(p.parse_args())))
