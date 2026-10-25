"""A stand-in for GAIFA's GPU queue (plan 31.1), enough for the mod's tests: one holder group, a waiting
list, long-polled acquire. Tests take and give back the slot from their own thread (``hold``/``release``)."""

from __future__ import annotations

import asyncio
import itertools
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class FakeGpu:
    def __init__(self) -> None:
        self.held: dict[str, dict] = {}
        self.waiting: list[dict] = []
        self.log: list[tuple[str, str, str]] = []     # (event, service, class)
        self._n = itertools.count(1)
        self.app = FastAPI()
        self._routes()

    # the test's side -----------------------------------------------------------------

    def hold(self, service: str, label: str = "work", group: str | None = None) -> str:
        lid = f"gl_test{next(self._n)}"
        self.held[lid] = {"id": lid, "service": service, "name": service.title(), "group": group or service,
                          "class": "job", "label": label}
        return lid

    def wait_other(self, service: str) -> str:
        """Another mod's lease starts waiting (as if it asked while the slot is held)."""
        lid = f"gl_test{next(self._n)}"
        self.waiting.append({"id": lid, "service": service, "name": service.title(), "group": service,
                             "class": "job", "label": "work"})
        return lid

    def release(self, lid: str) -> None:
        self.held.pop(lid, None)
        self.waiting = [w for w in self.waiting if w["id"] != lid]
        self._pump()

    def group(self) -> str | None:
        return next(iter(self.held.values()))["group"] if self.held else None

    # the queue ---------------------------------------------------------------------------

    def _pump(self) -> None:
        for w in list(self.waiting):
            if not self.held or self.group() == w["group"]:
                if w["id"].startswith("gl_test"):
                    continue                 # the test's own waiting leases stay waiting until released
                self.waiting.remove(w)
                self.held[w["id"]] = w
                self.log.append(("granted", w["service"], w["class"]))

    def _routes(self) -> None:
        app = self.app

        @app.get("/api/gpu")
        def view() -> dict:
            held = list(self.held.values())
            return {"queue": True, "lease_ttl_s": 60,
                    "holder": {"group": self.group(), "leases": held} if held else None,
                    "waiting": list(self.waiting), "recent": []}

        @app.post("/api/gpu/acquire")
        async def acquire(request: Request, wait: float = 0) -> JSONResponse:
            body = await request.json()
            lid = body.get("lease") or f"gl_{next(self._n)}"
            lease = {"id": lid, "service": body["service"], "name": body["service"].title(),
                     "group": body.get("group") or body["service"], "class": body.get("class", "job"),
                     "label": body.get("label", "")}
            if lid not in self.held and all(w["id"] != lid for w in self.waiting):
                if not self.held or (self.group() == lease["group"] and not self.waiting):
                    self.held[lid] = lease
                    self.log.append(("granted", lease["service"], lease["class"]))
                else:
                    self.waiting.append(lease)
                    self.log.append(("waiting", lease["service"], lease["class"]))
            deadline = time.monotonic() + wait
            while lid not in self.held and time.monotonic() < deadline:
                if all(w["id"] != lid for w in self.waiting):
                    return JSONResponse({"lease": lid, "state": "cancelled"})
                await asyncio.sleep(0.02)
            if lid in self.held:
                return JSONResponse({"lease": lid, "state": "granted"})
            if all(w["id"] != lid for w in self.waiting):
                return JSONResponse({"lease": lid, "state": "cancelled"})
            ahead = [{"service": x["service"], "label": x["label"], "state": "held", "eta_s": 120}
                     for x in self.held.values()]
            return JSONResponse({"lease": lid, "state": "waiting", "ahead": ahead, "eta_s": 120}, status_code=202)

        @app.post("/api/gpu/{lid}/renew")
        def renew(lid: str) -> dict:
            return {"lease": lid, "state": "granted" if lid in self.held else "waiting"}

        @app.post("/api/gpu/{lid}/release")
        def release(lid: str) -> dict:
            lease = self.held.get(lid) or next((w for w in self.waiting if w["id"] == lid), None)
            if lease:
                self.log.append(("released", lease["service"], lease["class"]))
            self.release(lid)
            return {"lease": lid, "state": "released"}

        @app.delete("/api/gpu/{lid}")
        def cancel(lid: str) -> dict:
            self.waiting = [w for w in self.waiting if w["id"] != lid]
            return {"lease": lid, "state": "cancelled"}
