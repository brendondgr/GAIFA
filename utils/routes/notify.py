"""The `notify` area: `POST /api/notify` (calendar plan 2.1), how a mod tells you something in the app.

A notification is published as a `notification` event (the UI shows a toast with its actions) and kept as an
activity item. `unread` sets the mod's badge (a count on its sidebar item), kept in memory: a mod posts it again
when it starts. Nothing leaves the app."""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from utils.services import ServiceError

router = APIRouter(tags=["events"])


class NotifyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=40)
    op: str = Field(pattern=r"^(POST|PATCH) /[^\s]{1,300}$", description="A route of the same mod, called through the hub's proxy")


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str = Field(description="The mod that tells you")
    title: str | None = Field(None, max_length=200, description="The toast's title; without one only the badge changes")
    body: str | None = Field(None, max_length=1000)
    level: Literal["info", "warn"] = "info"
    route: str | None = Field(None, max_length=500, pattern=r"^#/", description="Where Open goes (a #/ route)")
    key: str | None = Field(None, max_length=100, description="The mod's own id for it (a later toast with the same key replaces it)")
    actions: list[NotifyAction] = Field([], max_length=3)
    unread: int | None = Field(None, ge=0, le=100000, description="The mod's unread count, shown as its badge")


class NotifyOut(BaseModel):
    id: str | None
    badge: int | None


@router.post("/api/notify", summary="A mod tells you something in the app: a toast, an activity item, its badge", response_model=NotifyOut)
async def notify(request: Request, body: NotifyIn) -> dict[str, Any]:
    hub = request.app.state.hub
    mgr = hub.services
    if mgr is None or body.service not in {s.id for s in mgr.list()}:
        raise ServiceError(422, "unknown_service", f"No mod {body.service!r}")
    nid = None
    if body.title:
        nid = uuid.uuid4().hex[:12]
        hub.bus.publish({"type": "notification", "id": nid, "ts": time.time(), "service": body.service, "title": body.title,
                         "body": body.body or "", "level": body.level, "route": body.route, "key": body.key,
                         "actions": [a.model_dump() for a in body.actions]})
        text = body.title if not body.body else f"{body.title}: {body.body}"
        await hub.activity.add(text[:300], body.service, body.level, body.route)
    if body.unread is not None:
        mgr.badges[body.service] = body.unread
        hub.bus.publish({"type": "badge", "service": body.service, "unread": body.unread})
    return {"id": nid, "badge": mgr.badges.get(body.service)}
