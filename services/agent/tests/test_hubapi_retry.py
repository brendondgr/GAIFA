"""The agent waits out a hub restart: a refused connection is retried (any method); a dropped one only
for GET; past RETRY_S it gives up (found overnight 2026-10-21: a hub restart mid-turn ended the turn)."""

from __future__ import annotations

import httpx
import pytest

from agent import hubapi


def _api(handler) -> hubapi.HubAPI:
    api = hubapi.HubAPI("http://hub")
    api.client = httpx.AsyncClient(base_url="http://hub", transport=httpx.MockTransport(handler))
    return api


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(hubapi, "RETRY_FIRST_S", 0.01)
    monkeypatch.setattr(hubapi, "RETRY_S", 0.5)


async def test_a_refused_connection_is_retried_for_any_method():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.method)
        if len(seen) < 3:
            raise httpx.ConnectError("refused", request=req)
        return httpx.Response(200, json={"status": "done"})

    api = _api(handler)
    assert await api.call("hub_list_services", {}, {}, "manual") == {"status": "done"}
    assert seen == ["POST", "POST", "POST"]
    await api.close()


async def test_a_dropped_post_is_not_sent_again():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.method)
        raise httpx.RemoteProtocolError("dropped", request=req)

    api = _api(handler)
    with pytest.raises(httpx.RemoteProtocolError):
        await api._json("POST", "/api/tools/x/call", json={})
    assert seen == ["POST"]
    await api.close()


async def test_a_dropped_get_is_retried_and_it_gives_up_in_time():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.method)
        raise httpx.ReadError("dropped", request=req)

    api = _api(handler)
    with pytest.raises(httpx.ReadError):
        await api._json("GET", "/api/services")
    assert len(seen) > 2
    await api.close()
