"""ComfyUI's HTTP API (the parts the adapter uses). Websocket progress is in run.py."""

from __future__ import annotations

from typing import Any

import httpx


class ComfyError(Exception):
    def __init__(self, detail: str, status: int = 502, data: Any = None):
        super().__init__(detail)
        self.detail, self.status, self.data = detail, status, data


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _json(self, method: str, path: str, **kw) -> Any:
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ComfyError(f"ComfyUI isn't answering ({type(e).__name__})", 503) from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text[:500]
            raise ComfyError(f"ComfyUI answered {r.status_code} to {method} {path}", 502 if r.status_code >= 500 else 422, body)
        return r.json() if r.content else None

    async def up(self) -> bool:
        try:
            r = await self.http.get("/system_stats", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def system_stats(self) -> dict:
        return await self._json("GET", "/system_stats")

    async def queue(self) -> dict:
        """{queue_running: [[number, prompt_id, graph, extra, outputs], …], queue_pending: […]}"""
        return await self._json("GET", "/queue", timeout=5)

    async def object_info(self) -> dict:
        return await self._json("GET", "/object_info", timeout=120)

    async def free(self) -> None:
        await self._json("POST", "/free", json={"unload_models": True, "free_memory": True})

    async def prompt(self, graph: dict, client_id: str, extra: dict | None = None) -> dict:
        """Queue a graph: {prompt_id, number, node_errors}."""
        body = {"prompt": graph, "client_id": client_id}
        if extra:
            body["extra_data"] = extra
        return await self._json("POST", "/prompt", json=body)

    async def history(self, prompt_id: str | None = None, max_items: int = 50) -> dict:
        if prompt_id:
            return await self._json("GET", f"/history/{prompt_id}")
        return await self._json("GET", "/history", params={"max_items": max_items})

    async def interrupt(self, prompt_id: str | None = None) -> None:
        await self._json("POST", "/interrupt", json={"prompt_id": prompt_id} if prompt_id else {})

    async def delete_queued(self, prompt_ids: list[str]) -> None:
        await self._json("POST", "/queue", json={"delete": prompt_ids})

    async def upload_image(self, name: str, data: bytes, subfolder: str = "gaifa", overwrite: bool = True) -> str:
        """Upload to ComfyUI's input folder; returns the name LoadImage takes ("gaifa/x.png")."""
        files = {"image": (name, data, "application/octet-stream")}
        form = {"subfolder": subfolder, "type": "input", "overwrite": "true" if overwrite else "false"}
        r = await self._json("POST", "/upload/image", files=files, data=form)
        return f"{r['subfolder']}/{r['name']}" if r.get("subfolder") else r["name"]
