"""The model client (plan 14.3): `/v1/chat/completions` on the relay, streamed.

- **No `max_tokens`:** thinking and output may use the whole window.
- **Thinking** arrives as `reasoning` (vLLM) or `reasoning_content` (llama.cpp); it's returned
  separately and never sent back to the model.
- **Tool calls:** native `tool_calls` first; if the model writes the call as text instead (Gemma's
  `<|tool_call>call:name{…}<tool_call|>`, Hermes `<tool_call>{…}</tool_call>`, a lone JSON
  object or a ```json block naming a known tool), it's re-parsed.
- **Usage** (`prompt_tokens`, `completion_tokens`) from the final chunk (`stream_options`).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

Delta = Callable[[str, str], Awaitable[None]]   # (kind: "text" | "thinking", text)

GEMMA_CALL = re.compile(r"<\|tool_call\>\s*call:([A-Za-z0-9_.-]+)\s*(\{.*?\})\s*<tool_call\|>", re.S)
HERMES_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
FENCED = re.compile(r"```(?:json|tool_code|tool)?\s*(\{.*?\})\s*```", re.S)
THINK = re.compile(r"^\s*<(think|thinking)>(.*?)(?:</\1>|$)", re.S)
PLANNING = re.compile(r"^\s*(\*\s*)?(the user\b|user:|i should\b|i need to\b|i will\b|i'll\b|let me\b|now i\b|okay[,.]|ok[,.]|wait[,.]|"
                      r"plan:|first,? i\b|my plan\b|the request\b|the task\b)", re.I)


class TagRouter:
    """Streams content deltas, routing a leading `<think>…</think>` block to "thinking"."""

    def __init__(self) -> None:
        self.buf = ""
        self.mode = "start"      # start → (think →) text

    def feed(self, piece: str) -> list[tuple[str, str]]:
        if self.mode == "text":
            return [("text", piece)]
        self.buf += piece
        if self.mode == "start":
            head = self.buf.lstrip()
            if not head:
                return []
            for tag in ("<think>", "<thinking>"):
                if tag.startswith(head[: len(tag)]) and len(head) < len(tag):
                    return []            # could still become the tag: wait
                if head.startswith(tag):
                    self.mode, self.close, self.buf = "think", tag.replace("<", "</"), head[len(tag):]
                    break
            else:
                self.mode, out, self.buf = "text", self.buf, ""
                return [("text", out)]
        # think: emit up to the closing tag, keeping a possible partial tag back
        i = self.buf.find(self.close)
        if i >= 0:
            out = [("thinking", self.buf[:i])] if self.buf[:i] else []
            rest = self.buf[i + len(self.close):].lstrip("\n")
            self.mode, self.buf = "text", ""
            return out + ([("text", rest)] if rest else [])
        keep = len(self.close) - 1
        out_text, self.buf = self.buf[:-keep] if len(self.buf) > keep else "", self.buf[-keep:] if len(self.buf) > keep else self.buf
        return [("thinking", out_text)] if out_text else []


def split_planning(text: str) -> tuple[str, str]:
    """(thinking, reply): leading paragraphs that are the model planning to itself ("The user
    wants…", "I should…"), when it skipped its thinking channel. Only when a real reply follows."""
    paras = re.split(r"\n\s*\n", text.strip())
    i = 0
    while i < len(paras) and PLANNING.match(paras[i]):
        i += 1
    if 0 < i < len(paras):
        return "\n\n".join(paras[:i]), "\n\n".join(paras[i:])
    return "", text


class LLMError(Exception):
    def __init__(self, detail: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(detail)
        self.detail, self.status, self.retryable = detail, status, retryable


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str   # JSON text as the model wrote it

    def parsed(self) -> tuple[dict[str, Any] | None, str | None]:
        """(arguments, error)."""
        raw = (self.arguments or "").strip() or "{}"
        try:
            v = json.loads(raw)
        except ValueError as e:
            fixed = _loose_json(raw)
            if fixed is not None:
                return fixed, None
            return None, f"arguments aren't valid JSON ({e.msg} at {e.pos})"
        if not isinstance(v, dict):
            return None, "arguments must be a JSON object"
        return v, None


@dataclass
class Reply:
    text: str = ""
    thinking: str = ""
    thinking_s: float = 0.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish: str | None = None
    model: str | None = None
    leaked: bool = False
    split: bool = False          # planning moved out of the reply (split_planning)


def _loose_json(raw: str) -> dict[str, Any] | None:
    """Gemma's argument dialect: `{key:<|"|>text<|"|>,n:3}` → JSON."""
    s = raw.replace('<|"|>', '"')
    s = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
    try:
        v = json.loads(s)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def reparse(text: str, known: set[str]) -> tuple[str, list[ToolCall]]:
    """Tool calls written into the text → (the text without them, calls)."""
    calls: list[ToolCall] = []
    out = text
    for m in GEMMA_CALL.finditer(text):
        args = _loose_json(m.group(2)) or {}
        calls.append(ToolCall(f"tc_{len(calls)}", m.group(1), json.dumps(args)))
        out = out.replace(m.group(0), "")
    for m in HERMES_CALL.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("name"):
            calls.append(ToolCall(f"tc_{len(calls)}", obj["name"], json.dumps(obj.get("arguments") or obj.get("parameters") or {})))
            out = out.replace(m.group(0), "")
    if not calls:
        cands = [m.group(1) for m in FENCED.finditer(text)]
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            cands.append(stripped)
        for c in cands:
            try:
                obj = json.loads(c)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("name") in known:
                calls.append(ToolCall(f"tc_{len(calls)}", obj["name"], json.dumps(obj.get("arguments") or obj.get("parameters") or {})))
                out = out.replace(c, "").replace("```json", "").replace("```", "")
    return out.strip(), calls


class LLM:
    def __init__(self, base_url: str, timeout: float = 1800) -> None:
        self.base = base_url.rstrip("/")
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(timeout, connect=10))
        self._models: tuple[float, list[dict[str, Any]]] = (0.0, [])

    async def close(self) -> None:
        await self.client.aclose()

    async def models(self, max_age: float = 60) -> list[dict[str, Any]]:
        ts, cached = self._models
        if cached and time.time() - ts < max_age:
            return cached
        try:
            r = await self.client.get(self.base + "/models", timeout=8)
            r.raise_for_status()
            data = r.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            return cached
        self._models = (time.time(), data)
        return data

    async def meta(self, model: str) -> dict[str, Any]:
        for m in await self.models():
            if m.get("id") == model:
                return m.get("meta") or {}
        return {}

    async def chat(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   on_delta: Delta | None = None, known: set[str] | None = None) -> Reply:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True,
                                "stream_options": {"include_usage": True}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        reply = Reply(model=model)
        shown = TagRouter()
        calls: dict[int, dict[str, Any]] = {}
        t_think: float | None = None
        try:
            async with self.client.stream("POST", self.base + "/chat/completions", json=body) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode(errors="replace")[:600]
                    raise LLMError(f"HTTP {r.status_code}: {_detail(text)}", r.status_code,
                                   retryable=r.status_code in (404, 429, 500, 502, 503, 504))
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise LLMError(_detail(json.dumps(chunk["error"])), retryable=True)
                    if chunk.get("usage"):
                        reply.usage = {k: int(v) for k, v in chunk["usage"].items() if isinstance(v, (int, float))}
                    for ch in chunk.get("choices") or []:
                        d = ch.get("delta") or {}
                        think = d.get("reasoning") or d.get("reasoning_content")
                        if think:
                            t_think = t_think or time.monotonic()
                            reply.thinking += think
                            if on_delta:
                                await on_delta("thinking", think)
                        if d.get("content"):
                            if t_think and not reply.thinking_s:
                                reply.thinking_s = round(time.monotonic() - t_think, 1)
                            reply.text += d["content"]
                            if on_delta:
                                for kind, piece in shown.feed(d["content"]):
                                    await on_delta(kind, piece)
                        for tc in d.get("tool_calls") or []:
                            slot = calls.setdefault(int(tc.get("index", len(calls))), {"id": None, "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"] if isinstance(fn["arguments"], str) else json.dumps(fn["arguments"])
                        if ch.get("finish_reason"):
                            reply.finish = ch["finish_reason"]
        except httpx.HTTPError as e:
            raise LLMError(f"{type(e).__name__}: {e}"[:400] or type(e).__name__, retryable=True) from None
        if t_think and not reply.thinking_s:
            reply.thinking_s = round(time.monotonic() - t_think, 1)
        for i in sorted(calls):
            c = calls[i]
            if c["name"]:
                reply.tool_calls.append(ToolCall(c["id"] or f"tc_{i}", c["name"], c["arguments"]))
        if reply.text:
            m = THINK.match(reply.text)
            if m:
                reply.thinking = (reply.thinking + "\n" + m.group(2).strip()).strip()
                reply.text = reply.text[m.end():].strip()
            if not reply.thinking:
                plan, rest = split_planning(reply.text)
                if plan:
                    reply.thinking, reply.text, reply.split = plan, rest, True
        if not reply.tool_calls and reply.text and known:
            text, leaked = reparse(reply.text, known)
            if leaked:
                reply.text, reply.tool_calls, reply.leaked = text, leaked, True
        return reply


def _detail(text: str) -> str:
    try:
        j = json.loads(text)
    except ValueError:
        return text[:400]
    if isinstance(j, dict):
        e = j.get("error") if isinstance(j.get("error"), (dict, str)) else j
        if isinstance(e, dict):
            return str(e.get("message") or e.get("detail") or e)[:400]
        return str(e)[:400]
    return text[:400]
