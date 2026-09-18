"""Tiny stdlib HTTP client for lcppd. The CLI must start fast, so nothing here
(or in anything the CLI imports) may pull in FastAPI, httpx or pydantic."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterator
from urllib.parse import quote

from lcpp import settings
from lcpp.paths import Paths


class DaemonDown(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail: str, code: str):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


def default_url() -> str:
    env = os.environ.get("LCPP_URL")
    if env:
        return env.rstrip("/")
    try:
        return settings.daemon_url(settings.load(Paths.default()))
    except (OSError, ValueError):
        return settings.daemon_url(settings.DEFAULTS)


def q(part: str | int) -> str:
    return quote(str(part), safe="")


class Client:
    def __init__(self, base: str | None = None, timeout: float = 30.0):
        self.base = (base or default_url()).rstrip("/")
        self.timeout = timeout

    def _open(self, method: str, path: str, body: Any = None, timeout: float | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"content-type": "application/json"} if data else {})
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}")
            except ValueError:
                err = {}
            raise ApiError(e.code, err.get("detail") or e.reason, err.get("code") or "daemon_error") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise DaemonDown(f"lcpp daemon is not answering at {self.base} ({getattr(e, 'reason', e)})") from None

    def request(self, method: str, path: str, body: Any = None) -> Any:
        with self._open(method, path, body) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body if body is not None else {})

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def sse(self, method: str, path: str, body: Any = None) -> Iterator[dict[str, Any]]:
        """Yield each ``data:`` JSON event of a server-sent-event response."""
        with self._open(method, path, body, timeout=3600) as r:
            for raw in r:
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        try:
                            yield json.loads(data)
                        except ValueError:
                            continue
