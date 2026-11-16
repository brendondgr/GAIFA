"""The model client (plan 14.3): `/v1/chat/completions` on the relay, streamed.

- **No `max_tokens`:** thinking and output may use the whole window. A reply that degenerates into
  repeating one span (`looping`) is cut off instead (`Reply.runaway`); the loop asks once more.
- **Thinking** arrives as `reasoning` (vLLM) or `reasoning_content` (llama.cpp); it's returned
  separately and never sent back to the model.
- **Tool calls:** native `tool_calls` first; if the model writes the call as text instead (Gemma's
  `<|tool_call>call:name{…}<tool_call|>`, Hermes `<tool_call>{…}</tool_call>`, a lone JSON
  object or a ```json block naming a known tool), it's re-parsed.
- **Usage** (`prompt_tokens`, `completion_tokens`) from the final chunk (`stream_options`).
- **Control tokens** in user and tool messages (`<|turn>`, `<|im_start|>`, `[INST]`, … typed, attached, or in a page
  or file a tool read) are defused before sending (`defuse`): llama.cpp parses special tokens in the rendered prompt,
  so such text could otherwise open a turn of its own.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx

Delta = Callable[[str, str], Awaitable[None]]   # (kind: "text" | "thinking", text)
# The chat a model call belongs to, sent as X-GAIFA-Thread: the relay names it on the request's GPU lease (plan 31.4),
# so the turn can say it is waiting for the GPU. Set for the length of one model call (`Agent._model`).
THREAD: ContextVar[str | None] = ContextVar("gaifa_thread", default=None)
CHECK_S = 5.0          # how often a model call's stall clock is read


class GpuWait:
    """Whether this model call waits for GAIFA's GPU slot (gpuwait.watch sets it, plan 31.4). The client's
    timeout is a stall limit, and time spent waiting behind a GPU job doesn't count toward it."""

    def __init__(self) -> None:
        self.on, self.since = False, time.monotonic()

    def set(self, on: bool) -> None:
        if on != self.on:
            self.on, self.since = on, time.monotonic()


GPU_WAIT: ContextVar[GpuWait | None] = ContextVar("gaifa_gpu_wait", default=None)


def _headers() -> dict[str, str]:
    """A call that belongs to a chat names it (the GPU lease) and says it's a chat: the relay lets only
    chats reach a cloud model (plan llm-servers 2.1). Background work (summaries, the learner) sets no thread."""
    tid = THREAD.get()
    return {"X-GAIFA-Thread": tid, "X-GAIFA-Purpose": "chat"} if tid else {}


