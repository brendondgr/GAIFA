"""Find SearXNG, watch it, change its settings (plan 26.3).

- **Detect:** `SEARXNG_URL`, else 127.0.0.1:8080 and :8888, else the URL of a container whose image
  is `searxng/*`. The container is looked up either way, since its settings file is what changes.
- **Watch:** `/healthz`, `/config` (engines) and `/stats/errors` every `watch_s` (60 s); a test
  query every `query_s` (10 min by default, so the upstream engines aren't asked 1440 times a day).
- **Change:** one at a time: back up `settings.yml` (keeping the newest `keep_backups`), write it, restart the container, wait for
  `/healthz`, run a query (JSON when on, else HTML) and check the change shows in `/config`; when
  any of that fails, put the backup back, restart again and say why.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

import settings as st
from containers import KEEP_BACKUPS, Container, Runtime, RuntimeError_

PROBES = ("http://127.0.0.1:8080", "http://127.0.0.1:8888")
CHECK_QUERY = "gaifa settings check"


class ChangeFailed(Exception):
    """A change that didn't happen, or was rolled back. `code`/`status` for the HTTP error."""

    def __init__(self, detail: str, data: dict[str, Any], code: str = "change_failed", status: int = 409) -> None:
        super().__init__(detail)
        self.detail, self.data, self.code, self.status = detail, data, code, status


