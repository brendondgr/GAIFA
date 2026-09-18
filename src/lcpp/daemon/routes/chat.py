"""Playground proxy: stream an OpenAI chat completion from an instance (or
through Relay) and finish with a ``{"lcpp_metrics": ...}`` event.

Proxying rather than calling the instance from the browser keeps the UI on a
single origin (llama-server's CORS policy never matters) and lets the daemon
measure time to first token the same way for both targets.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fastapi import APIRouter, Body, Request
from fastapi.responses import StreamingResponse

from lcpp.daemon.app import error, state
from lcpp.instances import LcppError

router = APIRouter(prefix="/api", tags=["chat"])


def _metrics(t0: float, first: float | None, end: float, chunks: int,
             usage: dict[str, Any] | None, timings: dict[str, Any] | None) -> dict[str, Any]:
    usage, timings = usage or {}, timings or {}
    ttft = ((first or end) - t0) * 1000
    total = (end - t0) * 1000
    completion = usage.get("completion_tokens") or timings.get("predicted_n") or chunks
    prompt = usage.get("prompt_tokens") or timings.get("prompt_n") or 0
    tps = timings.get("predicted_per_second")
    if not tps:
        gen_s = max(1e-3, (total - ttft) / 1000)
        tps = completion / gen_s
    return {"ttft_ms": round(ttft), "tokens_per_s": round(float(tps), 1),
            "prompt_tokens": int(prompt), "completion_tokens": int(completion), "total_ms": round(total)}


@router.post("/chat")
async def chat(request: Request, body: dict[str, Any] = Body(...)):
    st = state(request)
    target = body.get("target") or {}
    req = dict(body.get("request") or {})
    if target.get("type") == "relay":
        model = str(target.get("model") or "")
        if not model:
            raise LcppError("invalid_param", "target.model is required", 400)
        url = f"{st.settings['relay']['url']}/v1/chat/completions"
        req["model"] = model
        unreachable = ("relay_unreachable", "Relay unreachable")
    else:
        inst = st.supervisor.get(str(target.get("name") or ""))
        if inst.state != "ready":
            raise LcppError("instance_not_found", f"Instance {inst.name} is not ready", 409)
        url = f"{inst.url}/chat/completions"
        # A single-model server serves one model whatever the name; a router
        # needs a model it actually has (the UI may send a relay alias).
        if inst.kind == "single":
            req["model"] = inst.model_id
        elif req.get("model") not in inst.model_ids:
            req["model"] = inst.model_ids[0]
        unreachable = ("instance_not_found", f"Instance {inst.name} is not answering")
    req["stream"] = True
    req["stream_options"] = {"include_usage": True}

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=3.0))
    t0 = time.monotonic()
    try:
        resp = await client.send(client.build_request("POST", url, json=req), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return error(*unreachable, 502)
    if resp.status_code >= 400:
        raw = await resp.aread()
        await resp.aclose()
        await client.aclose()
        try:
            detail = json.loads(raw).get("error", {}).get("message") or raw.decode()
        except (ValueError, AttributeError):
            detail = raw.decode(errors="replace")
        code = "model_not_found" if resp.status_code == 404 else "daemon_error"
        return error(code, f"upstream {resp.status_code}: {detail[:500]}", 502)

    async def events():
        first: float | None = None
        chunks = 0
        usage = timings = None
        try:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    j = json.loads(data)
                except ValueError:
                    continue
                usage = j.get("usage") or usage
                timings = j.get("timings") or timings
                for choice in j.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content"):
                        chunks += 1
                        first = first or time.monotonic()
                yield f"data: {data}\n\n"
        except httpx.HTTPError as e:
            msg = {"error": {"message": f"{unreachable[1]}: stream ended ({e.__class__.__name__})",
                             "code": unreachable[0]}}
            yield f"data: {json.dumps(msg)}\n\n"
            return
        finally:
            await resp.aclose()
            await client.aclose()
        m = _metrics(t0, first, time.monotonic(), chunks, usage, timings)
        yield f"data: {json.dumps({'lcpp_metrics': m})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
