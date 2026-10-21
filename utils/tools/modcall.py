"""Helpers for calls to a mod (plan 13.2, split from `calls.py` in 20.1): the error a tool call ends
with, dry runs, and turning a mod's error response into one the model can act on."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import httpx

from utils.tools import results

if TYPE_CHECKING:
    from utils.server import Hub


class ToolError(Exception):
    def __init__(self, code: str, detail: str, fix: str | None = None, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.fix, self.problems = code, detail, fix, problems

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "detail": self.detail}
        if self.fix:
            out["fix"] = self.fix
        if self.problems:
            out["problems"] = self.problems[:10]
        return out


async def dry_run(hub: Hub, c: Any) -> bool:
    """`origin.dry_run` (the agent eval): a generating tool makes a stand-in output under
    `outputs/eval/` instead of running (an image drawn from the prompt; a copy of the newest real
    video, audio or 3D model), titled from the arguments, so chains and cards are tested without
    the GPU. A tool with `dry_run = true` in `[tools]` goes to its mod as usual: the mod sees
    `dry_run` in `X-AIHub-Origin` and answers without its side effects (the web mod reads its fake
    web instead of the internet; plan 26.2)."""
    if not c.origin.get("dry_run") or c.tool.risk == "read" or c.tool.mod_dry_run:
        return False
    if c.tool.risk != "generate":                 # write and destructive: a stand-in success, nothing changes (plan 22.4)
        c.result = {"dry_run": True, "arguments": c.arguments}
        return True
    kind = (c.tool.response if c.tool.response in ("audio", "image", "video", "model3d") else None) \
        or results.made_kind(c.tool.name) or "image"
    source = None
    if kind != "image":
        page = await hub.outputs.list(kind=kind, service=c.tool.mod, limit=1)
        if not page["items"]:
            page = await hub.outputs.list(kind=kind, limit=200)
        source = next((o for o in page["items"] if o["service"] != "eval"), None)
        if source is None:
            raise ToolError("dry_run", f"dry run: no existing {kind} to stand in for {c.tool.name}")
        source = await hub.outputs.row(source["id"])
    rel = await asyncio.to_thread(results.stand_in, hub, kind, c.tool.name, c.arguments, source)
    await asyncio.sleep(0.3)
    c.outputs = await results.outputs_for(hub, [rel])
    c.result = {"state": "done", "arguments": c.arguments}
    return True


def _fix_and_problems(b: Any) -> tuple[str | None, list[dict[str, Any]] | None]:
    """A mod's own `fix` and `problems`: at the top level, under `data`, or inside a dict `detail`."""
    fix, probs = None, None
    for d in (b, b.get("data") if isinstance(b, dict) else None, b.get("detail") if isinstance(b, dict) else None):
        if not isinstance(d, dict):
            continue
        if fix is None and isinstance(d.get("fix"), str) and d["fix"].strip():
            fix = d["fix"].strip()
        if probs is None and isinstance(d.get("problems"), list):
            probs = [{k: str(x) for k, x in p.items()} for p in d["problems"] if isinstance(p, dict)] or None
    if fix is None and probs:
        fix = "; ".join(str(p["fix"]) for p in probs if p.get("fix")) or None
    return fix, probs


def mod_error(svc: Any, r: httpx.Response) -> ToolError:
    detail: Any = None
    b: Any = None
    try:
        b = r.json()
        detail = b.get("detail") if isinstance(b, dict) else b
    except ValueError:
        detail = r.text[:400]
    fix, probs = _fix_and_problems(b)
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg')}".lstrip(": ")
                           for d in detail if isinstance(d, dict))
    if isinstance(detail, dict):
        detail = detail["detail"] if isinstance(detail.get("detail"), str) else json.dumps(detail)[:400]
    if r.status_code >= 500:
        return ToolError("upstream_error", f"{svc.mod.name} failed (HTTP {r.status_code}): {detail}"[:600],
                         fix or "check the mod's Logs tab; try again or change the inputs", probs)
    return ToolError("mod_error", f"{svc.mod.name} refused it (HTTP {r.status_code}): {detail}"[:600],
                     fix or "fix the arguments the message names, then call again", probs)
