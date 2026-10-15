"""Publishing the engine to the relay (plan 18.4), against a fake relay."""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from vllm_mod.relay import Relay
from vllm_mod.server import create_app

from .conftest import run


class FakeRelay:
    """`/admin/registrations` in memory; `down = True` refuses connections."""

    def __init__(self):
        self.regs: dict[str, dict] = {}
        self.down = False
        self.log: list[str] = []
        self.facts: dict[str, dict | None] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path, m = request.url.path, request.method
        self.log.append(f"{m} {path}")
        if path == "/admin/registrations" and m == "GET":
            owner = request.url.params.get("owner")
            return httpx.Response(200, json=[{"key": k, **v} for k, v in self.regs.items() if v["owner"] == owner])
        key = path.rsplit("/", 1)[-1]
        if m == "PUT":
            body = json.loads(request.content)
            if body["alias"] == "taken":
                return httpx.Response(409, json={"detail": "alias 'taken' is used by another endpoint"})
            self.regs[key] = body
            return httpx.Response(200, json={"key": key, "owner": body["owner"], "adopted": False, "skipped_models": [],
                                             "endpoint": {"id": "ep1", "alias": body["alias"], "health": "up",
                                                          "facts_override": self.facts.get("ep1")}})
        if m == "PATCH" and path == "/admin/endpoints/ep1":
            self.facts["ep1"] = json.loads(request.content)["facts_override"]
            return httpx.Response(200, json={"id": "ep1"})
        if m == "DELETE":
            self.regs.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(404)


def _relay(settings, fake: FakeRelay) -> Relay:
    settings.relay_url = "http://relay"
    return Relay(settings, transport=httpx.MockTransport(fake.handler), delays=(0.05,))


async def _until(cond, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def test_publish_and_withdraw_with_the_engine(settings, make_engine, make_downloads):
    fake = FakeRelay()

    async def go():
        rel = _relay(settings, fake)
        e = make_engine()
        e.on_ready.append(rel.publish)
        e.on_stopping.append(rel.withdraw)
        await e.load("small")
        key = f"vllm:{settings.engine_port}"
        await _until(lambda: key in fake.regs)
        reg = fake.regs[key]
        assert reg["available_models"] == ["small"] and reg["alias"] == "Small" and reg["server_type"] == "vLLM"
        assert reg["port"] == settings.engine_port and reg["owner"] == "vllm" and reg["meta"]["profile"] == "small"
        assert rel.view()["state"] == "registered"
        assert fake.facts == {}                         # the profile parses neither tools nor thinking
        (settings.profiles_dir / "small.toml").write_text(
            (settings.profiles_dir / "small.toml").read_text() + 'tool_parser = "hermes"\nreasoning_parser = "qwen3"\n')
        await rel.publish(e.profiles()["small"])
        assert fake.facts == {"ep1": {"tools": True, "reasoning": True}}
        n = len(fake.log)
        await rel.publish(e.profiles()["small"])           # unchanged facts aren't sent again
        assert fake.log[n:] == [f"PUT /admin/registrations/{key}"]
        await e.unload()
        assert fake.regs == {} and rel.view()["state"] == "off"
        await e.shutdown()
        await rel.close()
    run(go())


def test_a_relay_that_is_down_gets_the_registration_later(settings):
    fake = FakeRelay()
    fake.down = True

    async def go():
        rel = _relay(settings, fake)
        from vllm_mod.profiles import load_profiles
        p = load_profiles(settings.profiles_dir)[0]["small"]
        await rel.publish(p)
        assert rel.state == "pending" and "unreachable" in rel.error
        fake.down = False
        await _until(lambda: rel.state == "registered")
        assert list(fake.regs) == [rel.key]
        # and a removal while it's down is sent once it's back
        fake.down = True
        await rel.withdraw(p)
        assert rel.state == "pending"
        fake.down = False
        await _until(lambda: rel.state == "off")
        assert fake.regs == {}
        await rel.close()
    run(go())


def test_a_rejected_registration_is_an_error(settings):
    fake = FakeRelay()
    (settings.profiles_dir / "dup.toml").write_text('name="D"\nmodel="o/d"\nalias="taken"\nmemory_gb=1\nmax_model_len=1024\n')

    async def go():
        rel = _relay(settings, fake)
        from vllm_mod.profiles import load_profiles
        await rel.publish(load_profiles(settings.profiles_dir)[0]["dup"])
        assert rel.state == "error" and "taken" in rel.error and fake.regs == {}
        await rel.close()
    run(go())


def test_reconcile_removes_stale_registrations(settings, make_engine, make_downloads):
    fake = FakeRelay()
    fake.regs = {f"vllm:{settings.engine_port}": {"owner": "vllm"}, "vllm:9999": {"owner": "vllm"},
                 "lcpp:7071": {"owner": "lcpp"}}
    rel = _relay(settings, fake)
    eng = make_engine()
    app = create_app(settings, engine=eng, downloads=make_downloads(eng), relay=rel)
    with TestClient(app) as c:
        assert set(fake.regs) == {"lcpp:7071"}          # nothing of ours is running
        assert c.post("/v1/load", json={"profile": "small"}).status_code == 200
        assert c.get("/v1/engine").json()["relay"]["state"] == "registered"
        assert set(fake.regs) == {"lcpp:7071", f"vllm:{settings.engine_port}"}
    assert set(fake.regs) == {"lcpp:7071"}              # stopping the adapter withdrew it
