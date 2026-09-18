"""lcpp ↔ relay: register on ready, unregister on stop, retry, reconcile."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from fakes.fake_relay import RelayServer
from lcpp import relay as relay_mod
from lcpp.backends.subprocess import SubprocessBackend
from lcpp.daemon.app import create_app

RELAY_PORT = 17999  # conftest's relay.url


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(relay_mod, "RETRY_DELAYS", (0.2, 0.3, 0.5))
    monkeypatch.setattr(relay_mod, "STATUS_TTL_S", 0.0)


@pytest.fixture
def relay():
    r = RelayServer(RELAY_PORT).start()
    yield r
    r.stop()


def make_client(fake_home, backend=None):
    return TestClient(create_app(fake_home, backend or SubprocessBackend(fake_home.state / "logs")))


def until(pred, timeout=10.0, step=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("condition not met in time")


def inst_of(c, name):
    return c.get(f"/api/instances/{name}").json()


def shutdown(c):
    c.post("/api/instances/stop-all")
    until(lambda: not c.get("/api/instances").json())


def test_register_on_ready_and_remove_on_stop(fake_home, relay):
    with make_client(fake_home) as c:
        r = c.post("/api/instances", json={"model_id": "minicpm", "port": 17071,
                                           "relay": {"enabled": True}}).json()
        name = r["instance"]["name"]
        until(lambda: inst_of(c, name)["relay"]["state"] == "registered")
        reg = relay.regs["lcpp:17071"]
        assert reg["alias"] == "MiniCPM5-2B"
        assert reg["available_models"] == ["minicpm-5-2B", "MiniCPM5-2B"]
        assert reg["base_url"] == "http://127.0.0.1:17071/v1" and reg["owner"] == "lcpp"
        assert reg["meta"]["manager_url"] == "http://127.0.0.1:7700/" and reg["meta"]["instance"] == name
        ov = c.get("/api/relay").json()
        assert ov["status"]["reachable"] and [o["key"] for o in ov["owned"]] == ["lcpp:17071"]
        assert ov["owned"][0]["instance"] == name and not ov["owned"][0]["orphan"]
        assert "MiniCPM5-2B" in ov["routable_models"]
        c.delete(f"/api/instances/{name}")
        until(lambda: "lcpp:17071" not in relay.regs)
        assert ("DELETE", "lcpp:17071") in relay.app.state.calls


def test_pending_while_relay_down_then_registers(fake_home):
    with make_client(fake_home) as c:
        r = c.post("/api/instances", json={"model_id": "gemma4-19B", "port": 17072,
                                           "relay": {"enabled": True, "alias": "g19"}}).json()
        name = r["instance"]["name"]
        assert any("unreachable" in w for w in r["warnings"])
        until(lambda: inst_of(c, name)["state"] == "ready")
        assert inst_of(c, name)["relay"]["state"] == "pending"
        relay = RelayServer(RELAY_PORT).start()
        try:
            until(lambda: inst_of(c, name)["relay"]["state"] == "registered")
            assert relay.regs["lcpp:17072"]["alias"] == "g19"
            shutdown(c)
        finally:
            relay.stop()


def test_stop_while_relay_down_queues_delete(fake_home, relay):
    with make_client(fake_home) as c:
        name = c.post("/api/instances", json={"model_id": "minicpm", "port": 17073,
                                              "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, name)["relay"]["state"] == "registered")
        relay.stop()
        c.delete(f"/api/instances/{name}")
        until(lambda: not c.get("/api/instances").json())
        assert "lcpp:17073" in relay.regs  # could not be deleted yet
        relay.start()
        until(lambda: "lcpp:17073" not in relay.regs)


def test_reconcile_removes_orphans_and_keeps_others(fake_home, relay):
    relay.app.state.add_manual("skynet", "http://127.0.0.1:9090/v1", "skynet")
    with TestClient(relay.app) as rc:
        rc.put("/admin/registrations/lcpp:17088", json={"name": "old", "port": 17088, "owner": "lcpp"})
        rc.put("/admin/registrations/tool:1", json={"name": "t", "port": 1, "owner": "tool"})
    with make_client(fake_home):
        assert "lcpp:17088" not in relay.regs
        assert "tool:1" in relay.regs
        assert any(e["name"] == "skynet" for e in relay.app.state.eps.values())


def test_publish_unpublish_and_alias_conflict(fake_home, relay):
    relay.app.state.add_manual("opencode", "http://127.0.0.1:4096", "agent")
    with make_client(fake_home) as c:
        name = c.post("/api/instances", json={"model_id": "gemma4-19B", "port": 17074,
                                              "relay": {"enabled": False}}).json()["instance"]["name"]
        until(lambda: inst_of(c, name)["state"] == "ready")
        assert "lcpp:17074" not in relay.regs
        r = c.post(f"/api/instances/{name}/relay", json={"alias": "agent"})
        assert r.status_code == 409 and r.json()["code"] == "alias_conflict"
        assert inst_of(c, name)["relay"]["state"] == "off"
        r = c.post(f"/api/instances/{name}/relay", json={"alias": "g19"}).json()
        assert r["relay"]["state"] == "registered" and relay.regs["lcpp:17074"]["alias"] == "g19"
        others = c.get("/api/relay").json()["others"]
        assert [o["name"] for o in others] == ["opencode"]
        r = c.delete(f"/api/instances/{name}/relay").json()
        assert r["relay"]["state"] == "off" and "lcpp:17074" not in relay.regs
        shutdown(c)


def test_adoption_reflects_relay_alias(fake_home, relay):
    relay.app.state.add_manual("llama.cpp · local", "http://127.0.0.1:17075/v1", "local")
    with make_client(fake_home) as c:
        name = c.post("/api/instances", json={"kind": "router", "model_ids": ["minicpm"], "port": 17075,
                                              "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, name)["relay"]["state"] == "registered")
        assert inst_of(c, name)["relay"]["alias"] == "local"
        assert len(relay.app.state.eps) == 1  # adopted, not duplicated
        shutdown(c)


def test_cleanup_remove_and_self_heal(fake_home, relay):
    with make_client(fake_home) as c:
        name = c.post("/api/instances", json={"model_id": "minicpm", "port": 17076,
                                              "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, name)["relay"]["state"] == "registered")
        with TestClient(relay.app) as rc:
            rc.put("/admin/registrations/lcpp:17089", json={"name": "ghost", "port": 17089, "owner": "lcpp"})
            owned = {o["key"]: o for o in c.get("/api/relay").json()["owned"]}
            assert owned["lcpp:17089"]["orphan"] is True
            assert c.post("/api/relay/cleanup").json()["removed"] == ["lcpp:17089"]
            # someone deletes our registration in the relay dashboard: healed
            rc.delete("/admin/registrations/lcpp:17076")
        c.get("/api/overview")
        until(lambda: "lcpp:17076" in relay.regs)
        assert c.delete("/api/relay/registrations/lcpp:17076").status_code == 204
        assert inst_of(c, name)["relay"]["state"] == "off" and "lcpp:17076" not in relay.regs
        shutdown(c)


def test_failed_instance_marks_relay_error(fake_home, relay):
    with make_client(fake_home) as c:
        name = c.post("/api/instances", json={"model_id": "broken", "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, name)["state"] == "failed")
        rel = until(lambda: (r := inst_of(c, name)["relay"])["state"] == "error" and r)
        assert rel["error"] == "instance never became ready"
        assert not relay.regs
        c.delete(f"/api/instances/{name}?dismiss=1")


def test_dedicated_instance_takes_model_name_from_router(fake_home, relay):
    with make_client(fake_home) as c:
        router = c.post("/api/instances", json={"kind": "router", "model_ids": ["gemma4-19B", "minicpm"],
                                                "port": 17077, "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, router)["relay"]["state"] == "registered")
        assert relay.regs["lcpp:17077"]["available_models"] == ["gemma-4-19B-it", "minicpm-5-2B"]
        single = c.post("/api/instances", json={"model_id": "minicpm", "port": 17078,
                                                "relay": {"enabled": True}}).json()["instance"]["name"]
        until(lambda: inst_of(c, single)["relay"]["state"] == "registered")
        assert relay.regs["lcpp:17077"]["available_models"] == ["gemma-4-19B-it"]
        assert relay.regs["lcpp:17078"]["available_models"] == ["minicpm-5-2B", "MiniCPM5-2B"]
        c.delete(f"/api/instances/{single}")
        until(lambda: relay.regs["lcpp:17077"]["available_models"] == ["gemma-4-19B-it", "minicpm-5-2B"])
        shutdown(c)


def test_reconcile_orders_routers_before_singles(fake_home, relay):
    # One backend for both daemon lifetimes: it stands in for systemd, which
    # is what lets a restarted daemon find the running instances.
    backend = SubprocessBackend(fake_home.state / "logs")
    with make_client(fake_home, backend) as c:
        router = c.post("/api/instances", json={"kind": "router", "model_ids": ["gemma4-19B", "minicpm"],
                                                "port": 17091, "relay": {"enabled": True}}).json()["instance"]["name"]
        r = c.post("/api/instances", json={"model_id": "minicpm", "port": 17092, "relay": {"enabled": True}})
        assert r.status_code == 201, r.text
        single = r.json()["instance"]["name"]
        until(lambda: inst_of(c, single)["relay"]["state"] == "registered"
              and inst_of(c, router)["relay"]["state"] == "registered")
        # the relay forgets everything; a daemon restart must rebuild it correctly
        relay.app.state.eps.clear()
    with make_client(fake_home, backend) as c:
        until(lambda: "lcpp:17092" in relay.regs and "lcpp:17091" in relay.regs)
        assert relay.regs["lcpp:17091"]["available_models"] == ["gemma-4-19B-it"]
        assert relay.regs["lcpp:17092"]["available_models"] == ["minicpm-5-2B", "MiniCPM5-2B"]
        shutdown(c)
