"""Instance lifecycle: plan, launch, readiness, exit detection, stop, reconcile.

Resource use at idle is the design constraint. With no instances there is no
task, timer or poll of any kind. A *starting* instance is polled on
``/health`` every half second until ready. A *ready* instance costs nothing:
its exit is detected through a pidfd registered with the event loop, which
wakes the daemon only when the process actually ends.

Hooks (the relay registrar is one) are told when an instance becomes ready,
starts stopping, and is gone, and are never allowed to break the lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol
from urllib.parse import urlparse

import httpx

from lcpp import gguf, proc, settings as settings_mod
from lcpp.backends import Backend, LogLine
from lcpp.catalog import Catalog, CatalogError, ModelEntry
from lcpp.cmdline import render_preset, reserved_keys, router_argv, single_argv, single_params
from lcpp import gaifa
from lcpp.instances import NAME_RE, Instance, InstanceStore, LcppError, relay_off
from lcpp.paths import Paths, write_atomic

log = logging.getLogger("lcpp.supervisor")

READY_TIMEOUT_S = 900
HEALTH_INTERVAL_S = 0.5
PID_POLL_S = 1.0  # only without pidfd (see _exit_future)
ERROR_LINE_RE = re.compile(r"error|failed|fatal|abort|out of memory|exception", re.IGNORECASE)
# Follow-on lines llama.cpp prints after the real cause; only used as a fallback.
GENERIC_ERROR_RE = re.compile(r"failed to load model|error loading model$|exiting due to", re.IGNORECASE)
RECENT_MAX = 5


class Hook(Protocol):
    async def instance_ready(self, inst: Instance) -> None: ...
    async def instance_stopping(self, inst: Instance) -> None: ...
    async def instance_gone(self, inst: Instance) -> None: ...


@dataclass
class Plan:
    preflight: dict[str, Any]
    spec: dict[str, Any]
    entries: list[ModelEntry]
    name: str
    port: int
    argv: list[str]
    params: dict[str, Any]
    preset: str | None


def _exit_future(pid: int | None) -> asyncio.Future[None]:
    """Resolves when ``pid`` exits, via pidfd: no polling, no child relationship needed."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[None] = loop.create_future()
    if not pid:
        fut.set_result(None)
        return fut
    if not hasattr(os, "pidfd_open"):  # some Python builds (e.g. uv's standalone CPython) lack it
        task = loop.create_task(_poll_exit(pid, fut))
        fut.add_done_callback(lambda _: task.cancel())
        return fut
    try:
        fd = os.pidfd_open(pid)
    except (ProcessLookupError, OSError):
        fut.set_result(None)
        return fut
    closed = False

    def close() -> None:
        nonlocal closed
        if not closed:
            closed = True
            loop.remove_reader(fd)
            os.close(fd)

    def on_exit() -> None:
        close()
        if not fut.done():
            fut.set_result(None)

    loop.add_reader(fd, on_exit)
    fut.add_done_callback(lambda _: close())
    return fut


