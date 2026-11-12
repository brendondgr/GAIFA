"""Plan lan-access 2.2: `POST /api/system/restart`, only for the hub's own systemd unit."""

from __future__ import annotations

from utils.routes import system


def test_only_gaifa_services_own_process_counts():
    assert system._in_hub_unit("0::/user.slice/user-1000.slice/user@1000.service/app.slice/gaifa.service\n")
    assert not system._in_hub_unit("0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-com.anthropic.Claude-1.scope\n")
    assert not system._in_hub_unit("0::/user.slice/user-1000.slice/user@1000.service/app.slice/gaifa-voice.service\n")   # a mod's unit


async def test_refused_when_it_couldnt_start_again(client, app, monkeypatch):
    r = await client.post("/api/system/restart")
    assert r.status_code == 409 and r.json()["code"] == "not_a_service"
    stopped = []
    monkeypatch.setattr(system, "_in_hub_unit", lambda cgroup=None: True)
    app.state.hub.stop_server = lambda: stopped.append(1)
    r = await client.post("/api/system/restart")
    assert r.status_code == 200 and app.state.hub.exit_code == 75
    import asyncio
    await asyncio.sleep(0.5)
    assert stopped == [1]                                  # the server is asked to stop: no signal to the process
