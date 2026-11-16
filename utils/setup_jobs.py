"""Setup as a hub job (plan capability-enablement 3.1): the plan, a running setup, and a mod's test on this machine.

Everything runs the same `bin/gaifa setup` a person and a coding agent run, so there is one process, one log
(`data/state/setup/logs/`) and one resume file:

- `plan(ids)` runs `gaifa setup --plan --json <ids>` and adds what the person must see per mod (what it gives, where it
  goes, its port, whether it's recommended).
- `start(ids, answers)` writes the answers to `data/state/setup/answers-<job>.json` (0600, removed after), runs
  `gaifa setup <ids> --json --answers <file>` in its own process group, sends each progress line (stderr) as a
  `{type: "setup"}` event, and on exit reads the report, rescans and starts each mod it set up. Exit code 2 is
  `needs_you` (a question or a command for the person). One job at a time.
- `test(id)` runs the mod's setup block's `smoke` (real work on this machine) and says what it measured.

The runner is injected (`SetupJobs(hub, run=…)`) so tests use a fake `gaifa`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import signal
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from utils.services.model import ServiceError
from utils.paths import write_atomic

CODE = Path(__file__).resolve().parents[1]           # the checkout: bin/gaifa lives here, whatever GAIFA_ROOT is
ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
LINES = 300
TEST_TIMEOUT_S = 900

Runner = Callable[[list[str], Path, Callable[[str], None], Callable[[Any], None]], Awaitable[tuple[int, str]]]


async def run_gaifa(args: list[str], root: Path, on_line: Callable[[str], None], on_proc: Callable[[Any], None]) -> tuple[int, str]:
    """`bin/gaifa <args>` in its own process group: (exit code, stdout); each stderr line goes to `on_line`.
    `["__smoke__", <id>, <command>]` runs a setup block's smoke with bash in the mod's folder (stdout and stderr together)."""
    env = {**os.environ, "GAIFA_ROOT": str(root)}
    if args[:1] == ["__smoke__"]:
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", args[2], cwd=str(root / "services" / args[1]), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        on_proc(proc)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), TEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            os.killpg(proc.pid, signal.SIGKILL)
            return 124, f"the test didn't finish in {TEST_TIMEOUT_S} s"
        return proc.returncode or 0, out.decode(errors="replace")
    proc = await asyncio.create_subprocess_exec(
        str(CODE / "bin" / "gaifa"), *args, cwd=str(root), env=env,     # a bash script: it finds its own Python
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    on_proc(proc)

    async def lines() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            on_line(raw.decode(errors="replace").rstrip("\n"))

    reader = asyncio.create_task(lines())
    out = await proc.stdout.read() if proc.stdout else b""
    rc = await proc.wait()
    await reader
    return rc, out.decode(errors="replace")


def check_ids(ids: list[str]) -> list[str]:
    ids = [i.strip() for i in ids if i and i.strip()]
    bad = [i for i in ids if not ID.match(i)]
    if not ids or bad:
        raise ServiceError(422, "invalid_request", f"setup needs mod ids ({', '.join(bad) or 'none given'})")
    return ids


class SetupJobs:
    def __init__(self, hub: Any, run: Runner | None = None) -> None:
        self.hub = hub
        self.run = run or run_gaifa
        self.job: dict[str, Any] | None = None
        self.proc: Any = None
        self.task: asyncio.Task[None] | None = None

    @property
    def root(self) -> Path:
        return self.hub.paths.root

    @property
    def state_dir(self) -> Path:
        return self.hub.paths.state / "setup"

    # ---- the plan ----------------------------------------------------------------------------

    async def plan(self, ids: list[str]) -> dict[str, Any]:
        ids = check_ids(ids)
        rc, out = await self.run(["setup", "--plan", "--json", *ids], self.root, lambda _: None, lambda _: None)
        try:
            plan = json.loads(out)
        except ValueError:
            raise ServiceError(500, "setup_failed", f"gaifa setup --plan answered {rc} without a plan: {out[:300]}") from None
        plan["about"] = [self._about(m) for m in plan.get("mods") or ids]
        return plan

    def _about(self, sid: str) -> dict[str, Any]:
        """What the person sees per mod beside the plan: what it gives, where it goes, its port, recommended."""
        from utils.setupdocs.envs import recommended

        mgr = self.hub.services
        svc = mgr.services.get(sid) if mgr is not None else None
        d = self.root / "services" / sid
        m = svc.m if svc is not None else None
        return {"id": sid, "name": svc.mod.name if svc else sid, "provides": (m.agent.provides if m else None) or "",
                "description": m.description if m else "", "folder": f"services/{sid}", "port": svc.eff.port if svc else None,
                "recommended": recommended(d) if d.is_dir() else False,
                "installed": mgr.installed(svc) if svc is not None else False, "last_test": self.last_test(sid)}

    # ---- a setup ----------------------------------------------------------------------------

    def public(self) -> dict[str, Any] | None:
        return dict(self.job) if self.job else None

    def _publish(self) -> None:
        bus = getattr(self.hub, "bus", None)
        if bus is not None and self.job is not None:
            bus.publish({"type": "setup", "job": self.public()})

    async def start(self, ids: list[str], answers: dict[str, Any] | None = None) -> dict[str, Any]:
        ids = check_ids(ids)
        if self.job and self.job["state"] == "running":
            raise ServiceError(409, "setup_busy", f"a setup is running ({', '.join(self.job['ids'])}); wait for it or stop it",
                               {"job": self.public()})
        jid = "sj_" + secrets.token_hex(5)
        self.job = {"id": jid, "ids": ids, "state": "running", "started_ts": time.time(), "finished_ts": None,
                    "lines": [], "report": None, "needs": None, "error": None, "started": []}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        f = self.state_dir / f"answers-{jid}.json"
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump({"yes": True, **(answers or {})}, fh)
        self.task = asyncio.create_task(self._run(ids, f))
        self._publish()
        return self.public()   # type: ignore[return-value]

    def _line(self, text: str) -> None:
        if self.job is None:
            return
        self.job["lines"] = [*self.job["lines"], text][-LINES:]
        self._publish()

    def _proc(self, p: Any) -> None:
        self.proc = p

    async def _run(self, ids: list[str], answers: Path) -> None:
        assert self.job is not None
        job = self.job
        try:
            rc, out = await self.run(["setup", *ids, "--json", "--answers", str(answers)], self.root, self._line, self._proc)
        except asyncio.CancelledError:
            job.update(state="cancelled", finished_ts=time.time())
            self._publish()
            raise
        except Exception as e:  # noqa: BLE001: a job reports, never raises
            rc, out = 1, ""
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            answers.unlink(missing_ok=True)
            self.proc = None
        if job["state"] == "cancelled":
            return
        try:
            report = json.loads(out) if out.strip() else None
        except ValueError:
            report = None
            job["error"] = job["error"] or f"no report from gaifa setup (exit {rc})"
        job["report"] = report
        if rc == 2:
            job["needs"] = _needs(report)
            job["state"] = "needs_you"
        elif rc == 0:
            job["started"] = await self._start_set_up(ids)    # before "done": whoever waits for it sees the mods started
            job["state"] = "done"
        else:
            job["state"] = "failed"
            job["error"] = job["error"] or _failure(report) or f"gaifa setup exited {rc}"
        job["finished_ts"] = time.time()
        self._publish()

    async def _start_set_up(self, ids: list[str]) -> list[dict[str, Any]]:
        """After a setup: pick up new folders, then start each mod it set up (its state, or why it didn't)."""
        mgr = self.hub.services
        if mgr is None:
            return []
        try:
            await mgr.rescan(autostart=False)
        except Exception:  # noqa: BLE001
            pass
        out = []
        for sid in ids:
            svc = mgr.services.get(sid)
            if svc is None:
                continue
            try:
                svc = await mgr.start(sid, wait=True)
                out.append({"id": sid, "state": svc.state, **({"error": svc.last_error} if svc.last_error and not svc.up else {})})
            except ServiceError as e:
                out.append({"id": sid, "state": svc.state, "error": e.detail})
        return out

    async def cancel(self) -> dict[str, Any] | None:
        """Stop the running setup (its whole process group)."""
        if self.job is None or self.job["state"] != "running":
            return self.public()
        if self.proc is not None and getattr(self.proc, "pid", None):
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.job.update(state="cancelled", finished_ts=time.time())
        self._publish()
        return self.public()

    async def close(self) -> None:
        if self.job and self.job["state"] == "running":
            await self.cancel()

    # ---- a mod's test on this machine -------------------------------------------------------

    async def test(self, sid: str) -> dict[str, Any]:
        """Run the mod's own setup block's `smoke` in its folder: passed, seconds, the device, the log."""
        from utils.setupdocs.envs import parse

        check_ids([sid])
        d = self.root / "services" / sid
        env = None
        for doc in sorted((d / "setup").glob("*.md")) if (d / "setup").is_dir() else []:
            e, _ = parse(doc, sid)
            if e is not None and e.id == sid:
                env = e
        if env is None or not env.setup.smoke:
            raise ServiceError(404, "no_test", f"{sid} has no test (its setup doc gives no smoke)")
        logs = self.state_dir / "logs" / sid
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / "test.log"
        t0 = time.monotonic()
        rc, out = await self.run(["__smoke__", sid, env.setup.smoke], self.root, lambda _: None, lambda _: None)
        secs = round(time.monotonic() - t0, 1)
        log.write_text(out)
        svc = self.hub.services.services.get(sid) if self.hub.services else None
        device = ((svc.status or {}).get("device") if svc is not None else None) or None
        measured = _measured(out)                # capability-enablement 7.2: the mod's own numbers, when its test gives them
        device = measured.get("device") or device
        passed = rc == 0
        out_ = {"id": sid, "passed": passed, "seconds": secs, "device": device, "run": env.setup.smoke,
                "log": str(log.relative_to(self.root)), "output": out[-2000:],
                "sentence": measured.get("sentence") or (f"{sid}: test {'passed' if passed else 'failed'} in {secs} s"), "measured": measured}
        gpu_expected = bool(env.setup.gpu) and any(v.accel != "cpu" for v in env.setup.effective_variants())
        advice = []                              # advice, never a gate: the mod stays set up either way
        if not passed or (gpu_expected and device == "cpu"):
            if gpu_expected:
                advice.append(f"try the CPU variant: gaifa setup {sid} --accel {sid}=cpu" if not passed else
                              f"it ran on the CPU though a GPU was expected: check the GPU setup (gaifa hardware), or keep the CPU")
            if len(env.setup.suggest) > 1:
                advice.append("pick a smaller model (its setup's model question)")
            advice.append(f"have your coding agent look: gaifa setup --prompt {sid} (the log is {out_['log']})")
        out_["advice"] = advice
        out_["at"] = time.time()
        write_atomic(logs / "test.json", json.dumps({k: v for k, v in out_.items() if k != "output"}))  # shown beside the model (7.3, 7.4)
        return out_

    def last_test(self, sid: str) -> dict[str, Any] | None:
        """The mod's last test result (without its output), or None."""
        try:
            return json.loads((self.state_dir / "logs" / sid / "test.json").read_text())
        except (OSError, ValueError):
            return None


def _measured(out: str) -> dict[str, Any]:
    """The last JSON object a test printed that has a `sentence` (a mod's /v1/selftest), else {}."""
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"sentence"' in line:
            try:
                v = json.loads(line)
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
    return {}


def _needs(report: Any) -> dict[str, Any]:
    """What the person must do for a setup that stopped with exit code 2: the questions, or the command to run."""
    r = report if isinstance(report, dict) else {}
    return {"questions": r.get("questions") or [], "interactive": r.get("interactive") or r.get("waiting") or [],
            "host": [h for h in r.get("host") or [] if not h.get("ok", True)], "stage": r.get("stage")}


def _failure(report: Any) -> str | None:
    r = report if isinstance(report, dict) else {}
    failed = r.get("failed") or []
    if failed and isinstance(failed[0], dict):
        f = failed[0]
        return f"{f.get('setup')}: {f.get('step')} failed ({f.get('run')})"
    return None
