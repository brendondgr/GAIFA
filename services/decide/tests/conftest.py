"""Shared fixtures: settings in a temporary folder, the fake decision model, and a fake hub that serves outputs and
records memory and registry calls."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from decide.engine import Decider, LocalBackend
from decide.hubclient import Hub
from decide.models.fake import FakeModel
from decide.server import create_app
from decide.settings import Settings

ADAPTERS = {"fake": FakeModel}


def png(color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(buf, "PNG")
    return buf.getvalue()


class FakeHub:
    def __init__(self):
        self.outputs: dict[str, tuple[dict, bytes]] = {}
        self.acquires: list[dict] = []
        self.models: list[dict] = []

    def add(self, oid: str, kind: str, data: bytes) -> str:
        self.outputs[oid] = ({"id": oid, "kind": kind, "size_bytes": len(data), "path": f"x/{oid}.png"}, data)
        return f"output:{oid}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/memory/acquire":
            self.acquires.append(json.loads(request.content))
            return httpx.Response(200, json={"granted": True, "freed": []})
        if path == "/api/models":
            self.models.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "fake"})
        if path.startswith("/api/outputs/"):
            oid, _, rest = path.removeprefix("/api/outputs/").partition("/")
            if oid not in self.outputs:
                return httpx.Response(404, json={"detail": "no such output", "code": "not_found"})
            rec, data = self.outputs[oid]
            return httpx.Response(200, content=data) if rest == "file" else httpx.Response(200, json=rec)
        return httpx.Response(404, json={"detail": "not here", "code": "not_found"})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeModel.calls.clear()
    FakeModel.loads.clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    folder = tmp_path / "models" / "fake"
    folder.mkdir(parents=True)
    (folder / "weights.bin").write_bytes(b"fake")
    return Settings(port=0, models_dir=tmp_path / "models", state_dir=tmp_path / "state", hub_url="http://hub",
                    default_model="fake", batch_size=8, idle_unload_s=0, max_questions=32)


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def decider(settings: Settings) -> Decider:
    return Decider(LocalBackend(ADAPTERS, settings.models_dir, batch_size=settings.batch_size), settings.state_dir)


@pytest.fixture
def client(settings: Settings, decider: Decider, hub: FakeHub):
    app = create_app(settings, decider=decider, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)),
                     adapters=ADAPTERS)
    with TestClient(app) as c:
        yield c
