"""SearXNG: find the SearXNG on this machine, watch it, adjust its settings (plan 26.3).

GAIFA runs this as `.venv/bin/python server.py` (architecture §4.4). SearXNG itself runs outside
GAIFA (setup/searxng.md); this mod never installs it or changes its network binding. Its only
writes outside the project are SearXNG's `settings.yml` and its backups (containers.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import settings as st
import source as src
from containers import CliRuntime, Runtime
from searx import ChangeFailed, Searx

log = logging.getLogger("searxng")


def error(status: int, code: str, detail: str, fix: str, **data: Any) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code, "fix": fix, **({"data": data} if data else {})}, status_code=status)


class DetectIn(BaseModel):
    port: int | None = Field(None, ge=1, le=65535, description="Look on this port first (\"mine is on port …\")")


class SourceIn(BaseModel):
    source: Literal["yours", "managed"] = Field(description="yours: a SearXNG of yours; managed: GAIFA's own container")
    url: str | None = Field(None, max_length=200, pattern=r"^https?://", description="yours: its URL (default: what detect found)")


class EngineIn(BaseModel):
    enabled: bool = Field(description="true turns the engine on, false off")


class SettingsIn(BaseModel):
    safe_search: Literal[0, 1, 2] | None = Field(None, description="0 off, 1 moderate, 2 strict")
    default_lang: str | None = Field(None, max_length=16, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z]{2})?$|^(all|auto)$",
                                     description="The language searches default to: auto, all, or a code such as en or de-DE")
    request_timeout: float | None = Field(None, ge=0.5, le=30, description="Seconds SearXNG waits for each engine (outgoing.request_timeout)")
    engine_timeouts: dict[str, float] | None = Field(None, description="Per-engine timeouts in seconds, e.g. {\"google\": 5}")
    json_format: Literal[True] | None = Field(None, description="true turns on the JSON format (the web mod needs it)")


def create_app(runtime: Runtime | None = None, env_url: str | None = None, watch_s: float | None = None,
               query_s: float | None = None, ready_s: float = 60) -> FastAPI:
    sx = Searx(runtime or CliRuntime(), env_url if env_url is not None else os.environ.get("SEARXNG_URL"),
               watch_s=watch_s or float(os.environ.get("SEARXNG_WATCH_S", "60")),
               query_s=query_s or float(os.environ.get("SEARXNG_QUERY_S", "600")), ready_s=ready_s)
    started = time.time()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:   # whatever the first look finds, the server starts and says so; the watch loop tries again
            await sx.detect()
            await sx.tick()
        except Exception:  # noqa: BLE001
            log.exception("the first look for SearXNG failed; the watch loop tries again")
        task = asyncio.create_task(sx.watch())
        yield
        task.cancel()   # shutdown never waits long: a watch round stuck in a call, or a pooled connection, can't hold it
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(task, 5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(sx.http.aclose(), 5)

    app = FastAPI(title="SearXNG", version="0.1.0", lifespan=lifespan,
                  description="Finds the SearXNG on this machine, watches it and its engines, and adjusts its settings.")
    app.state.searx = sx

    @app.get("/health")
    def health() -> dict:
        """Up when this server is; SearXNG's own state is in /v1/status."""
        return {"status": "ok"}

    @app.get("/v1/status")
    def status() -> dict:
        failing = [e["name"] for e in sx.engines if e["enabled"] and e["errors"]]
        up = sx.health.get("up")
        return {
            "loaded": None, "busy": sx.busy, "idle_s": round(time.time() - started, 1),
            "stats": [
                {"label": "SearXNG", "value": "up" if up else ("not found" if not sx.url else "down"),
                 "hint": f"{sx.url or 'no URL'}: {sx.health.get('detail')}" + (f"; {sx.settings_problem}" if sx.settings_problem else "")},
                {"label": "Engines on", "value": sum(1 for e in sx.engines if e["enabled"])},
                {"label": "Engines failing", "value": len(failing), "hint": ", ".join(failing[:8]) or "none"},
                {"label": "Test search", "unit": "ms", "value": (sx.last_query or {}).get("ms") or 0,
                 "hint": "ok" if (sx.last_query or {}).get("ok") else (sx.last_query or {}).get("detail", "not run yet")},
            ],
            "jobs": [],
            "found": sx.found(),
        }

    @app.get("/v1/endpoint", summary="The SearXNG URL, for the web mod")
    def endpoint() -> dict:
        """The chosen SearXNG (capability-enablement 5.1: yours, or GAIFA's own), else what detect found; `url` is null
        when there is none, and the web mod then uses its own SEARXNG_URL."""
        chosen = src.load()
        if chosen and chosen.get("url"):
            return {"url": chosen["url"], "found_by": chosen["source"], "up": sx.health.get("up") if chosen["url"] == sx.url else None}
        return {"url": sx.url, "found_by": sx.found_by, "up": sx.health.get("up")}

    @app.get("/v1/source", summary="Which SearXNG search uses: yours or GAIFA's own (null: not chosen yet)")
    def get_source() -> dict:
        return {"chosen": src.load(), "detected": {"url": sx.url, "answer": sx.answer}}

    @app.post("/v1/source", summary="Choose which SearXNG search uses")
    async def set_source(body: SourceIn) -> Any:
        url = body.url or (sx.url if body.source == "yours" else None)
        if body.source == "yours" and not url:
            return error(409, "no_searxng", "no SearXNG of yours was found", "give its URL, or start GAIFA's own")
        saved = src.save(body.source, url)
        if body.source == "yours" and url != sx.url:
            sx.env_url = url
            await sx.detect()
            await sx.tick()
        return {"chosen": saved}

    @app.get("/v1/found", summary="What was found: URL, container, compose folder, settings file")
    def found() -> dict:
        return sx.found()

    @app.post("/v1/detect", summary="Look for SearXNG again: yours (JSON on), yours_no_json, or none")
    async def detect(body: DetectIn | None = None) -> dict:
        out = await sx.detect((body.port if body else None))
        await sx.tick()
        return out

    @app.get("/v1/health", summary="SearXNG's health: /healthz, the last test search, recent history")
    def watch_state() -> dict:
        return {"health": sx.health, "last_query": sx.last_query, "history": list(sx.history)[-60:],
                "watch_s": sx.watch_s, "query_s": sx.query_s}

    @app.post("/v1/health/query", summary="Run a test search now")
    async def test_query() -> dict:
        if not sx.url:
            return error(503, "no_searxng", "no SearXNG was found", "see the mod's setup doc")
        return await sx.query()

    @app.get("/v1/engines", summary="SearXNG's engines: on or off, categories, timeout, recent errors")
    def engines(enabled: bool | None = None, failing: bool | None = None) -> dict:
        rows = [e for e in sx.engines if (enabled is None or e["enabled"] == enabled) and (failing is None or bool(e["errors"]) == failing)]
        return {"engines": rows, "total": len(sx.engines)}

    @app.get("/v1/settings", summary="The settings this mod adjusts, and the backups")
    async def get_settings() -> dict:
        s = await sx.read_settings()
        if s is None and sx.settings_problem:
            return error(409, "settings_invalid", sx.settings_problem, sx.bad_settings_fix(),
                         file=sx.container.settings_host if sx.container else None,
                         backups=sx.runtime.backups(sx.container) if sx.container else [], changes=list(sx.changes))
        if s is None:
            return error(404, "no_settings", "no SearXNG settings file was found", "see the mod's setup doc")
        return {"settings": s, "file": sx.container.settings_host if sx.container else None,
                "backups": sx.runtime.backups(sx.container) if sx.container else [], "changes": list(sx.changes)}

    def _failed(e: ChangeFailed) -> JSONResponse:
        extra = {"backup": e.data["backup"]} if e.data.get("backup") else {}
        return error(e.status, e.code, e.detail, e.data.get("fix", ""), **extra)

    @app.post("/v1/engines/{name}", summary="Turn an engine on or off")
    async def set_engine(name: str, body: EngineIn):
        """Backs up settings.yml, writes it, restarts SearXNG and checks a search works; puts the
        backup back if it doesn't."""
        if sx.engines and name not in {e["name"] for e in sx.engines}:
            return error(404, "no_engine", f"SearXNG has no engine {name!r}", "list them with GET /v1/engines")

        def expect(cfg: dict) -> str | None:
            e = next((x for x in cfg.get("engines") or [] if x.get("name") == name), None)
            if e is None or bool(e.get("enabled")) != body.enabled:
                return f"SearXNG still has {name} {'off' if body.enabled else 'on'} after the restart"
            return None
        try:
            return await sx.change(f"{name} {'on' if body.enabled else 'off'}", lambda d: st.set_engine(d, name, body.enabled), expect)
        except ChangeFailed as e:
            return _failed(e)

    @app.post("/v1/settings", summary="Change SearXNG settings")
    async def set_settings(body: SettingsIn):
        """Safe search, the default language, timeouts and the JSON format. One backup, write,
        restart and check for all of them; the backup goes back if the check fails."""
        given = body.model_dump(exclude_none=True)
        if not given:
            return error(422, "nothing_to_change", "no settings given", "pass at least one field")
        names = {e["name"] for e in sx.engines}
        unknown = [n for n in (body.engine_timeouts or {}) if names and n not in names]
        if unknown:
            return error(404, "no_engine", f"SearXNG has no engine {', '.join(unknown)}", "list them with GET /v1/engines")

        def edit(d: Any) -> None:
            if body.safe_search is not None:
                st.set_safe_search(d, body.safe_search)
            if body.default_lang is not None:
                st.set_default_lang(d, body.default_lang)
            if body.request_timeout is not None:
                st.set_request_timeout(d, body.request_timeout)
            for n, s in (body.engine_timeouts or {}).items():
                st.set_engine_timeout(d, n, s)
            if body.json_format:
                st.enable_json(d)

        def expect(cfg: dict) -> str | None:
            if body.safe_search is not None and cfg.get("safe_search") != body.safe_search:
                return f"SearXNG reports safe_search {cfg.get('safe_search')} after the restart"
            for n, s in (body.engine_timeouts or {}).items():
                e = next((x for x in cfg.get("engines") or [] if x.get("name") == n), {})
                if e.get("timeout") is not None and abs(float(e["timeout"]) - s) > 1e-6:
                    return f"SearXNG reports {n}'s timeout as {e['timeout']} after the restart"
            return None
        try:
            return await sx.change(", ".join(f"{k}={v}" for k, v in given.items()), edit, expect)
        except ChangeFailed as e:
            return _failed(e)

    return app


class _QuietPolls(logging.Filter):
    """GAIFA polls health and status every few seconds; keep them out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f'"GET {p} ' in msg for p in ("/health", "/v1/status"))


if __name__ == "__main__":
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("GAIFA_PORT", "5106")), log_level="info")
