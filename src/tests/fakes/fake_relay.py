"""A minimal DashLLM relay: the registration contract from its Step 7 API.

Matching mirrors the real one: by key, else adopt an unowned endpoint with
the same base_url (keeping its alias), else create. Alias clashes are 409;
models routed elsewhere are skipped. Endpoints report ``healthy``.
"""

from __future__ import annotations

import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException, Response


def make_relay():
    app = FastAPI()
    eps: dict[str, dict] = {}  # id -> endpoint
    app.state.eps = eps
    app.state.calls = []

    def out(e: dict) -> dict:
        return {**e, "health": "healthy"}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/admin/endpoints")
    def endpoints():
        return [out(e) for e in eps.values()]

    @app.get("/v1/models")
    def models():
        ids = ["auto"]
        for e in eps.values():
            if e.get("alias"):
                ids.append(e["alias"])
            ids.extend(e.get("available_models") or [])
        return {"data": [{"id": i} for i in ids]}

    @app.get("/admin/registrations")
    def registrations(owner: str | None = None):
        return [{"key": e["external_key"], "owner": e["owner"], "endpoint": out(e)}
                for e in eps.values() if e.get("external_key") and (owner is None or e["owner"] == owner)]

    @app.put("/admin/registrations/{key}")
    def upsert(key: str, body: dict):
        app.state.calls.append(("PUT", key))
        url = body.get("base_url") or f"http://{body.get('host', '127.0.0.1')}:{body['port']}/v1"
        row = next((e for e in eps.values() if e.get("external_key") == key), None)
        adopted = False
        if row is None:
            row = next((e for e in eps.values() if not e.get("owner") and e["base_url"] == url), None)
            adopted = row is not None
        alias = body.get("alias")
        if adopted and row.get("alias"):
            alias = row["alias"]
        for e in eps.values():
            if e is not row and alias and (e.get("alias") or "").lower() == alias.lower():
                raise HTTPException(409, f"alias {alias!r} already used by endpoint {e['name']!r}")
        taken = {m.lower() for e in eps.values() if e is not row for m in (e.get("available_models") or [])}
        wanted = body.get("available_models") or []
        models = [m for m in wanted if m.lower() not in taken]
        if row is None:
            row = {"id": str(uuid.uuid4()), "name": body["name"]}
            eps[row["id"]] = row
        if not adopted:
            row["name"] = body["name"]
        row.update(alias=alias, base_url=url, available_models=models, owner=body.get("owner"),
                   external_key=key, meta=body.get("meta") or {}, server_type=body.get("server_type"))
        return {"key": key, "owner": row["owner"], "adopted": adopted,
                "skipped_models": [m for m in wanted if m not in models], "endpoint": out(row)}

    @app.delete("/admin/registrations/{key}")
    def delete(key: str):
        app.state.calls.append(("DELETE", key))
        for eid, e in list(eps.items()):
            if e.get("external_key") == key:
                del eps[eid]
        return Response(status_code=204)

    def add_manual(name: str, base_url: str, alias: str | None = None, models=None) -> dict:
        row = {"id": str(uuid.uuid4()), "name": name, "base_url": base_url, "alias": alias,
               "available_models": models or [], "owner": None, "external_key": None,
               "meta": None, "server_type": "openai"}
        eps[row["id"]] = row
        return row

    app.state.add_manual = add_manual
    return app


class RelayServer:
    """Run the fake relay on a fixed port in a thread; start/stop at will."""

    def __init__(self, port: int):
        self.port = port
        self.app = make_relay()
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> "RelayServer":
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(5)

    @property
    def regs(self) -> dict[str, dict]:
        return {e["external_key"]: e for e in self.app.state.eps.values() if e.get("external_key")}
