"""The calendar's tests run in New York time (a DST change on 2026-11-01 and 2027-03-14) against a temp DB."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["CALENDAR_TZ"] = "America/New_York"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def app(tmp_path):
    from server import create_app
    return create_app(str(tmp_path / "calendar.db"), str(tmp_path / "state"), hub_url="", background=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cal(client):
    return client.app.state.cal


AGENT = {"X-GAIFA-Origin": '{"thread": "t_abc", "tool_call": "tc_1"}'}
