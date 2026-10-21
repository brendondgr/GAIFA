"""A scripted OpenAI-compatible model server (plan 14.11).

Tests queue replies; each `POST /v1/chat/completions` streams the next one and records the request.
A reply is a dict:

    {"text": "…", "thinking": "…", "tool_calls": [{"name": "x", "arguments": {...} | "raw json"}],
     "leaked": "<|tool_call>call:x{a:1}<tool_call|>",   # written into the text instead of tool_calls
     "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "status": 503, "delay": 0.5, "chunk": 8,
     "field": "reasoning" | "reasoning_content", "match": "substring the request must contain"}

With no reply queued, it answers "ok". `/v1/models` lists `models` with their `meta`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


class FakeModel:
    def __init__(self) -> None:
        self.script: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []
        self.titles = 0
        self.title = "Test title"                       # what the model answers when asked for a title
        self.title_asks: list[dict[str, Any]] = []      # those requests
        self.models: dict[str, dict[str, Any]] = {
            "main": {"context_length": 8000, "tools": True, "vision": True, "reasoning": True},
            "backup": {"context_length": 16000, "tools": True, "vision": False, "reasoning": False},
            "blind": {"context_length": 8000, "tools": True, "vision": False, "reasoning": False}}
        self.down: set[str] = set()
        self.app = self._app()

    def queue(self, *replies: dict[str, Any]) -> None:
        self.script.extend(replies)

    def _pick(self, body: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(body)
        if "Give this chat a short title" in text:
            self.titles += 1
            self.title_asks.append(body)
            return {"text": self.title}
        for i, r in enumerate(self.script):
            if r.get("match") and r["match"] not in text:
                continue
            return self.script.pop(i)
        return {"text": "ok"}

    def _app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/v1/models")
        def models() -> dict:
            return {"object": "list", "data": [{"id": k, "object": "model", "meta": v,
                                                "relay": {"endpoint": k, "health": "healthy", "protocol": "openai"}}
                                               for k, v in self.models.items()]}

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            if "Give this chat a short title" not in json.dumps(body):
                self.received.append(body)
            if body.get("model") in self.down:
                return JSONResponse({"error": {"message": f"{body['model']} is down"}}, status_code=502)
            r = self._pick(body)
            if r.get("status"):
                return JSONResponse({"error": {"message": r.get("text") or "scripted failure"}}, status_code=r["status"])
            if body.get("stream") is False:
                calls = [{"id": tc.get("id") or f"call_{i}", "type": "function",
                          "function": {"name": tc["name"], "arguments": tc["arguments"] if isinstance(tc.get("arguments"), str)
                                       else json.dumps(tc.get("arguments") or {})}} for i, tc in enumerate(r.get("tool_calls") or [])]
                msg = {"role": "assistant", "content": (r.get("text") or "") + (r.get("leaked") or "")}
                if r.get("thinking"):
                    msg["reasoning"] = r["thinking"]
                if calls:
                    msg["tool_calls"] = calls
                return {"choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
                        "usage": r.get("usage") or {"prompt_tokens": 100, "completion_tokens": 10}}
            return StreamingResponse(self._stream(r, body), media_type="text/event-stream")

        return app

    async def _stream(self, r: dict[str, Any], body: dict[str, Any]):
        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            return "data: " + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

        n = int(r.get("chunk") or 8)
        if r.get("delay"):
            await asyncio.sleep(r["delay"])
        field = r.get("field") or "reasoning"
        for i in range(0, len(r.get("thinking") or ""), n):
            yield chunk({field: r["thinking"][i:i + n]})
            await asyncio.sleep(0)
        text = (r.get("text") or "") + (r.get("leaked") or "")
        for i in range(0, len(text), n):
            yield chunk({"content": text[i:i + n]})
            await asyncio.sleep(r.get("gap", 0))
        for idx, tc in enumerate(r.get("tool_calls") or []):
            args = tc["arguments"] if isinstance(tc.get("arguments"), str) else json.dumps(tc.get("arguments") or {})
            yield chunk({"tool_calls": [{"index": idx, "id": tc.get("id") or f"call_{idx}_{len(self.received)}", "type": "function",
                                         "function": {"name": tc["name"], "arguments": ""}}]})
            for i in range(0, len(args), n):
                yield chunk({"tool_calls": [{"index": idx, "function": {"arguments": args[i:i + n]}}]})
        yield chunk({}, "tool_calls" if r.get("tool_calls") else "stop")
        usage = r.get("usage") or {"prompt_tokens": len(json.dumps(body["messages"])) // 4, "completion_tokens": max(1, len(text) // 4)}
        yield "data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n"
        yield "data: [DONE]\n\n"
