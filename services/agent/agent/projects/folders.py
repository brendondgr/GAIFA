"""A project's own folders (plan projects 2.3): kept in a hidden environment of the workspace mod (`project: <pid>`),
made with the first folder, through the hub's proxy. The workspace mod's rules apply unchanged: a folder starts at
Read, the GAIFA folder and `data/models/` stay at Read, secrets are refused; its errors come back as they are."""

from __future__ import annotations

from typing import Any

from ..hubapi import HubCallError

WS = "/api/s/workspace/v1/environments"


def env_id(pid: str) -> str:
    """The hidden environment's id: `proj-<the project id's hex>` (the workspace mod's ids are [a-z0-9._-], ≤ 48)."""
    return "proj-" + pid.removeprefix("p_")


async def folders(agent: Any, p: dict[str, Any]) -> list[dict[str, Any]]:
    if not p.get("own_env"):
        return []
    try:
        return (await agent.hub._json("GET", f"{WS}/{p['own_env']}")).get("folders") or []
    except HubCallError as e:
        if e.status == 404 and e.code == "unknown_environment":     # deleted on the Workspace side: none left
            return []
        raise


async def ensure_env(agent: Any, p: dict[str, Any]) -> str:
    """The project's hidden environment, made the first time ("<project> (project)"; another name when that one is
    taken)."""
    if p.get("own_env"):
        return p["own_env"]
    eid = env_id(p["id"])
    for name in (f"{p['name'][:52]} (project)", f"{p['name'][:40]} (project {p['id'][2:]})"):
        try:
            await agent.hub._json("POST", WS, json={"name": name, "id": eid, "project": p["id"]})
            break
        except HubCallError as e:
            if e.code == "bad_id" and e.status == 422:              # made before, never recorded (a crash between)
                break
            if e.code != "exists":
                raise
    agent.projects.update(p["id"], own_env=eid)
    return eid


async def add(agent: Any, p: dict[str, Any], path: str, level: str) -> dict[str, Any]:
    eid = await ensure_env(agent, p)
    return await agent.hub._json("POST", f"{WS}/{eid}/folders", json={"path": path, "level": level})


async def change(agent: Any, p: dict[str, Any], fid: str, level: str) -> dict[str, Any]:
    return await agent.hub._json("PATCH", f"{WS}/{p['own_env']}/folders/{fid}", json={"level": level})


async def remove(agent: Any, p: dict[str, Any], fid: str) -> dict[str, Any]:
    return await agent.hub._json("DELETE", f"{WS}/{p['own_env']}/folders/{fid}")


async def drop_env(agent: Any, p: dict[str, Any]) -> str:
    """When the project is deleted: its hidden environment goes (the folders' files are left alone)."""
    if not p.get("own_env"):
        return "none"
    await agent.hub._json("DELETE", f"{WS}/{p['own_env']}")
    return p["own_env"]
