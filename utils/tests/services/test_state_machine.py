"""2.3: the service state machine, run against fake mods with the subprocess backend."""

from __future__ import annotations

import asyncio
import os
import signal
import socket

import pytest

from utils.services import ServiceError
from utils.tests.conftest import free_port
from utils.tests.services.conftest import until


def activity(mgr) -> list[str]:
    return [a["text"] for a in mgr.test_activity.recent(200)][::-1]


async def test_start_to_ready(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    svc = mgr.get("fake-ok")
    assert svc.state == "stopped" and svc.load == "n/a"
    await mgr.start("fake-ok", wait=True)
    assert svc.state == "ready" and svc.pid and svc.started_ts
    assert svc.health["ok"] and svc.health["body"]["status"] == "ok"
    assert rig.states("fake-ok") == ["starting", "ready"]
    assert any(t.startswith("Fake OK is ready (") for t in activity(mgr))
    assert (rig.root / "outputs" / "fake-ok").is_dir()  # [outputs] → created on start


async def test_start_is_idempotent(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await asyncio.gather(mgr.start("fake-ok"), mgr.start("fake-ok"), mgr.start("fake-ok"))
    await until(lambda: mgr.get("fake-ok").state == "ready")
    assert await rig.backend.list_ours() == ["fake-ok"]
    pid = mgr.get("fake-ok").pid
    await mgr.start("fake-ok", wait=True)
    assert mgr.get("fake-ok").pid == pid


async def test_slow_start_succeeds_within_timeout(rig):
    rig.add("fake-slow")
    rig.config('[services.fake-slow]\nenv = { FAKE_SLOW_S = "0.6" }')
    mgr = await rig.manager()
    await mgr.start("fake-slow", wait=True)
    assert mgr.get("fake-slow").state == "ready"


async def test_slow_start_timeout_fails_and_stops_it(rig):
    rig.add("fake-slow", edit={"start_timeout_s": "0.5"})
    rig.config('[services.fake-slow]\nenv = { FAKE_SLOW_S = "30" }')
    mgr = await rig.manager()
    await mgr.start("fake-slow", wait=True)
    svc = mgr.get("fake-slow")
    assert svc.state == "failed"
    assert "not healthy after 0.5s (/health HTTP 503)" in svc.last_error
    assert "Last log lines:" in svc.last_error and "listening on 127.0.0.1" in svc.last_error
    assert await rig.backend.list_ours() == []  # the stuck process was stopped
    assert [a["id"] for a in mgr.alerts.list()] == ["svc-fake-slow"]


async def test_crash_restarts_then_gives_up(rig):
    rig.add("fake-crash", edit={"restart": '"on-failure"'})
    rig.config('[services.fake-crash]\nenv = { FAKE_CRASH_S = "0.3" }')
    mgr = await rig.manager()
    await mgr.start("fake-crash", wait=True)
    svc = mgr.get("fake-crash")
    await until(lambda: any("gave up restarting" in t for t in activity(mgr)), timeout=20)
    assert svc.state == "failed"
    assert "exited with status 1" in svc.last_error and "Gave up after 3 restarts" in svc.last_error
    texts = activity(mgr)
    assert [t for t in texts if t.startswith("Restarting")] == [
        "Restarting Fake Crash (try 1 of 3)", "Restarting Fake Crash (try 2 of 3)", "Restarting Fake Crash (try 3 of 3)",
    ]
    assert sum(1 for t in texts if t.startswith("Fake Crash failed")) == 4
    assert await rig.backend.list_ours() == []


async def test_crash_with_restart_no_stays_failed(rig):
    rig.add("fake-crash")  # restart = "no" in the fixture
    rig.config('[services.fake-crash]\nenv = { FAKE_CRASH_S = "0.3" }')
    mgr = await rig.manager()
    await mgr.start("fake-crash", wait=True)
    await until(lambda: mgr.get("fake-crash").state == "failed")
    await asyncio.sleep(0.3)
    assert mgr.get("fake-crash").state == "failed"
    assert not any(t.startswith("Restarting") for t in activity(mgr))
    alert = mgr.alerts.list()[0]
    assert alert["level"] == "error" and alert["action"]["route"] == "#/s/fake-crash/logs"


async def test_health_misses_degrade_then_fail(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    os.kill(svc.pid, signal.SIGSTOP)  # alive but not answering
    await until(lambda: svc.state == "failed", timeout=10)
    assert "health check failed 5 times in a row" in svc.last_error
    # From the published events (not polling, which can miss the short degraded window under load):
    states = rig.states("fake-ok")
    assert states[-2:] == ["degraded", "failed"], states
    assert any(e["type"] == "service" and e["service"]["state"] == "degraded" and "health check failing" in (e["service"]["last_error"] or "") for e in rig.events)
    assert await rig.backend.list_ours() == []  # the hung process was killed


async def test_degraded_recovers(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    os.kill(svc.pid, signal.SIGSTOP)
    await until(lambda: svc.state == "degraded", timeout=5)
    os.kill(svc.pid, signal.SIGCONT)
    await until(lambda: svc.state == "ready", timeout=5)
    assert svc.last_error is None
    await until(lambda: "Fake OK is healthy again" in activity(mgr))  # written just after the state changes


async def test_stop_and_restart(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    pid = mgr.get("fake-ok").pid
    await mgr.restart("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    assert svc.state == "ready" and svc.pid != pid
    await mgr.stop("fake-ok", wait=True)
    assert svc.state == "stopped" and svc.pid is None and svc.health is None
    assert rig.states("fake-ok") == ["starting", "ready", "stopping", "stopped", "starting", "ready", "stopping", "stopped"]
    assert "Stopped Fake OK" in activity(mgr)


async def test_stop_while_starting_wins(rig):
    rig.add("fake-slow")
    rig.config('[services.fake-slow]\nenv = { FAKE_SLOW_S = "0.5" }')
    mgr = await rig.manager()
    await mgr.start("fake-slow")
    assert mgr.get("fake-slow").state == "starting"
    await mgr.stop("fake-slow", wait=True)
    await asyncio.sleep(1)
    assert mgr.get("fake-slow").state == "stopped"
    assert "ready" not in rig.states("fake-slow")


async def test_stop_returns_before_the_process_is_gone(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = await mgr.stop("fake-ok")
    assert svc.state == "stopping"
    await until(lambda: svc.state == "stopped")


async def test_adopts_running_mods_on_boot(rig):
    rig.add("fake-ok")
    first = await rig.manager()
    await first.start("fake-ok", wait=True)
    pid = first.get("fake-ok").pid
    await first.close()  # the hub stops; KeepBackend leaves the mod running
    second = await rig.manager(autostart=True)
    svc = second.get("fake-ok")
    await until(lambda: svc.state == "ready")
    assert svc.pid == pid
    assert f"Adopted Fake OK, already running (pid {pid})" in activity(second)
    assert "Fake OK is ready again" in activity(second)


async def test_orphan_from_this_root_is_stopped(rig):
    rig.add("fake-ok")
    first = await rig.manager()
    await first.start("fake-ok", wait=True)
    await first.close()
    import shutil

    shutil.rmtree(rig.services / "fake-ok")  # "deleting services/<id>/ removes the mod completely"
    second = await rig.manager()
    assert second.services == {}
    assert await rig.backend.list_ours() == []
    assert "Stopped fake-ok: its folder was removed" in activity(second)


async def test_unit_from_another_root_is_left_alone(rig, tmp_path_factory):
    other = tmp_path_factory.mktemp("other-checkout")
    rig.add("fake-ok")
    mgr = await rig.manager(boot=False)
    # A unit with the same name, started from another folder.
    from utils.manifest import LaunchSpec

    port = free_port()
    await rig.backend.start(LaunchSpec(
        id="fake-ok", argv=["python3", str(rig.services / "_fakemod.py"), "ok"], cwd=other,
        env={"FAKE_PORT": str(port)}, port=port, stop_timeout_s=2, outputs=other,
    ))
    await rig.backend.start(LaunchSpec(
        id="ghost", argv=["sleep", "30"], cwd=other, env={}, port=0, stop_timeout_s=2, outputs=other,
    ))
    await mgr.boot(autostart=True)
    assert mgr.get("fake-ok").state == "failed" and "another GAIFA folder" in mgr.get("fake-ok").last_error
    assert await rig.backend.list_ours() == ["fake-ok", "ghost"]


async def test_autostart_respects_enabled_autostart_and_after(rig):
    rig.add("fake-slow", as_id="base")
    rig.add("fake-ok", as_id="dependent", edit={"after": '["base"]'})
    rig.add("fake-ok", as_id="off")
    rig.add("fake-ok", as_id="manual")
    rig.config(
        '[services.base]\nenv = { FAKE_SLOW_S = "0.5" }\n'
        "[services.off]\nenabled = false\n"
        "[services.manual]\nautostart = false\n"
    )
    mgr = await rig.manager(autostart=True)
    await until(lambda: mgr.get("dependent").state == "ready" and mgr.get("base").state == "ready")
    base_ready = next(e["service"]["state_since"] for e in rig.events if e["type"] == "service" and e["service"]["id"] == "base" and e["service"]["state"] == "ready")
    assert mgr.get("dependent").started_ts >= base_ready  # waited for base
    await asyncio.sleep(0.3)
    assert mgr.get("off").state == "stopped" and mgr.get("manual").state == "stopped"
    with pytest.raises(ServiceError) as e:
        await mgr.start("off")
    assert e.value.code == "service_disabled" and e.value.status == 409
    await mgr.start("manual", wait=True)
    assert mgr.get("manual").state == "ready"


async def test_a_mod_that_isnt_installed_isnt_autostarted(rig):
    rig.add("fake-ok", as_id="fresh", edit={"command": '[".venv/bin/python", "server.py"]'})   # no .venv yet
    rig.add("fake-ok", as_id="ready-one")
    rig.add("fake-ok", as_id="script", edit={"installed": '"~/.gaifa-test-missing/bin/tool"'})   # a tracked command, its tool not installed
    rig.add("fake-ok", as_id="either", edit={"installed": '["~/.gaifa-test-missing/bin/tool", "sh"]'})   # any one of them
    mgr = await rig.manager(autostart=True)
    await until(lambda: mgr.get("ready-one").state == "ready")
    await asyncio.sleep(0.2)
    fresh = mgr.get("fresh")
    assert fresh.state == "stopped" and fresh.last_error == "not set up: run `gaifa setup fresh`"
    assert mgr.installed(fresh) is False and mgr.installed(mgr.get("ready-one")) is True
    assert mgr.get("script").state == "stopped" and mgr.installed(mgr.get("script")) is False
    assert mgr.installed(mgr.get("either")) is True


async def test_port_conflict_names_the_holder(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    with socket.socket() as s:
        s.bind(("127.0.0.1", rig.ports["fake-ok"]))
        s.listen()
        with pytest.raises(ServiceError) as e:
            await mgr.start("fake-ok")
    assert e.value.code == "port_in_use"
    svc = mgr.get("fake-ok")
    assert svc.state == "failed"
    assert f"port {rig.ports['fake-ok']} is already in use by " in svc.last_error
    assert f"pid {os.getpid()}" in svc.last_error  # this test process holds it
    assert e.value.data["owner"]["pid"] == os.getpid()
    await mgr.start("fake-ok", wait=True)  # freed: starts normally
    assert svc.state == "ready" and svc.last_error is None


async def test_broken_manifest_is_failed_and_not_startable(rig):
    d = rig.add("fake-ok", as_id="broken")
    (d / "service.toml").write_text('id = "broken"\nname = "Broken"\n[run]\nport = 5150\n')
    mgr = await rig.manager(autostart=True)
    svc = mgr.get("broken")
    assert svc.state == "failed" and svc.errors == ["service.toml: [run].command is required (or set kind = \"external\")"]
    with pytest.raises(ServiceError) as e:
        await mgr.start("broken")
    assert e.value.code == "manifest_invalid"


async def test_config_port_clash_is_a_manifest_error(rig):
    rig.add("fake-ok", as_id="aaa")
    rig.add("fake-ok", as_id="bbb")
    rig.config(f"[services.bbb]\nport = {rig.ports['aaa']}\n")
    mgr = await rig.manager()
    assert mgr.get("aaa").errors == []
    assert mgr.get("bbb").errors == [f"config.toml: [services.bbb] port {rig.ports['aaa']} is already used by aaa"]


async def test_bad_placeholder_fails_at_start(rig):
    rig.add("fake-ok", edit={"env": '{ FAKE_PORT = "{port}", X = "{nope}" }'})
    mgr = await rig.manager()
    with pytest.raises(ServiceError) as e:
        await mgr.start("fake-ok")
    assert e.value.code == "manifest_invalid" and "unknown placeholder {nope}" in e.value.detail
    assert mgr.get("fake-ok").state == "failed"


async def test_missing_executable_is_not_set_up(rig):
    """capability-enablement 1.3: a missing command is a mod that was never set up, refused before any launch."""
    rig.add("fake-ok", edit={"command": '["./missing-binary"]'})
    mgr = await rig.manager()
    with pytest.raises(ServiceError) as e:
        await mgr.start("fake-ok")
    assert e.value.code == "not_set_up" and e.value.data["fix"] == "gaifa setup fake-ok"
    assert mgr.get("fake-ok").state == "stopped"


async def test_a_launch_that_fails_names_the_executable(rig):
    """Set up by its `installed` marker, but the command itself is missing: the launch error names it."""
    rig.add("fake-ok", edit={"command": '["./missing-binary"]', "installed": '"sh"'})
    mgr = await rig.manager()
    with pytest.raises(ServiceError) as e:
        await mgr.start("fake-ok")
    assert e.value.code == "service_failed" and "missing-binary" in e.value.detail
    assert mgr.get("fake-ok").state == "failed" and mgr.get("fake-ok").start_failed_at


async def test_failed_while_hub_was_down(rig):
    rig.add("fake-crash")
    rig.config('[services.fake-crash]\nenv = { FAKE_CRASH_S = "0.2" }\nautostart = false')
    first = await rig.manager()
    await first.start("fake-crash", wait=True)
    await first.close()  # closes before noticing the crash
    await asyncio.sleep(0.6)
    second = await rig.manager()
    svc = second.get("fake-crash")
    assert svc.state == "failed" and svc.last_error.startswith("exited with status 1 while GAIFA was down")


async def test_external_mod_is_health_only(rig, fake_mod):
    real = fake_mod("ok")
    d = rig.add("fake-ok", as_id="ext", port=real.port)
    (d / "service.toml").write_text(f'id = "ext"\nname = "External"\n[run]\nkind = "external"\nport = {real.port}\n')
    mgr = await rig.manager(autostart=True)
    svc = mgr.get("ext")
    await until(lambda: svc.state == "ready")
    for action in (mgr.start, mgr.stop, mgr.restart):
        with pytest.raises(ServiceError) as e:
            await action("ext")
        assert e.value.code == "external_service"
    real.proc.kill()
    await until(lambda: svc.state == "failed", timeout=5)
    assert "not responding on" in svc.last_error


async def test_external_mod_never_seen_is_stopped(rig):
    d = rig.add("fake-ok", as_id="ext")
    (d / "service.toml").write_text(f'id = "ext"\n[run]\nkind = "external"\nport = {rig.ports["ext"]}\n')
    mgr = await rig.manager()
    await asyncio.sleep(0.4)
    assert mgr.get("ext").state == "stopped"


async def test_unknown_service(rig):
    mgr = await rig.manager()
    with pytest.raises(ServiceError) as e:
        await mgr.start("nope")
    assert (e.value.status, e.value.code) == (404, "service_not_found")


async def test_tcp_health(rig):
    rig.add("fake-ok", edit={"health": '"tcp"'})
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    svc = mgr.get("fake-ok")
    assert svc.state == "ready" and svc.health["ok"] and svc.health["body"] is None


async def test_every_change_is_published_with_a_full_summary(rig):
    rig.add("fake-ok")
    mgr = await rig.manager()
    await mgr.start("fake-ok", wait=True)
    ev = [e for e in rig.events if e["type"] == "service"][-1]["service"]
    expected = {
        "id", "name", "description", "icon", "version", "kind", "port", "url", "state", "state_since", "load", "idle_s",
        "busy", "memory", "stats", "has_page", "page_url", "logo_url", "chat_url", "badge", "main", "chat_panel", "has_outputs", "native_ui", "enabled", "autostart", "last_error", "manifest_errors",
        "accel", "unavailable", "installed", "availability",
    }
    assert set(ev) == expected
    assert ev["url"] == f"http://127.0.0.1:{rig.ports['fake-ok']}" and ev["has_outputs"] is True
