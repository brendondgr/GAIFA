"""When a mod is missing (plan capability-enablement 1.1, 2.4): real-world questions on a scratch hub whose `web`
mod is in one broken state per case, scored on how fast the agent gives up and says what is missing.

Cases (each its own scratch root and hub, so one never leaks into the next):
  a  not_set_up  `web`'s folder without its `.venv`
  b  no_searxng  `web` set up, SEARXNG_URL at a port where nothing answers
  c  off         `web` set up and turned off (`[services.web] enabled = false`)
  d  start_fails `web` whose server exits at once

The scratch root lives under --root (a fresh folder per case): `services/agent` is a link to this checkout's agent
(its data, harness versions and database stay in the scratch root), `config.toml` moves the mods to their own ports and
points the agent at --llm. Nothing in this checkout or the installed hub is touched. Run from services/agent:

    .venv/bin/python -m evals.missing --root /tmp/missing --llm http://127.0.0.1:9090/v1 --model default-model \
        --out /tmp/missing.json

The bar (used from 2.4 on): at most 3 model steps and 1 call to the missing mod's tools after its first refusal, no
`workspace_run`/`workspace_python` reaching for the network, and a reply that names what is missing (or answers from
knowledge and says it couldn't check).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[3]
AGENT_DIR = REPO / "services" / "agent"
WEB_DIR = REPO / "services" / "web"
HUB_PORT, AGENT_PORT, WEB_PORT, DEAD_PORT = 7078, 5190, 5192, 5299
QUESTION = "What's the weather in Tallahassee this weekend?"
# what "says web isn't available" looks like in a reply
UNAVAILABLE = ("isn't set up", "is not set up", "not set up", "isn't available", "is not available", "not available",
               "unavailable", "can't search", "cannot search", "can't access the web", "cannot access the web",
               "can't browse", "cannot browse", "no web", "can't check", "cannot check", "couldn't check", "could not check",
               "turned off", "isn't running", "not running", "didn't start", "can't reach", "cannot reach", "couldn't reach",
               "unable to search", "unable to access", "gaifa setup", "isn't currently working", "not currently working",
               "connectivity issues", "connection errors", "don't have direct access", "unable to retrieve", "couldn't retrieve", "wasn't able to", "aren't set up",
               "isn't set up", "currently down", "is down", "can't get the", "cannot get the",
               "technical trouble", "isn't starting", "not starting", "not working", "disabled", "don't have access", "do not have access", "no access", "not connected")
OFFER = ("set it up", "set up", "turn it on", "turn on", "enable", "start it", "want me to")
REFUSALS = ("capability_unavailable", "tool_unavailable", "service_not_running", "not_set_up", "searxng_failed",
            "searxng_unreachable", "unavailable")
NETWORK_SHELL = ("curl", "wget", "requests", "urllib", "httpx", "http://", "https://")


PORTS = {"web": WEB_PORT, "workspace": 5193, "decide": 5194, "embed": 5195, "calendar": 5196}


@dataclass
class Case:
    id: str
    state: str                       # web's state, or the case's name for the 2.4 cases
    question: str = QUESTION
    mod: str = "web"                 # the mod that is missing
    tools: tuple[str, ...] = ("web_search", "web_fetch")
    mods: dict[str, str] = field(default_factory=dict)   # other mods: id → on | not_set_up | off | start_fails | no_searxng
    mode: str = "manual"
    kind: str = "missing"            # missing: says what is missing · auto_answers: Auto without its judge still answers · turns_on: it turns the mod on
    notes: list[str] = field(default_factory=list)


CASES = [Case("a", "not_set_up"), Case("b", "no_searxng", tools=("web_search",)), Case("c", "off", kind="turns_on"), Case("d", "start_fails"),
         # plan 2.4: the other recommended mods
         Case("e", "workspace", "What's in my Documents folder?", "workspace",
              ("workspace_folders", "workspace_tree", "workspace_read", "workspace_run", "workspace_python"), {"workspace": "not_set_up"}),
         Case("f", "decide", QUESTION, "decide", (), {"web": "on", "decide": "not_set_up"}, mode="auto", kind="auto_answers"),
         Case("g", "embed", "Find the chat where we talked about boots for Torres del Paine.", "embed",
              ("embed_library_search", "embed_library_collections", "chat_search"), {"embed": "not_set_up"}),
         Case("h", "calendar", "What's on my calendar tomorrow?", "calendar", ("calendar_agenda",), {"calendar": "off"}, kind="turns_on")]


# --- the scratch root ---------------------------------------------------------------------------------------------


def _link_tree(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> None:
    """`dst` a real folder whose entries link to `src`'s, except `skip` (a mod folder with no `.venv`, say)."""
    dst.mkdir(parents=True)
    for p in src.iterdir():
        if p.name not in skip and p.name != "__pycache__":
            (dst / p.name).symlink_to(p)