def for_model(messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """`reasoning_details` (a provider's hidden state: Claude's thinking signatures, Gemini's parts) goes back
    only to the model that produced it; `details_model` names it and is never sent."""
    out = []
    for m in messages:
        if "details_model" in m or "reasoning_details" in m:
            m = dict(m)
            if m.pop("details_model", None) != model:
                m.pop("reasoning_details", None)
        out.append(m)
    return out

# Gemma's own `<|tool_call>call:name{…}<tool_call|>`, also written as `<call:name{…}</call>` by the 26B
GEMMA_CALL = re.compile(r"(?:<\|tool_call\>\s*)?<?(?:call:)?([A-Za-z0-9_.-]+)\s*(\{.*?\})\s*(?:<tool_call\|>|</call>)", re.S)
HERMES_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
TAG_CALL = re.compile(r"<([A-Za-z][A-Za-z0-9_]*)>\s*(\{.*?\})\s*</\1>", re.S)    # <ask_user>{…}</ask_user> (the 26B)
FENCED = re.compile(r"```(?:json|tool_code|tool)?\s*(\{.*?\})\s*```", re.S)
ONE_FENCE = re.compile(r"^```[A-Za-z_]*\s*\n?(.*?)\s*```$", re.S)
CHANNEL_OPEN = re.compile(r"<\|channel\>(?:thought|analysis|final)?\s*")
THINK = re.compile(r"^\s*<(think|thinking)>(.*?)(?:</\1>|$)", re.S)
# Chat-template control tokens (the hub's utils/tools/judge.py SPECIAL_TOKENS: mods don't import the hub)
SPECIAL_TOKENS = re.compile(
    r"<\|[^<>|\n]{0,40}\|>|<\|[A-Za-z_][\w.-]{0,40}>|<[A-Za-z_][\w.-]{0,40}\|>|<｜[^<>｜\n]{0,40}｜>"
    r"|</?(?:start_of_turn|end_of_turn|start_of_image|end_of_image|s|think|thinking|bos|eos|pad|unk|mask|tool_call"
    r"|tool_response)>|\[/?(?:INST|SYSTEM_PROMPT|TOOL_CALLS|AVAILABLE_TOOLS|TOOL_RESULTS|THINK)\]|<<\s*/?SYS\s*>>", re.I)
PLANNING = re.compile(r"^\s*(\*\s*)?(the user\b|user:|i should\b|i need to\b|i will\b|i'll\b|let me\b|now i\b|okay[,.]|ok[,.]|wait[,.]|"
                      r"plan:|first,? i\b|my plan\b|the request\b|the task\b)", re.I)


def defuse(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`messages` with each control-token look-alike in user and tool text made inert (its first `<` or `[` becomes
    `‹` or `［`); the system prompt and the model's own turns are sent as they are."""
    def fix(text: str) -> str:
        return SPECIAL_TOKENS.sub(lambda m: {"<": "‹", "[": "［"}[m.group(0)[0]] + m.group(0)[1:], text)
    out = []
    for m in messages:
        c = m.get("content")
        if m.get("role") in ("user", "tool") and isinstance(c, str):
            m = {**m, "content": fix(c)}
        elif m.get("role") in ("user", "tool") and isinstance(c, list):
            m = {**m, "content": [{**p, "text": fix(p["text"])} if isinstance(p, dict) and isinstance(p.get("text"), str)
                                  else p for p in c]}
        out.append(m)
    return out


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
            if fixed is None:
                fixed = close_json(raw)
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
    details: list[dict[str, Any]] = field(default_factory=list)   # reasoning_details to send back next turn
    leaked: bool = False
    split: bool = False          # planning moved out of the reply (split_planning)
    runaway: bool = False        # cut off: the model kept repeating itself (looping)


LOOP_WINDOW, LOOP_SPAN, LOOP_REPEATS = 8000, 300, 10


def looping(text: str) -> bool:
    """The end of the text is one span repeated over and over (a degenerate generation: the 26B
    once streamed 23,762 tokens in 9 minutes). Needs ≥ 3,000 characters of exact repetition."""
    if len(text) < LOOP_SPAN * LOOP_REPEATS:
        return False
    tail = text[-LOOP_WINDOW:]
    return tail.count(tail[-LOOP_SPAN:]) >= LOOP_REPEATS


def close_json(raw: str) -> dict[str, Any] | None:
    """JSON cut short at the end → closed (open string, objects and arrays). vLLM's streaming
    Gemma 4 tool parser drops the closing `"}` of every call but the last when a reply has several."""
    stack: list[str] = []
    in_str = esc = False
    for ch in raw:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return None
    if not stack and not in_str:
        return None
    s = raw + ('"' if in_str else "")
    t = s.rstrip()
    if t.endswith(","):
        s = t[:-1]
    elif t.endswith(":"):
        s = t + " null"
    s += "".join(reversed(stack))
    try:
        v = json.loads(s)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


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
        if m.group(1) not in known and not m.group(0).lstrip().startswith("<|tool_call>"):
            continue          # without the opening tag, only a known tool name counts
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
        for m in TAG_CALL.finditer(text):
            if m.group(1) in known and (args := _loose_json(m.group(2))) is not None:
                calls.append(ToolCall(f"tc_{len(calls)}", m.group(1), json.dumps(args)))
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
    if not calls and (py := _python_calls(text, known)):
        return "", [ToolCall(f"tc_{i}", name, json.dumps(args)) for i, (name, args) in enumerate(py)]
    return out.strip(), calls


def _python_calls(text: str, known: set[str]) -> list[tuple[str, dict[str, Any]]] | None:
    """A reply that is nothing but Python-style calls of known tools with literal keyword arguments,
    e.g. `comfy_generate_image(aspect='9:16', prompt='a heron')` (the 26B now and then). Parsed, never run."""
    body = text.strip()
    if m := ONE_FENCE.match(body):
        body = m.group(1)
    body = body.strip("`").strip()
    if "(" not in body:
        return None
    try:
        tree = ast.parse(body, mode="exec")
    except SyntaxError:
        return None
    out = []
    for st in tree.body:
        call = st.value if isinstance(st, ast.Expr) else None
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print" and len(call.args) == 1:
            call = call.args[0]       # print(tool(...))
        if not isinstance(call, ast.Call) or call.args:
            return None
        f = call.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None   # tool(...) / default_api.tool(...)
        if name not in known:
            return None
        args: dict[str, Any] = {}
        for kw in call.keywords:
            if kw.arg is None:
                return None
            try:
                args[kw.arg] = ast.literal_eval(kw.value)
            except (ValueError, SyntaxError):
                return None
        out.append((name, args))
    return out or None


class LLM:
    def __init__(self, base_url: str, timeout: float = 1800, key: str | None = None, direct_window: int = 8192) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout       # seconds without a byte from the model, not counting a wait for the GPU (_guarded)
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(None, connect=10))
        self._models: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self.key = key or None       # capability-enablement 6.1: AGENT_LLM_KEY, a bearer token for a direct endpoint
        self.direct_window = direct_window   # AGENT_WINDOW: a direct endpoint's window when it says none
        self._status: tuple[float, dict[str, Any]] = (0.0, {})

    def headers(self) -> dict[str, str]:
        """The chat's own headers (the relay's GPU lease and cloud rule), and the key for a direct endpoint."""
        return {**_headers(), **({"Authorization": f"Bearer {self.key}"} if self.key else {})}

    def kind(self, models: list[dict[str, Any]] | None = None) -> str:
        """relay: GAIFA's relay (its /v1/models rows carry `relay`); direct: any other OpenAI-compatible server."""
        rows = self._models[1] if models is None else models
        if rows:
            return "relay" if any(isinstance(m.get("relay"), dict) for m in rows) else "direct"
        return "relay" if self.base.startswith(("http://127.0.0.1:4000", "http://localhost:4000")) else "direct"

    async def status(self, max_age: float = 30) -> dict[str, Any]:
        """{url, kind, answers, models, detail}: probed at most every `max_age` s (capability-enablement 6.1)."""
        ts, cached = self._status
        if cached and time.time() - ts < max_age:
            return cached
        try:
            r = await self.client.get(self.base + "/models", headers=self.headers(), timeout=8)
            r.raise_for_status()
            rows = r.json().get("data") or []
            self._models = (time.time(), rows)
            out = {"answers": True, "models": [m.get("id") for m in rows if m.get("id")], "detail": ""}
        except httpx.HTTPStatusError as e:
            out = {"answers": False, "models": [], "detail": f"{self.base} answered HTTP {e.response.status_code}" +
                   (" (a key is needed: AGENT_LLM_KEY)" if e.response.status_code in (401, 403) else "")}
        except (httpx.HTTPError, ValueError) as e:
            out = {"answers": False, "models": [], "detail": f"nothing answers at {self.base} ({type(e).__name__})"}
        kind = self.kind()
        if kind == "direct" and out["answers"]:
            out["detail"] = (f"a server of yours: no relay facts, so a {self.direct_window:,}-token window, tools on and "
                             "pictures off are assumed")
        out = {"url": self.base, "kind": kind, **out}
        self._status = (time.time(), out)
        return out

    async def close(self) -> None:
        await self.client.aclose()

    async def models(self, max_age: float = 60) -> list[dict[str, Any]]:
        ts, cached = self._models
        if cached and time.time() - ts < max_age:
            return cached
        try:
            r = await self.client.get(self.base + "/models", headers=self.headers(), timeout=8)
            r.raise_for_status()
            data = r.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            return cached
        self._models = (time.time(), data)
        return data

    async def is_cloud(self, model: str) -> bool:
        """A paid provider's model (the relay's `cloud` group): for chats only."""
        for m in await self.models():
            if m.get("id") == model:
                return (m.get("relay") or {}).get("group") == "cloud"
        return False

    async def background_model(self, model: str | None, default: str) -> str | None:
        """The model background work (summaries, memory learning) uses for a chat: the chat's own when the relay
        serves it and it isn't a paid provider's (plan llm-servers 2.1), else `default`; None while neither is served."""
        served = {m.get("id") for m in await self.models()}
        model = model or default
        if model != default and (model not in served or await self.is_cloud(model)):
            model = default
        return model if model in served else None

    async def meta(self, model: str) -> dict[str, Any]:
        rows = await self.models()
        for m in rows:
            if m.get("id") == model:
                if m.get("meta"):
                    return m["meta"]
                break
        if rows and self.kind(rows) == "direct":          # capability-enablement 6.1: safe defaults without the relay's facts
            return {"context_length": self.direct_window, "tools": True, "vision": False, "assumed": True}
        return {}

    async def _guarded(self, work: Awaitable[Any], progress: list[float]) -> Any:
        """`work`, failed when nothing arrives for `timeout` s (`progress[0]`: the last byte). While the call waits
        for the GPU slot the clock stops, so a chat waits out a long job instead of failing at 30 min."""
        task = asyncio.ensure_future(work)
        wait = GPU_WAIT.get()
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=min(CHECK_S, self.timeout))
                if done:
                    return task.result()
                if wait is not None and wait.on:
                    continue
                last = max(progress[0], wait.since if wait is not None else 0.0)
                if time.monotonic() - last > self.timeout:
                    raise LLMError(f"the model sent nothing for {self.timeout:g} s", retryable=True)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _once(self, body: dict[str, Any], reply: Reply) -> None:
        """A non-streaming request (the fallback when a streamed reply came back empty)."""
        try:
            r = await self._guarded(self.client.post(self.base + "/chat/completions", json={**body, "stream": False},
                                                     headers=self.headers()), [time.monotonic()])
        except httpx.HTTPError as e:
            raise LLMError(f"{type(e).__name__}: {e}"[:400], retryable=True) from None
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {_detail(r.text[:600])}", r.status_code, retryable=r.status_code in (429, 500, 502, 503, 504))
        d = r.json()
        m = (d.get("choices") or [{}])[0].get("message") or {}
        reply.text = m.get("content") or ""
        reply.thinking = m.get("reasoning") or m.get("reasoning_content") or ""
        reply.details = list(m.get("reasoning_details") or [])
        for i, tc in enumerate(m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            reply.tool_calls.append(ToolCall(tc.get("id") or f"tc_{i}", fn.get("name") or "", args if isinstance(args, str) else json.dumps(args or {})))
        reply.usage = {k: int(v) for k, v in (d.get("usage") or {}).items() if isinstance(v, (int, float))}

    async def chat(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   on_delta: Delta | None = None, known: set[str] | None = None, stream: bool = True,
                   tool_choice: str = "auto") -> Reply:
        body: dict[str, Any] = {"model": model, "messages": defuse(for_model(messages, model)), "stream": True,
                                "stream_options": {"include_usage": True}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        reply = Reply(model=model)
        if not stream:
            body.pop("stream_options")
            await self._once(body, reply)
            return self._finish(reply, known)
        shown = TagRouter()
        calls: dict[int, dict[str, Any]] = {}
        t_think: float | None = None
        checked = 0          # length of thinking + text at the last `looping` check
        progress = [time.monotonic()]

        async def consume() -> None:
            nonlocal t_think, checked
            async with self.client.stream("POST", self.base + "/chat/completions", json=body, headers=self.headers()) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode(errors="replace")[:600]
                    raise LLMError(f"HTTP {r.status_code}: {_detail(text)}", r.status_code,
                                   retryable=r.status_code in (404, 429, 500, 502, 503, 504))
                async for line in r.aiter_lines():
                    progress[0] = time.monotonic()
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
                        if d.get("reasoning_details"):
                            reply.details.extend(d["reasoning_details"])
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
                    if len(reply.thinking) + len(reply.text) - checked >= 1000:
                        checked = len(reply.thinking) + len(reply.text)
                        if looping(reply.thinking) or looping(reply.text):
                            reply.runaway = True
                            reply.finish = "runaway"
                            break       # leaving the stream closes it, and the server stops generating

        try:
            await self._guarded(consume(), progress)
        except httpx.HTTPError as e:
            raise LLMError(f"{type(e).__name__}: {e}"[:400] or type(e).__name__, retryable=True) from None
        if t_think and not reply.thinking_s:
            reply.thinking_s = round(time.monotonic() - t_think, 1)
        for i in sorted(calls):
            c = calls[i]
            if c["name"]:
                reply.tool_calls.append(ToolCall(c["id"] or f"tc_{i}", c["name"], c["arguments"]))
        return self._finish(reply, known)

    def _finish(self, reply: Reply, known: set[str] | None) -> Reply:
        """Thinking markers and tool calls written as text, after the reply is complete."""
        if reply.text and "<channel|>" in reply.text:
            # Gemma 4's thought channel when the server's reasoning parser missed its opening:
            # "<|channel>thought …<channel|>reply" or just "…<channel|>reply"
            before, _, after = reply.text.rpartition("<channel|>")
            before = CHANNEL_OPEN.sub("", before).strip()
            reply.thinking = (reply.thinking + "\n" + before).strip()
            reply.text = after.strip()
        if reply.text:
            reply.text = CHANNEL_OPEN.sub("", reply.text)
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