class Searx:
    def __init__(self, runtime: Runtime, env_url: str | None = None, probes: tuple[str, ...] = PROBES,
                 watch_s: float = 60, query_s: float = 600, ready_s: float = 60, client: httpx.AsyncClient | None = None,
                 keep_backups: int = KEEP_BACKUPS) -> None:
        self.runtime, self.env_url, self.probes = runtime, (env_url or "").rstrip("/") or None, probes
        self.watch_s, self.query_s, self.ready_s, self.keep_backups = watch_s, query_s, ready_s, keep_backups
        self.http = client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=3), trust_env=False)
        self.url: str | None = None
        self.found_by: str | None = None
        self.container: Container | None = None
        self.health: dict[str, Any] = {"up": None, "checked_ts": None, "detail": "not checked yet"}
        self.last_query: dict[str, Any] | None = None
        self.engines: list[dict[str, Any]] = []
        self.errors: dict[str, list[dict[str, Any]]] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=120)
        self.changes: deque[dict[str, Any]] = deque(maxlen=50)
        self.busy = False
        self.lock = asyncio.Lock()
        self._last_query_ts: float | None = None   # None: no test query yet, so the first round runs one
        self._read_cache: str | None = None      # settings.yml as last read
        self.settings_problem: str | None = None  # why settings.yml can't be used as it is (doesn't parse, …)
        self.answer: str = "none"                 # capability-enablement 5.1: yours | yours_no_json | none, from the last detect

    # ---- detect ------------------------------------------------------------------------------

    async def _answers(self, url: str) -> bool:
        try:
            r = await self.http.get(url + "/healthz", timeout=3)
            if r.status_code == 200:
                return True
            r = await self.http.get(url + "/config", timeout=3)
            return r.status_code == 200 and "engines" in r.json()
        except (httpx.HTTPError, ValueError):
            return False

    async def detect(self, port: int | None = None) -> dict[str, Any]:
        """Find a SearXNG: SEARXNG_URL, else `port` (the user's "mine is on port …") and the usual ports, else a
        `searxng/*` container. The answer (capability-enablement 5.1): `yours` (it answers and gives JSON),
        `yours_no_json` (it answers and refuses JSON), or `none`."""
        self.container = await self.runtime.find()
        url, by = None, None
        probes = ((f"http://127.0.0.1:{port}",) if port else ()) + tuple(p for p in self.probes if not port or not p.endswith(f":{port}"))
        if self.env_url and not port:
            url, by = self.env_url, "SEARXNG_URL"
        else:
            for p in probes:
                if await self._answers(p):
                    url, by = p, "probe"
                    break
            if url is None and self.container and self.container.url and not port:
                url, by = self.container.url, "container"
        if self.container and self.container.url and url and self.container.url.rstrip("/") != url.rstrip("/"):
            # a SearXNG container that isn't the one search uses (yours in Docker while GAIFA's own is chosen): never
            # adjust it from here (the capability-enablement fresh-clone check, 2026-11-16)
            self.container = None
        self.url, self.found_by = url, by
        self.answer = "none" if not url or not await self._answers(url) else ("yours_no_json" if await self._json_refused(url) else "yours")
        return {**self.found(), "answer": self.answer}

    async def _json_refused(self, url: str) -> bool:
        """Does this SearXNG refuse `format=json` (403, the default for a fresh SearXNG)?"""
        try:
            r = await self.http.get(url + "/search", params={"q": CHECK_QUERY, "format": "json"}, timeout=15)
            return r.status_code == 403
        except httpx.HTTPError:
            return False

    def found(self) -> dict[str, Any]:
        c = self.container
        return {"url": self.url, "found_by": self.found_by,
                "container": c.public() if c else None,
                "compose_dir": c.compose_dir if c else None,
                "settings_file": c.settings_host if c else None,
                "can_adjust": bool(c and c.state == "running" and c.settings_host),
                "settings_problem": self.settings_problem}

    # ---- watch -------------------------------------------------------------------------------

    async def check_health(self) -> dict[str, Any]:
        if not self.url:
            self.health = {"up": False, "checked_ts": time.time(), "detail": "no SearXNG found"}
            return self.health
        t0 = time.monotonic()
        try:
            r = await self.http.get(self.url + "/healthz", timeout=5)
            up = r.status_code == 200
            detail = "answers" if up else f"/healthz: HTTP {r.status_code}"
        except httpx.HTTPError as e:
            up, detail = False, f"doesn't answer ({type(e).__name__})"
        self.health = {"up": up, "checked_ts": time.time(), "ms": round((time.monotonic() - t0) * 1000, 1), "detail": detail}
        return self.health

    async def read_engines(self) -> None:
        if not self.url:
            return
        try:
            cfg = (await self.http.get(self.url + "/config", timeout=10)).json()
            errs = (await self.http.get(self.url + "/stats/errors", timeout=10)).json()
        except (httpx.HTTPError, ValueError):
            return
        self.errors = errs if isinstance(errs, dict) else {}
        self.engines = [{"name": e.get("name"), "enabled": bool(e.get("enabled")), "categories": e.get("categories") or [],
                         "shortcut": e.get("shortcut"), "timeout": e.get("timeout"),
                         "errors": [{"type": (x.get("exception_classname") or "").rsplit(".", 1)[-1],
                                     "message": " ".join(map(str, x.get("log_parameters") or [])) or x.get("log_message"),
                                     "percentage": x.get("percentage")} for x in self.errors.get(e.get("name"), [])]}
                        for e in cfg.get("engines") or [] if isinstance(e, dict)]

    async def query(self, fmt: str | None = None) -> dict[str, Any]:
        """A test search: JSON when the format is on, else HTML."""
        if fmt is None:
            fmt = "json" if self.json_on() is not False else "html"
        t0 = time.monotonic()
        try:
            r = await self.http.get(self.url + "/search", params={"q": CHECK_QUERY, "format": fmt}, timeout=30)
            ms = round((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                out = {"ok": False, "format": fmt, "ms": ms, "detail": f"HTTP {r.status_code}" + (" (JSON is off)" if fmt == "json" and r.status_code == 403 else "")}
            elif fmt == "json":
                d = r.json()
                out = {"ok": "results" in d, "format": fmt, "ms": ms, "results": len(d.get("results") or []),
                       "unresponsive": [str(u[0]) if isinstance(u, list) and u else str(u) for u in d.get("unresponsive_engines") or []]}
            else:
                out = {"ok": True, "format": fmt, "ms": ms}
        except (httpx.HTTPError, ValueError) as e:
            out = {"ok": False, "format": fmt, "detail": f"{type(e).__name__}: {e}"[:200]}
        out["ts"] = time.time()
        self.last_query = out
        return out

    def json_on(self) -> bool | None:
        if not self.container:
            return None
        try:
            return st.summary(st.load(self._read_cache))["json"] if self._read_cache is not None else None
        except ValueError:
            return None

    def bad_settings_fix(self, c: Container | None = None) -> str:
        c = c or self.container
        where = (c.settings_host or c.settings_in) if c else "settings.yml"
        newest = self.runtime.backups(c)[:1] if c else []
        back = f", or copy back the newest backup ({newest[0]}) next to it" if newest else ""
        return f"fix {where} by hand{back}; changes wait until it parses (the mod reads it again every minute and on Look again)"

    async def read_settings(self) -> dict[str, Any] | None:
        """settings.yml as this mod adjusts it; None when there's no container, the read fails, or the
        file can't be used (then `settings_problem` says why and where, and changes are refused)."""
        if not self.container:
            return None
        try:
            text = await self.runtime.read(self.container)
        except (OSError, RuntimeError_):
            return None
        except ValueError:    # bytes that aren't UTF-8
            self._read_cache, self.settings_problem = None, "settings.yml isn't UTF-8 text"
            return None
        self._read_cache = text
        try:
            out = st.summary(st.load(text))
        except st.BadSettings as e:
            self.settings_problem = str(e)
            return None
        self.settings_problem = None
        return out

    async def tick(self) -> None:
        """One round of the watch loop."""
        if self.busy:
            return
        await self.check_health()
        await self.read_settings()
        if self.health["up"]:
            await self.read_engines()
            if self._last_query_ts is None or time.monotonic() - self._last_query_ts >= self.query_s:
                self._last_query_ts = time.monotonic()
                await self.query()
        self.history.append({"ts": time.time(), "up": self.health["up"], "ms": self.health.get("ms"),
                             "query_ms": (self.last_query or {}).get("ms")})

    async def watch(self) -> None:
        while True:
            try:
                if self.url is None:
                    await self.detect()
                await self.tick()
            except Exception:  # noqa: BLE001: the loop must keep watching
                pass
            await asyncio.sleep(self.watch_s)

    # ---- change ------------------------------------------------------------------------------

    async def _ready(self) -> tuple[bool, str]:
        deadline = time.monotonic() + self.ready_s
        while time.monotonic() < deadline:
            h = await self.check_health()
            if h["up"]:
                return True, "healthz answers"
            await asyncio.sleep(1)
        return False, f"/healthz didn't answer within {self.ready_s:.0f} s after the restart"

    async def _verify(self, expect: Callable[[dict[str, Any]], str | None] | None, json_expected: bool) -> tuple[bool, str]:
        ok, why = await self._ready()
        if not ok:
            return False, why
        q = await self.query("json" if json_expected else "html")
        if not q["ok"]:
            return False, f"a test search failed: {q.get('detail', 'no results key')}"
        if expect:
            try:
                cfg = (await self.http.get(self.url + "/config", timeout=10)).json()
            except (httpx.HTTPError, ValueError) as e:
                return False, f"/config didn't answer ({type(e).__name__})"
            problem = expect(cfg)
            if problem:
                return False, problem
        await self.read_engines()
        return True, f"SearXNG is up and a test search answered ({q['format']}, {q.get('ms')} ms)"

    async def change(self, label: str, edit: Callable[[Any], None],
                     expect: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
        """Back up, write, restart, check; restore the backup when the check fails."""
        c = self.container
        if not c or not c.settings_host:
            raise ChangeFailed("no SearXNG container with a settings file was found", {"fix": "see the mod's setup doc"})
        if c.state != "running":
            raise ChangeFailed(f"the container {c.name} is {c.state}", {"fix": f"start it: docker start {c.name}"})
        async with self.lock:
            self.busy = True
            try:
                return await self._change(c, label, edit, expect)
            finally:
                self.busy = False

    async def _change(self, c: Container, label: str, edit: Callable[[Any], None],
                      expect: Callable[[dict[str, Any]], str | None] | None) -> dict[str, Any]:
        try:
            before = await self.runtime.read(c)
        except (OSError, RuntimeError_) as e:
            raise ChangeFailed(f"{label}: couldn't read settings.yml ({getattr(e, 'detail', e)}); nothing was changed",
                               {"fix": "check that Docker (or podman) and the container work, then try again"}, "read_failed", 503) from None
        try:
            doc = st.load(before)
        except st.BadSettings as e:
            self.settings_problem = str(e)
            raise ChangeFailed(f"{label}: {e}; nothing was changed", {"fix": self.bad_settings_fix(c)}, "settings_invalid", 409) from None
        edit(doc)
        after = st.dump(doc)
        record: dict[str, Any] = {"ts": time.time(), "label": label}
        if after == before:
            record.update(changed=False, detail="already set")
            self.changes.appendleft(record)
            return record
        json_expected = st.summary(doc)["json"]
        try:
            backup = await self.runtime.backup(c)
        except (OSError, RuntimeError_) as e:
            record.update(changed=False, detail=f"couldn't back up settings.yml: {getattr(e, 'detail', e)}")
            self.changes.appendleft(record)
            raise ChangeFailed(f"{label}: couldn't back up settings.yml ({getattr(e, 'detail', e)}); nothing was changed",
                               {"fix": "check that Docker (or podman) and the container work, then try again"}, "backup_failed", 503) from None
        record["backup"] = backup
        try:   # older backups go; one that won't is no reason to stop the change
            if pruned := await self.runtime.prune(c, self.keep_backups):
                record["pruned"] = pruned
        except (OSError, RuntimeError_) as e:
            record["prune_failed"] = getattr(e, "detail", str(e))
        try:
            await self.runtime.write(c, after)
            await self.runtime.restart(c)
            ok, why = await self._verify(expect, json_expected)
        except RuntimeError_ as e:
            ok, why = False, e.detail
        if ok:
            self._read_cache = after
            record.update(changed=True, detail=why)
            self.changes.appendleft(record)
            return record
        restored = "the backup is back"
        try:
            await self.runtime.restore(c, backup)
            await self.runtime.restart(c)
            ok2, why2 = await self._verify(None, st.summary(st.load(before))["json"])
            restored += f"; after it: {why2}" if ok2 else f", but SearXNG still fails: {why2}"
        except RuntimeError_ as e:
            restored = f"restoring {backup} failed: {e.detail}"
        self._read_cache = before
        record.update(changed=False, rolled_back=True, detail=f"{why}; {restored}")
        self.changes.appendleft(record)
        raise ChangeFailed(f"{label}: {why}; {restored}", {"backup": backup, "fix": "nothing changed; see the mod's logs"})