def _pid_gone(pid: int) -> bool:
    """True once ``pid`` has exited (a zombie counts as exited, as it does for a pidfd)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except (OSError, IndexError):
        return True


async def _poll_exit(pid: int, fut: asyncio.Future[None]) -> None:
    """Fallback for ``_exit_future`` without pidfd: checks once a second, only while awaited."""
    while not _pid_gone(pid):
        await asyncio.sleep(PID_POLL_S)
    if not fut.done():
        fut.set_result(None)


def normalize_spec(raw: Any, auto_register: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LcppError("invalid_param", "launch spec must be an object")
    kind = raw.get("kind") or "single"
    if kind not in ("single", "router"):
        raise LcppError("invalid_param", "kind must be 'single' or 'router'", field="kind")
    port = raw.get("port")
    if port in ("", None):
        port = None
    elif isinstance(port, bool) or not isinstance(port, int):
        raise LcppError("invalid_param", "port must be an integer", field="port")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise LcppError("invalid_param", "params must be an object", field="params")
    relay = raw.get("relay")
    relay = relay if isinstance(relay, dict) else {}
    models_max = raw.get("models_max") or 1
    if not isinstance(models_max, int) or models_max < 1:
        raise LcppError("invalid_param", "models_max must be a positive integer", field="models_max")
    model_ids = raw.get("model_ids") or []
    if not isinstance(model_ids, list):
        raise LcppError("invalid_param", "model_ids must be a list", field="model")
    name = (raw.get("name") or "").strip() or None
    return {
        "kind": kind,
        "model_id": raw.get("model_id") if kind == "single" else None,
        "model_ids": [str(m) for m in model_ids] if kind == "router" else [],
        "models_max": models_max if kind == "router" else 1,
        "port": port,
        "name": name,
        "params": {str(k).removeprefix("--"): v for k, v in params.items()},
        "relay": {
            "enabled": bool(relay.get("enabled", auto_register)),
            "alias": (relay.get("alias") or "").strip() or None,
        },
        "save_preset": (raw.get("save_preset") or "").strip() or None,
    }


def boot_time() -> float:
    """When the machine booted (/proc/stat btime); 0 when unknown."""
    try:
        for line in open("/proc/stat"):
            if line.startswith("btime "):
                return float(line.split()[1])
    except OSError:
        pass
    return 0.0


def _before_boot(started_ts: float | None) -> bool:
    return bool(started_ts) and started_ts < boot_time()


def _auto_name(base: str, port: int) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "model"
    return f"{slug[:40]}-{port}"


class Supervisor:
    def __init__(self, paths: Paths, backend: Backend, settings: dict[str, Any], catalog: Catalog):
        self.paths = paths
        self.backend = backend
        self.settings = settings
        self.catalog = catalog
        self.store = InstanceStore(paths.instances)
        self.instances: dict[str, Instance] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.hooks: list[Hook] = []
        # Set by the relay registrar: True/False once known, None before.
        self.relay_reachable: bool | None = None
        self.lock = asyncio.Lock()
        self.http: httpx.AsyncClient | None = None
        self._router_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # ---- lifecycle of the supervisor itself ---------------------------
    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=1.0))
        await self.reconcile()

    async def close(self) -> None:
        """Stop watching. Instances keep running (they are not our children)."""
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        if self.http:
            await self.http.aclose()

    async def reconcile(self) -> None:
        """Rebuild state after a daemon restart from records + live units."""
        for inst in self.store.load_all():
            st = await asyncio.to_thread(self.backend.status, inst.name)
            self.instances[inst.name] = inst
            if inst.state == "failed":
                continue
            if st.active:
                inst.pid = st.pid
                if inst.state == "stopping":
                    self._spawn(inst.name, self._stop_task(inst))
                else:
                    self._spawn(inst.name, self._monitor(inst))
                continue
            if inst.state == "stopping" or _before_boot(inst.started_ts):
                # Stopped on purpose, or the machine rebooted since it started: the record is stale
                # (state lives in GAIFA's data/state/ now, which survives reboots; plan 16.2). A
                # session restore relaunches what should run.
                self._forget(inst)
                await self._emit("instance_gone", inst)
                continue
            await self._mark_failed(inst, "exited while the lcpp daemon was not running")
        known = set(self.instances)
        for name in await asyncio.to_thread(self.backend.active_names):
            if name not in known:
                log.warning("unit lcpp-%s is running without an lcpp record; leaving it alone", name)

    # ---- hooks ----------------------------------------------------------
    async def _emit(self, event: str, inst: Instance) -> None:
        for hook in self.hooks:
            try:
                await getattr(hook, event)(inst)
            except Exception:  # noqa: BLE001 - a hook must never break the lifecycle
                log.exception("hook %s failed for %s", event, inst.name)

    def _spawn(self, name: str, coro: Any) -> None:
        old = self.tasks.pop(name, None)
        # A restart relaunches from inside its own task; never cancel the caller.
        if old and not old.done() and old is not asyncio.current_task():
            old.cancel()
        task = asyncio.create_task(coro)
        self.tasks[name] = task
        task.add_done_callback(lambda t, n=name: self.tasks.pop(n, None) if self.tasks.get(n) is t else None)

    def save(self, inst: Instance) -> None:
        if inst.name in self.instances:
            self.store.save(inst)

    def _forget(self, inst: Instance) -> None:
        self.instances.pop(inst.name, None)
        self.store.delete(inst.name)
        self._router_cache.pop(inst.name, None)

    # ---- ports & names ---------------------------------------------------
    def reserved_ports(self) -> dict[int, str]:
        out = {self.settings["daemon"]["port"]: "reserved (lcpp daemon)"}
        relay = urlparse(self.settings["relay"]["url"])
        if relay.hostname in ("127.0.0.1", "localhost", "::1") and relay.port:
            out[relay.port] = "reserved (Relay)"
        return out

    def port_check(self, port: int) -> tuple[bool, str | None, str | None]:
        """(ok, reason, code)"""
        if not 1024 <= port <= 65535:
            return False, "outside 1024–65535", "invalid_param"
        reserved = self.reserved_ports()
        if port in reserved:
            return False, reserved[port], "port_reserved"
        for inst in self.instances.values():
            if inst.port == port and inst.state != "failed":
                return False, f"in use by lcpp instance {inst.name}", "port_in_use"
        if not proc.port_free(port):
            return False, f"in use by {proc.port_owner(port) or 'another process'}", "port_in_use"
        return True, None, None

    def suggest_port(self) -> int:
        start, end = self.settings["ports"]["start"], self.settings["ports"]["end"]
        for port in range(start, end + 1):
            if self.port_check(port)[0]:
                return port
        raise LcppError("port_in_use", f"no free port in {start}–{end}", 409, "port")

    def _resolve_target(self, target: str) -> Instance:
        """An instance by name, or by port when ``target`` is a number."""
        inst = self.instances.get(target)
        if inst is None and str(target).isdigit():
            inst = next((i for i in self.instances.values() if i.port == int(target)), None)
        if inst is None:
            raise LcppError("instance_not_found", f'Instance "{target}" not found', 404)
        return inst

    get = _resolve_target

    # ---- planning ----------------------------------------------------------
    def estimate_bytes(self, entry: ModelEntry, params: dict[str, Any]) -> int:
        size = self.catalog.size_bytes(entry)
        try:
            meta = gguf.read_metadata(self.paths.model(entry.path))
            kv = gguf.kv_cache_bytes(
                meta, int(params.get("ctx-size") or 4096),
                str(params.get("cache-type-k") or "f16"), str(params.get("cache-type-v") or "f16"),
                int(params.get("parallel") or 1) if str(params.get("parallel") or "1").lstrip("-").isdigit() else 1)
        except (OSError, ValueError, EOFError):
            kv = None
        # Compute buffers and runtime overhead on top of weights + KV.
        return size + (kv or 0) + 512 * 1024**2

    def plan(self, raw_spec: Any) -> Plan:
        spec = normalize_spec(raw_spec, self.settings["relay"]["auto_register"])
        errors: list[dict[str, str]] = []
        warnings: list[str] = []

        def err(code: str, detail: str, fld: str) -> None:
            errors.append({"code": code, "detail": detail, "field": fld})

        entries: list[ModelEntry] = []
        if spec["kind"] == "single":
            if not spec["model_id"]:
                err("model_not_found", "Choose a model", "model")
            else:
                try:
                    entries = [self.catalog.resolve(str(spec["model_id"]))]
                except CatalogError as e:
                    err(e.code, str(e), "model")
        else:
            if spec["model_ids"]:
                for mid in spec["model_ids"]:
                    try:
                        entries.append(self.catalog.resolve(mid))
                    except CatalogError as e:
                        err(e.code, str(e), "model")
            else:
                entries = [m for m in self.catalog.models.values() if not self.catalog.problems(m)]
            if not entries and not errors:
                err("model_not_found", "A router needs at least one model", "model")
        for entry in entries:
            problems = self.catalog.problems(entry)
            if problems:
                err("model_files_missing", f"{entry.id}: {problems[0]}", "model")
        bad = reserved_keys(spec["params"])
        if bad:
            err("invalid_param", f"--{bad[0]} is managed by lcpp and cannot be overridden", "params")

        port = spec["port"] or self.suggest_port()
        port_ok, port_reason, port_code = self.port_check(port)
        if not port_ok:
            err(port_code or "port_in_use", f"Port {port}: {port_reason}", "port")

        base = "router" if spec["kind"] == "router" else (entries[0].nick if entries else "model")
        name = spec["name"] or _auto_name(base, port)
        name_ok, name_reason = True, None
        if not NAME_RE.match(name):
            name_ok, name_reason = False, "lowercase letters, digits and dashes; 1–48 chars"
            err("invalid_name", f'Name "{name}": {name_reason}', "name")
        elif name in self.instances:
            name_ok, name_reason = False, "already used by an instance"
            err("name_taken", f'Name "{name}": {name_reason}', "name")

        # Memory: a router can only ever hold its models_max largest models.
        if spec["kind"] == "router":
            loaded = sorted(entries, key=self.catalog.size_bytes, reverse=True)[: spec["models_max"]]
        else:
            loaded = entries
        estimate = sum(self.estimate_bytes(e, self.catalog.effective(e, spec["params"])) for e in loaded)
        available = proc.meminfo()["available_bytes"]
        gb = 1024**3
        if estimate > available:
            warnings.append(f"Estimated {estimate / gb:.1f} GB needed, {available / gb:.1f} GB available. "
                            "Loading may fail or swap.")
        elif estimate > available * 0.85:
            warnings.append(f"Estimated {estimate / gb:.1f} GB needed, {available / gb:.1f} GB available. "
                            "Little headroom for other work.")
        if spec["relay"]["enabled"] and self.relay_reachable is False:
            warnings.append("Relay is unreachable. The instance will register when Relay comes back.")

        preset = None
        if spec["kind"] == "single":
            if entries:
                argv = single_argv(self.paths, self.settings, self.catalog, entries[0], port, spec["params"])
                params = single_params(self.catalog, self.settings, entries[0], spec["params"])
            else:
                argv, params = [], {}
        else:
            preset_path = self.paths.generated / f"{name}.ini"
            preset = render_preset(self.paths, self.catalog, entries, spec["params"])
            argv = router_argv(self.paths, self.settings, preset_path, port, spec["models_max"])
            params = {**self.settings["llama"]["server_params"], **self.catalog.defaults,
                      **spec["params"], "models-max": spec["models_max"]}

        preflight = {
            "port": port, "port_ok": port_ok, "port_reason": port_reason,
            "suggested_port": self._suggest_or(port), "name": name, "name_ok": name_ok,
            "name_reason": name_reason, "estimated_bytes": estimate, "available_bytes": available,
            "warnings": warnings, "errors": errors, "argv": argv,
        }
        return Plan(preflight, spec, entries, name, port, argv, params, preset)

    def _suggest_or(self, fallback: int) -> int:
        try:
            return self.suggest_port()
        except LcppError:
            return fallback

    def preflight(self, raw_spec: Any) -> dict[str, Any]:
        return self.plan(raw_spec).preflight

    # ---- launch ---------------------------------------------------------------
    async def launch(self, raw_spec: Any, remember: bool = True,
                     make_room: bool = False) -> tuple[Instance, list[str]]:
        """``make_room``: under GAIFA, let it unload other mods if the memory isn't free."""
        async with self.lock:
            plan = await asyncio.to_thread(self.plan, raw_spec)
            if plan.preflight["errors"]:
                first = plan.preflight["errors"][0]
                status = 404 if first["code"] == "model_not_found" else 409
                raise LcppError(first["code"], first["detail"], status, first["field"])
            # Under GAIFA: ask for the memory first (raises needs_room with GAIFA's plan).
            await gaifa.acquire(plan.preflight["estimated_bytes"], make_room, f"launch {plan.name}")
            spec = plan.spec
            if plan.preset is not None:
                write_atomic(self.paths.generated / f"{plan.name}.ini", plan.preset)
            entry = plan.entries[0] if spec["kind"] == "single" else None
            relay = relay_off()
            if spec["relay"]["enabled"]:
                relay.update(enabled=True, state="pending", key=f"lcpp:{plan.port}",
                             alias=spec["relay"]["alias"] or (entry.nick if entry else plan.name))
            inst = Instance(
                name=plan.name, kind=spec["kind"], port=plan.port,
                spec={**spec, "name": plan.name, "port": plan.port, "save_preset": None},
                model_id=entry.id if entry else None,
                model_ids=[e.id for e in plan.entries] if spec["kind"] == "router" else [],
                models_max=spec["models_max"], params=plan.params, argv=plan.argv,
                capabilities={"vision": bool(entry and entry.mmproj),
                              "speculative": bool(entry and entry.draft)},
                relay=relay, started_ts=time.time(),
            )
            self.instances[inst.name] = inst
            self.store.save(inst)
            try:
                launched = await asyncio.to_thread(
                    self.backend.launch, inst.name, plan.argv,
                    dict(self.settings["llama"]["environment"]), self.paths.root)
            except Exception as e:
                self._forget(inst)
                raise LcppError("daemon_error", f"could not start {inst.name}: {e}", 500) from e
            inst.pid, inst.invocation = launched.pid, launched.invocation
            self.save(inst)
            if remember:
                self._remember(raw_spec, spec)
            self._spawn(inst.name, self._monitor(inst))
            return inst, plan.preflight["warnings"]

    async def _monitor(self, inst: Instance) -> None:
        if inst.state == "starting" and not await self._wait_ready(inst):
            return
        await _exit_future(inst.pid)
        if inst.state in ("ready", "starting") and self.instances.get(inst.name) is inst:
            await self._mark_failed(inst)

    async def _wait_ready(self, inst: Instance) -> bool:
        exited = _exit_future(inst.pid)
        deadline = time.monotonic() + READY_TIMEOUT_S
        assert self.http is not None
        try:
            while time.monotonic() < deadline:
                if inst.state != "starting":
                    return False
                if exited.done():
                    await self._mark_failed(inst)
                    return False
                try:
                    r = await self.http.get(f"{inst.base}/health", timeout=2.0)
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.wait([exited], timeout=HEALTH_INTERVAL_S)
            else:
                await self._mark_failed(inst, f"did not become ready within {READY_TIMEOUT_S // 60} minutes")
                await asyncio.to_thread(self.backend.stop, inst.name)
                return False
        finally:
            exited.cancel()
        if inst.state != "starting":
            return False
        inst.state, inst.ready_ts, inst.last_log_lines = "ready", time.time(), []
        self.save(inst)
        await self._emit("instance_ready", inst)
        return True

    async def _mark_failed(self, inst: Instance, reason: str | None = None) -> None:
        st = await asyncio.to_thread(self.backend.status, inst.name)
        lines = await asyncio.to_thread(self.backend.logs, inst.name, inst.invocation, 60)
        texts = [ln["text"] for ln in lines]
        if reason is None:
            errs = [t.strip() for t in texts if ERROR_LINE_RE.search(t)]
            specific = [t for t in errs if not GENERIC_ERROR_RE.search(t)]
            if errs:
                reason = (specific or errs)[-1]
            elif st.exit_status is not None:
                reason = f"exited with status {st.exit_status}"
            else:
                reason = "exited unexpectedly"
        inst.state, inst.pid, inst.last_error = "failed", None, reason
        inst.last_log_lines = texts[-5:]
        self.save(inst)
        await self._emit("instance_gone", inst)

    # ---- stop / restart / dismiss ---------------------------------------------
    async def stop(self, target: str) -> Instance:
        inst = self._resolve_target(target)
        if inst.state == "failed":
            await self._dismiss(inst)
            return inst
        if inst.state != "stopping":
            inst.state = "stopping"
            self.save(inst)
            self._spawn(inst.name, self._stop_task(inst))
        return inst

    async def _stop_now(self, inst: Instance) -> None:
        await self._emit("instance_stopping", inst)
        await asyncio.to_thread(self.backend.stop, inst.name)

    async def _stop_task(self, inst: Instance) -> None:
        await self._stop_now(inst)
        self._forget(inst)
        await self._emit("instance_gone", inst)

    async def stop_all(self) -> list[str]:
        names = []
        for inst in list(self.instances.values()):
            if inst.state == "failed":
                await self._dismiss(inst)
            elif inst.state != "stopping":
                await self.stop(inst.name)
                names.append(inst.name)
        return names

    async def restart(self, target: str) -> Instance:
        inst = self._resolve_target(target)
        if inst.state == "stopping":
            raise LcppError("invalid_param", f"{inst.name} is stopping", 409)
        spec = dict(inst.spec)
        if inst.state != "failed":
            inst.state = "stopping"
            self.save(inst)
        self._spawn(inst.name, self._restart_task(inst, spec))
        return inst

    async def _restart_task(self, inst: Instance, spec: dict[str, Any]) -> None:
        if inst.state == "stopping":
            await self._stop_now(inst)
        else:
            await asyncio.to_thread(self.backend.reset, inst.name)
        self._forget(inst)
        try:
            await self.launch(spec, remember=False)
        except LcppError as e:
            inst.state, inst.pid, inst.last_error = "failed", None, f"restart failed: {e.detail}"
            self.instances[inst.name] = inst
            self.save(inst)
            await self._emit("instance_gone", inst)

    async def dismiss(self, target: str) -> None:
        inst = self._resolve_target(target)
        if inst.state != "failed":
            await self.stop(inst.name)
            return
        await self._dismiss(inst)

    async def _dismiss(self, inst: Instance) -> None:
        await asyncio.to_thread(self.backend.reset, inst.name)
        self._forget(inst)
        await self._emit("instance_gone", inst)

    # ---- router models -------------------------------------------------------
    async def router_models(self, inst: Instance, fresh: bool = False) -> list[dict[str, Any]]:
        if inst.kind != "router":
            return []
        cached = self._router_cache.get(inst.name)
        if cached and not fresh and time.monotonic() - cached[0] < 1.0:
            return cached[1]
        status: dict[str, str] = {}
        if inst.state == "ready" and self.http:
            try:
                r = await self.http.get(f"{inst.base}/models", timeout=2.0)
                for m in r.json().get("data", []):
                    status[m.get("id")] = (m.get("status") or {}).get("value", "unloaded")
            except (httpx.HTTPError, ValueError):
                pass
        models = [{"id": mid, "loaded": status.get(mid) == "loaded",
                   "loading": status.get(mid) == "loading"} for mid in inst.model_ids]
        self._router_cache[inst.name] = (time.monotonic(), models)
        return models

    async def router_action(self, target: str, model_id: str, action: str) -> Instance:
        inst = self._resolve_target(target)
        if inst.kind != "router":
            raise LcppError("invalid_param", f"{inst.name} is not a router", 400)
        if model_id not in inst.model_ids:
            raise LcppError("model_not_found", f'Model "{model_id}" is not served by {inst.name}', 404)
        if inst.state != "ready":
            raise LcppError("instance_not_found", f"{inst.name} is not ready", 409)
        assert self.http is not None
        try:
            r = await self.http.post(f"{inst.base}/models/{action}", json={"model": model_id}, timeout=10.0)
        except httpx.HTTPError as e:
            raise LcppError("daemon_error", f"{inst.name} did not answer: {e}", 502) from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", {}).get("message") or r.text
            except ValueError:
                detail = r.text
            raise LcppError("daemon_error", f"{action} {model_id}: {detail}", 502)
        self._router_cache.pop(inst.name, None)
        return inst

    # ---- views ------------------------------------------------------------------
    async def view(self, inst: Instance) -> dict[str, Any]:
        rss = await asyncio.to_thread(proc.footprint, inst.pid) if inst.state != "failed" else None
        last = inst.last_log_lines
        if inst.state == "starting":
            lines = await asyncio.to_thread(self.backend.logs, inst.name, inst.invocation, 5)
            last = [ln["text"] for ln in lines]
        relay = {k: inst.relay.get(k) for k in ("state", "key", "alias", "health", "error")}
        return {
            "name": inst.name, "kind": inst.kind, "model_id": inst.model_id,
            "models": await self.router_models(inst), "host": settings_mod.HOST, "port": inst.port,
            "url": inst.url, "state": inst.state, "pid": inst.pid, "started_ts": inst.started_ts,
            "ready_ts": inst.ready_ts, "rss_bytes": rss, "params": inst.params, "argv": inst.argv,
            "capabilities": inst.capabilities, "relay": relay, "last_error": inst.last_error,
            "last_log_lines": last,
        }

    async def views(self) -> list[dict[str, Any]]:
        insts = sorted(self.instances.values(), key=lambda i: i.started_ts)
        return list(await asyncio.gather(*(self.view(i) for i in insts)))

    # ---- logs -------------------------------------------------------------------
    def logs(self, target: str, lines: int) -> list[LogLine]:
        inst = self._resolve_target(target)
        return self.backend.logs(inst.name, inst.invocation, lines)

    def follow(self, target: str) -> AsyncIterator[LogLine]:
        inst = self._resolve_target(target)
        return self.backend.follow(inst.name, inst.invocation)

    # ---- recent launches ----------------------------------------------------------
    def recent(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.paths.recent_file.read_text())
            return data[:RECENT_MAX] if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _remember(self, raw: Any, spec: dict[str, Any]) -> None:
        entry = {k: v for k, v in dict(raw).items() if k != "save_preset" and v not in (None, "", [], {})}
        if spec["save_preset"]:
            entry["name"] = spec["save_preset"]
        key = json.dumps(entry, sort_keys=True)
        items = [entry, *(r for r in self.recent() if json.dumps(r, sort_keys=True) != key)]
        write_atomic(self.paths.recent_file, json.dumps(items[:RECENT_MAX], indent=2))
