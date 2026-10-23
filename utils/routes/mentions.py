"""@-mentions (plan 48.1): `GET /api/mentions?q=&kind=` lists what the user can mention in a message, from the kinds the
mods declare (`[[agent.mentions]]`: a voice, a workflow, an engine). Each choice says which tool fields it fills
("tts_speak.name"); the chat sends the picked ones with the message and the agent pins them on that turn's calls
(utils/tools/pins.py). Outputs (#n) and folders are the chat's own and listed by the chat. Lists are cached 30 s."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter(tags=["mentions"])
CACHE_S = 30
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class Mention(BaseModel):
    kind: str
    id: str
    label: str
    sub: str
    fills: list[str]


def _path(obj: Any, path: str) -> Any:
    for k in [p for p in path.split(".") if p]:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def items_of(body: Any, spec: Any, sid: str, name: str) -> list[dict[str, Any]]:
    """A mod's list answer → mentions, by the spec's rows, value and label."""
    rows = _path(body, spec.rows)
    out = []
    for it in rows if isinstance(rows, list) else []:
        value = it if not spec.value else (it.get(spec.value) if isinstance(it, dict) else None)
        if not isinstance(value, (str, int)) or value == "":
            continue
        label = it.get(spec.label) if spec.label and isinstance(it, dict) else value
        out.append({"kind": spec.kind, "id": str(value), "label": str(label or value), "sub": name,
                    "fills": [f"{sid}_{f}" for f in spec.fills]})
    return out


async def _list(request: Request, svc: Any, spec: Any) -> list[dict[str, Any]]:
    key = f"{svc.id}:{spec.kind}:{spec.list}:{spec.rows}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    method, path = spec.list.split(" ", 1)
    try:
        r = await request.app.state.hub.services.client.request(method, svc.url + path, timeout=10)
        r.raise_for_status()
        items = items_of(r.json(), spec, svc.id, svc.mod.name)
    except Exception:  # noqa: BLE001 - a mod that doesn't answer lists nothing
        items = []
    _cache[key] = (time.monotonic(), items)
    return items


@router.get("/api/mentions", summary="What the user can @-mention: the mods' declared kinds (voice, workflow…), best first",
            response_model=list[Mention])
async def mentions(request: Request, q: str = Query("", description="Words to match in the name"),
                   kind: str | None = Query(None, description="Only this kind"), limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    hub = request.app.state.hub
    out: list[dict[str, Any]] = []
    for svc in hub.services.list():
        if not svc.m or not svc.up:
            continue
        for spec in svc.m.agent.mentions:
            if kind and spec.kind != kind:
                continue
            out += await _list(request, svc, spec)
    ql = q.strip().lower()
    if ql:
        out = [m for m in out if ql in m["label"].lower() or ql in m["id"].lower()]
        out.sort(key=lambda m: (not m["label"].lower().startswith(ql), m["label"].lower()))
    return out[:limit]