def _mod(root: Path, mid: str, state: str) -> list[str]:
    """Put mod `mid` into the scratch root in `state`; its config.toml lines."""
    src, dst = REPO / "services" / mid, root / "services" / mid
    if state == "not_set_up":
        _link_tree(src, dst, skip=(".venv", ".env"))
    elif state == "start_fails":
        _link_tree(src, dst, skip=("server.py", ".env"))
        (dst / "server.py").write_text(f"import sys\nsys.exit('this {mid} mod fails on purpose (evals/missing.py)')\n")
    else:
        _link_tree(src, dst, skip=(".env",))
    lines = [f"[services.{mid}]", f"port = {PORTS[mid]}", *(["enabled = false"] if state == "off" else []), ""]
    if mid == "web":
        lines += ["[services.web.env]", f'SEARXNG_URL = "http://127.0.0.1:{DEAD_PORT}"' if state == "no_searxng" else
                  'SEARXNG_URL = "http://127.0.0.1:8080"', ""]
    return lines


def build_root(root: Path, case: Case, llm: str, model: str) -> Path:
    """A scratch GAIFA root for `case`: the agent linked, its mods in the case's states, `config.toml` with their ports."""
    if root.exists():
        shutil.rmtree(root)
    (root / "services").mkdir(parents=True)
    (root / "web").symlink_to(REPO / "web")
    (root / "services" / "agent").symlink_to(AGENT_DIR)
    mods = dict(case.mods) if case.mods else {"web": case.state}
    cfg = ["[hub]", f"port = {HUB_PORT}", "",
           "[services.agent]", f"port = {AGENT_PORT}", "",
           "[services.agent.env]", f'AGENT_LLM_URL = "{llm}"', f'AGENT_MODEL = "{model}"', ""]
    for mid, state in mods.items():
        cfg += _mod(root, mid, state)
    (root / "config.toml").write_text("\n".join(cfg))
    return root


def start_hub(root: Path, log: Path) -> subprocess.Popen:
    env = {**os.environ, "GAIFA_ROOT": str(root)}
    env.pop("GAIFA_URL", None)
    f = log.open("w")
    return subprocess.Popen(["uv", "run", "--project", str(REPO), "python", str(REPO / "app.py"), "--port", str(HUB_PORT), "--dev"],
                            cwd=REPO, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)


def stop_hub(p: subprocess.Popen) -> None:
    import signal

    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=30)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass


