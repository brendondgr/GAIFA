"""Eval and test runs leave nothing behind: when a run ends, its chats are deleted from the agent
and the outputs it made (dry-run stand-ins and live results) are deleted from the hub for good
(`DELETE /api/outputs/{id}?permanent=true`, not the trash). Seeds a task's setup wrote into
`outputs/eval/` go when the harness closes. Pass `keep=True` (`--keep`) to look at them afterwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

AGENT_PREFIX = "/api/s/agent"
SEEDED: list[Path] = []     # files the tasks' setups wrote (evals/tasks.py), removed by Harness.close


def hub_of(base: str) -> str | None:
    """The hub's URL from the agent's base when it goes through the hub's proxy, else None."""
    base = base.rstrip("/")
    return base[: -len(AGENT_PREFIX)] if base.endswith(AGENT_PREFIX) else None


def output_ids(events: list[dict[str, Any]]) -> list[str]:
    """Every output a run's tool results made."""
    ids: list[str] = []
    for e in events:
        if e.get("type") != "tool_result":
            continue
        for o in (e.get("payload") or e).get("outputs") or []:
            oid = o.get("output_id") or o.get("id")
            if oid and oid not in ids:
                ids.append(str(oid))
    return ids


async def forget(agent: httpx.AsyncClient, hub: httpx.AsyncClient | None, threads: list[str],
                 events: list[dict[str, Any]]) -> None:
    """Delete the run's outputs (from its events) and its threads. Failures are ignored."""
    if hub is not None:
        for oid in output_ids(events):
            try:
                await hub.delete(f"/api/outputs/{oid}", params={"permanent": "true"})
            except httpx.HTTPError:
                pass
    for tid in threads:
        try:
            await agent.delete(f"/v1/threads/{tid}")
        except httpx.HTTPError:
            pass


def remove_files(paths: list[Path]) -> None:
    """Seed files a task's setup wrote, with their sidecars and cached previews."""
    for p in paths:
        for f in (p, p.with_name(p.name + ".json"), p.with_name(f".{p.name}.preview.jpg")):
            f.unlink(missing_ok=True)


async def forget_threads(threads: list[str], base: str = "http://127.0.0.1:7000" + AGENT_PREFIX) -> None:
    """For the one-off checks (`compact_live`, `meter_check`, `restart_live`): read each thread's
    events for its outputs, then delete them and the threads."""
    hub_url = hub_of(base)
    async with httpx.AsyncClient(base_url=base, timeout=60, trust_env=False) as agent, \
            httpx.AsyncClient(base_url=hub_url or base, timeout=60, trust_env=False) as hub:
        events: list[dict[str, Any]] = []
        for tid in threads:
            try:
                events += (await agent.get(f"/v1/threads/{tid}/events")).json()
            except (httpx.HTTPError, ValueError):
                pass
        await forget(agent, hub if hub_url else None, threads, events)
