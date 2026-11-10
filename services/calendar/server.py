"""The calendar mod (calendar plan): events and to-dos, repeats, alerts, plain-words dates, free time, `.ics`,
proposals and the agenda, for you (the Calendar page, the Chat panel) and the agent (its tools).

GAIFA runs this as `.venv/bin/python server.py` with GAIFA_PORT, GAIFA_URL, CALENDAR_DB and CALENDAR_STATE set
(service.toml). Everything is reachable through the hub at /api/s/calendar/…
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from items import Invalid, Items
from proposals import Proposals
from settings import Settings
from store import NotFound, Store


class Calendar:
    """Everything a route needs, on `app.state.cal`."""

    def __init__(self, db: str, state: str, hub_url: str | None = None) -> None:
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(db)
        self.settings = Settings(state)
        self.items = Items(self.store, self.settings)
        self.proposals = Proposals(self)
        self.hub_url = hub_url
        self.alerts: Any = None          # alerts.Alerts, started in the lifespan (plan 2.3)


def create_app(db: str | None = None, state: str | None = None, hub_url: str | None = None,
               background: bool = True) -> FastAPI:
    db = db or os.environ.get("CALENDAR_DB", "data/calendar.db")
    state = state or os.environ.get("CALENDAR_STATE", "data/state")
    hub_url = hub_url if hub_url is not None else os.environ.get("GAIFA_URL")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.cal = Calendar(db, state, hub_url)
        app.state.cal.store.purge()
        from alerts import Alerts
        app.state.cal.alerts = Alerts(app.state.cal)
        if background:
            app.state.cal.alerts.start()
        yield
        await app.state.cal.alerts.stop()

    app = FastAPI(title="Calendar", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(Invalid)
    async def invalid(_: Request, e: Invalid) -> JSONResponse:
        return JSONResponse({"detail": str(e), "code": e.code, **({"data": e.data} if e.data else {})}, status_code=422)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, e: NotFound) -> JSONResponse:
        return JSONResponse({"detail": f"not found: {e.args[0]}", "code": "not_found"}, status_code=404)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/status", summary="Counts, the revision and the next alert")
    def status(request: Request) -> dict:
        cal: Calendar = request.app.state.cal
        s = cal.store
        items = s.db.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0]
        unread = s.db.execute("SELECT COUNT(*) FROM fired WHERE state = 'unread'").fetchone()[0]
        nxt = cal.alerts.next_at() if cal.alerts is not None else None
        return {"loaded": None, "busy": False, "rev": s.rev, "next_alert": nxt,
                "stats": [{"label": "Items", "value": items}, {"label": "Calendars", "value": len(s.calendars())},
                          {"label": "Unread reminders", "value": unread}], "jobs": []}

    import api_agent
    import api_alerts
    import api_items
    import api_more
    app.include_router(api_more.router)          # first: /v1/items/{id}.ics before /v1/items/{id}
    app.include_router(api_items.router)
    app.include_router(api_alerts.router)
    app.include_router(api_agent.router)
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("GAIFA_PORT", "5109")), log_level="warning")
