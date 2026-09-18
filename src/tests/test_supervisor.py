"""Instance lifecycle against the fake llama-server (SubprocessBackend)."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import time

import httpx
import pytest

from conftest import make_supervisor
from lcpp import proc
from lcpp.instances import LcppError


def run(coro):
    return asyncio.run(coro)


async def until(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


class Recorder:
    def __init__(self):
        self.events = []

    async def instance_ready(self, inst):
        self.events.append(("ready", inst.name))

    async def instance_stopping(self, inst):
        self.events.append(("stopping", inst.name))

    async def instance_gone(self, inst):
        self.events.append(("gone", inst.name))


def test_preflight_defaults(fake_home):
    sup = make_supervisor(fake_home)
    pf = sup.preflight({"kind": "single", "model_id": "gemma4-19B"})
    assert pf["errors"] == [], pf["errors"]
    assert pf["port"] == 17071 and pf["port_ok"]
    assert pf["name"] == "gemma4-19b-17071" and pf["name_ok"]
    assert pf["estimated_bytes"] > 1500
    assert "--model" in pf["argv"] and "17071" in pf["argv"]


def test_preflight_errors(fake_home):
    sup = make_supervisor(fake_home)
    codes = lambda spec: {e["code"] for e in sup.preflight(spec)["errors"]}  # noqa: E731
    assert codes({"model_id": "gemma4-19B", "port": 17999}) == {"port_reserved"}
    assert codes({"model_id": "gemma4-19B", "port": 7710}) == {"port_reserved"}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 17090))
        s.listen()
        pf = sup.preflight({"model_id": "gemma4-19B", "port": 17090})
        assert pf["errors"][0]["code"] == "port_in_use" and "pid" in (pf["port_reason"] or "")
        assert pf["suggested_port"] == 17071
    assert codes({"model_id": "gemma4-19B", "name": "Bad Name"}) == {"invalid_name"}
    assert codes({"model_id": "nope"}) == {"model_not_found"}
    assert codes({"model_id": "gemma4-19B", "params": {"port": 1}}) == {"invalid_param"}
    os.remove(fake_home.root / "models/Gemma4-19B/g19.gguf")
    sup.catalog = sup.catalog.load(fake_home)
    assert codes({"model_id": "gemma4-19B"}) == {"model_files_missing"}


def test_launch_ready_logs_stop(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        rec = Recorder()
        sup.hooks.append(rec)
        await sup.start()
        inst, warnings = await sup.launch({"model_id": "minicpm", "port": 17072, "relay": {"enabled": False}})
        assert inst.state == "starting" and inst.name == "minicpm5-2b-17072"
        v = await sup.view(inst)
        assert v["state"] == "starting" and v["relay"]["state"] == "off"
        await until(lambda: inst.state == "ready")
        async with httpx.AsyncClient() as c:
            r = await c.get("http://127.0.0.1:17072/v1/models")
            assert r.json()["data"][0]["id"] == "minicpm-5-2B"
        v = await sup.view(inst)
        assert v["pid"] and v["rss_bytes"] and v["url"] == "http://127.0.0.1:17072/v1"
        assert any("listening" in ln["text"] for ln in sup.logs("17072", 50))
        # name taken by a running instance
        with pytest.raises(LcppError) as e:
            await sup.launch({"model_id": "gemma4-19B", "name": "minicpm5-2b-17072"})
        assert e.value.code == "name_taken"
        await sup.stop("minicpm5-2b-17072")
        await until(lambda: "minicpm5-2b-17072" not in sup.instances)
        assert proc.port_free(17072)
        assert rec.events == [("ready", inst.name), ("stopping", inst.name), ("gone", inst.name)]
        assert sup.recent()[0]["model_id"] == "minicpm"
        await sup.close()
    run(scenario())


def test_failed_load_is_reported_then_dismissed(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        inst, _ = await sup.launch({"model_id": "broken", "port": 17073})
        await until(lambda: inst.state == "failed")
        assert "out of device memory" in inst.last_error
        assert any("failed to load model" in t for t in inst.last_log_lines)
        v = await sup.view(inst)
        assert v["state"] == "failed" and v["pid"] is None
        await sup.dismiss(inst.name)
        assert inst.name not in sup.instances
        await sup.close()
    run(scenario())


def test_crash_after_ready_detected_by_pidfd(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        rec = Recorder()
        sup.hooks.append(rec)
        await sup.start()
        inst, _ = await sup.launch({"model_id": "gemma4-19B", "port": 17074})
        await until(lambda: inst.state == "ready")
        os.killpg(inst.pid, signal.SIGKILL)
        await until(lambda: inst.state == "failed")
        assert inst.last_error
        assert rec.events[-1] == ("gone", inst.name)
        await sup.close()
    run(scenario())


def test_restart_gets_new_process(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        inst, _ = await sup.launch({"model_id": "gemma4-19B", "port": 17075})
        await until(lambda: inst.state == "ready")
        old_pid = inst.pid
        await sup.restart(inst.name)
        await until(lambda: (i := sup.instances.get(inst.name)) is not None
                    and i.state == "ready" and i.pid != old_pid)
        assert sup.instances[inst.name].port == 17075
        assert len(sup.recent()) == 1  # a restart is not a new "recent" launch
        await sup.stop(inst.name)
        await until(lambda: not sup.instances)
        await sup.close()
    run(scenario())


def test_reconcile_adopts_running_and_fails_dead(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        a, _ = await sup.launch({"model_id": "gemma4-19B", "port": 17076})
        b, _ = await sup.launch({"model_id": "minicpm", "port": 17077})
        await until(lambda: a.state == "ready" and b.state == "ready")
        await sup.close()  # the daemon goes away; instances keep running
        os.killpg(b.pid, signal.SIGKILL)
        await asyncio.sleep(0.2)
        sup2 = make_supervisor(fake_home, backend=sup.backend)
        await sup2.start()
        assert sup2.instances[a.name].state == "ready"
        assert sup2.instances[b.name].state == "failed"
        assert "not running" in sup2.instances[b.name].last_error
        await sup2.stop(a.name)
        await until(lambda: a.name not in sup2.instances)
        await sup2.close()
    run(scenario())


def test_router_load_unload(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        inst, _ = await sup.launch({"kind": "router", "model_ids": ["gemma4-19B", "minicpm"],
                                    "models_max": 1, "port": 17078})
        assert inst.name == "router-17078" and inst.model_id is None
        assert (fake_home.generated / "router-17078.ini").exists()
        await until(lambda: inst.state == "ready")
        models = await sup.router_models(inst, fresh=True)
        assert models == [{"id": "gemma-4-19B-it", "loaded": False, "loading": False},
                          {"id": "minicpm-5-2B", "loaded": False, "loading": False}]
        await sup.router_action(inst.name, "minicpm-5-2B", "load")
        assert [m["loaded"] for m in await sup.router_models(inst)] == [False, True]
        with pytest.raises(LcppError):
            await sup.router_action(inst.name, "serenity", "load")
        await sup.stop_all()
        await until(lambda: not sup.instances)
        await sup.close()
    run(scenario())


def test_recent_and_presets(fake_home):
    async def scenario():
        sup = make_supervisor(fake_home)
        await sup.start()
        inst, _ = await sup.launch({"model_id": "gemma4-19B", "port": 17079, "save_preset": "my-g19"})
        recent = sup.recent()
        assert recent[0]["name"] == "my-g19" and "save_preset" not in recent[0]
        await sup.stop_all()
        await until(lambda: not sup.instances)
        await sup.close()
    run(scenario())