async def wait_ready(hub: str, timeout: float = 120) -> None:
    """The hub answers and its agent is ready."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(base_url=hub, timeout=5, trust_env=False) as c:
        while time.monotonic() < deadline:
            try:
                r = await c.get("/api/services/agent")
                if r.status_code == 200 and r.json().get("state") in ("ready", "degraded"):
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    raise TimeoutError("the scratch hub's agent wasn't ready in time")


# --- scoring --------------------------------------------------------------------------------------------------------


def _code(result: dict[str, Any]) -> str | None:
    err = result.get("error")
    if isinstance(err, dict):
        return err.get("code")
    if result.get("status") not in (None, "done"):
        return result.get("status")
    return None


def score(events: list[dict[str, Any]], case: Case, seconds: float) -> dict[str, Any]:
    """One run's numbers and whether it passes the bar, from its events (also used on recorded transcripts)."""
    pay = lambda t: [e["payload"] for e in events if e["type"] == t]  # noqa: E731
    results = {r["id"]: r for r in pay("tool_result")}
    calls = [c for c in pay("tool_call") if c.get("by", "model") == "model"]
    steps = len(pay("usage"))
    rows, first_refusal_at, after_refusal = [], None, 0
    for i, c in enumerate(calls):
        r = results.get(c["id"]) or {}
        code = _code(r)
        rows.append({"name": c["name"], "code": code})
        if c["name"] in case.tools:
            if first_refusal_at is not None:
                after_refusal += 1
            elif code:
                first_refusal_at = i
    # model steps after the first refusal: usage events after the refusal's result
    steps_after = 0
    if first_refusal_at is not None:
        rid = calls[first_refusal_at]["id"]
        seq = next((e["seq"] for e in events if e["type"] == "tool_result" and e["payload"]["id"] == rid), None)
        steps_after = sum(1 for e in events if e["type"] == "usage" and seq is not None and e["seq"] > seq)
    shell = [c for c in calls if c["name"] in ("workspace_run", "workspace_python")
             and any(w in json.dumps(c.get("arguments") or {}) for w in NETWORK_SHELL)]
    replies = [a.get("text") or "" for a in pay("assistant")]
    reply = (replies[-1] if replies else "").lower()
    says = any(w in reply for w in UNAVAILABLE)
    offers = any(w in reply for w in OFFER)
    ok = (says and (steps_after <= 3) and after_refusal <= 1 and not shell)
    if case.kind == "auto_answers":        # decide not set up in Auto: the fixed rules or a card decide, and the turn answers
        ok = bool(reply.strip()) and not any(e["type"] == "error" for e in events) and steps <= 12
    elif case.kind == "turns_on":          # a turned-off mod: the agent turns it on and answers from it
        on = [c for c in calls if c["name"] == "hub_enable_service" and (c.get("arguments") or {}).get("id") == case.mod] + \
             [n for n in pay("note") if f"turned on {case.mod} " in (n.get("text") or "")]     # 2.4: the agent turns it on itself
        used = [c for c in calls if c["name"] in case.tools and not _code(results.get(c["id"]) or {})]
        ok = bool(on) and bool(used) and bool(reply.strip())
    return {"case": case.id, "state": case.state, "kind": case.kind, "approvals": len(pay("approval")), "steps": steps, "steps_after_refusal": steps_after, "seconds": round(seconds, 1),
            "calls": rows, "calls_after_refusal": after_refusal, "network_shell": len(shell), "says_unavailable": says,
            "offers_to_turn_on": offers, "ok": ok, "reply": (replies[-1] if replies else "")[:400]}


# --- running --------------------------------------------------------------------------------------------------------


async def run_case(case: Case, root: Path, llm: str, model: str, timeout: float) -> dict[str, Any]:
    from .harness import Harness, Task

    root = build_root(root / f"case-{case.id}", case, llm, model)
    hub = f"http://127.0.0.1:{HUB_PORT}"
    proc = start_hub(root, root / "hub.log")
    try:
        await wait_ready(hub)
        h = Harness(f"{hub}/api/s/agent", model, dry_run=False, hub=hub, log=lambda s: None)
        try:
            run = await h.run(Task(f"missing-{case.id}", "missing", [case.question], [], mode=case.mode,
                                   settings={"dry_run": False}, timeout=timeout))
        finally:
            await h.close()
        row = score(run.events, case, run.seconds)
        if run.error:
            row["error"] = run.error
            row["ok"] = False
        return row
    finally:
        stop_hub(proc)


def table(rows: list[dict[str, Any]]) -> str:
    """The markdown table for docs/agent-eval.md."""
    out = ["| Case | Web | Steps | After the first refusal (steps / calls) | Seconds | Tool calls (name: code) | Says what's missing | Pass |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        calls = ", ".join(f"{c['name']}: {c['code'] or 'ok'}" for c in r["calls"]) or "none"
        out.append(f"| {r['case']} | {r['state']} | {r['steps']} | {r['steps_after_refusal']} / {r['calls_after_refusal']} | {r['seconds']} | "
                   f"{calls} | {'yes' if r['says_unavailable'] else 'no'} | {'yes' if r['ok'] else 'no'} |")
    return "\n".join(out)


async def main(a: argparse.Namespace) -> int:
    cases = [c for c in CASES if not a.only or c.id in a.only.split(",")]
    rows = []
    for c in cases:
        for i in range(a.runs):
            row = await run_case(c, Path(a.root), a.llm, a.model, a.timeout)
            row["run"] = i + 1
            rows.append(row)
            print(f"{c.id} {c.state:12} run {i + 1}: {'PASS' if row['ok'] else 'FAIL'} {row['seconds']:6.1f}s "
                  f"steps={row['steps']} calls={[x['name'] + ':' + str(x['code']) for x in row['calls']]}", flush=True)
    print(table(rows))
    if a.out:
        Path(a.out).write_text(json.dumps({"model": a.model, "llm": a.llm, "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="a scratch folder (one root per case is made inside it)")
    p.add_argument("--llm", default="http://127.0.0.1:9090/v1")
    p.add_argument("--model", default="default-model")
    p.add_argument("--only")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--out")
    raise SystemExit(asyncio.run(main(p.parse_args())))
