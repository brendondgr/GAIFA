"""Context (plan 14.7): the model's messages rebuilt from the event log, the meter, and compaction.

- **Messages:** user turns, assistant steps (text + tool calls), and each step's tool results
  placed right after it (a message queued during a turn lands after them). Thinking is never
  sent back. A compaction summary replaces everything up to its `upto_seq`; cleared results
  become one-line stubs (`read_result` brings them back).
- **Meter:** the last response's `prompt_tokens + completion_tokens`, plus an estimate (4
  characters per token) of what was added since. The breakdown is estimated per section and
  scaled to the real total when the model has reported usage.
- **Compaction:** at 70% old tool results are cleared; at 85% older turns are summarized; if
  that can't get under 70% the turn stops and says so (no loop).
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4
RESULT_CAP_TOKENS = 4000
CLEAR_AT = 0.70
SUMMARIZE_AT = 0.85
KEEP_TURNS = 2
MAX_IMAGES = 2


def est(obj: Any) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return max(1, len(text) // CHARS_PER_TOKEN)


def cap_text(text: str, tokens: int = RESULT_CAP_TOKENS) -> tuple[str, bool]:
    limit = tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n…[cut at {tokens} tokens of {len(text) // CHARS_PER_TOKEN}; read the rest with read_result]", True


def outputs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every output made in the thread, in order, with its #n."""
    out = []
    for e in events:
        if e["type"] == "tool_result":
            for o in e["payload"].get("outputs") or []:
                out.append({**o, "tool": e["payload"].get("name"), "seq": e["seq"]})
    return out


def summary_state(events: list[dict[str, Any]]) -> tuple[str, int, set[int]]:
    """(the latest summary, the seq it covers, the cleared result seqs)."""
    summary, upto, cleared = "", 0, set()
    for e in events:
        if e["type"] == "compact":
            p = e["payload"]
            if p.get("stage") == "summary":
                summary, upto = p.get("summary") or "", int(p.get("upto_seq") or 0)
            cleared |= set(p.get("cleared") or [])
    return summary, upto, cleared


def _call_msg(step: list[dict[str, Any]]) -> dict[str, Any]:
    text = "".join(e["payload"].get("text", "") for e in step if e["type"] == "assistant")
    calls = [{"id": e["payload"]["id"], "type": "function",
              "function": {"name": e["payload"]["name"], "arguments": json.dumps(e["payload"].get("arguments") or {}, ensure_ascii=False)}}
             for e in step if e["type"] == "tool_call"]
    msg: dict[str, Any] = {"role": "assistant", "content": text or ("" if calls else "…")}
    if calls:
        msg["tool_calls"] = calls
    return msg


def result_content(e: dict[str, Any], cleared: bool) -> str:
    p = e["payload"]
    if cleared:
        return f"[result cleared to save context: {p.get('status')}; read_result({e['seq']}) shows it again]"
    content = p.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return cap_text(text)[0]


def rebuild(events: list[dict[str, Any]], images: dict[int, dict[str, Any]] | None = None,
            pending_ok: bool = False) -> tuple[list[dict[str, Any]], int]:
    """The conversation messages (without the system prompt) and the seq they were built up to.
    `images`: tool-result seq → `{"url": data-url, "label": …}` for `view_output` (newest kept)."""
    _, upto, cleared = summary_state(events)
    results = {e["payload"]["id"]: e for e in events if e["type"] == "tool_result"}
    image_seqs = sorted(images or {})[-MAX_IMAGES:]
    msgs: list[dict[str, Any]] = []
    step: list[dict[str, Any]] = []
    step_id: Any = None

    def flush() -> None:
        nonlocal step, step_id
        if not step:
            return
        by_user = [e for e in step if e["type"] == "tool_call" and e["payload"].get("by") == "user"]
        if by_user:      # a button: say so, or the model takes the call (and its result) for its own
            names = ", ".join(e["payload"]["name"] for e in by_user)
            msgs.append({"role": "user", "content": f"(I pressed a button that ran {names} directly; its result follows.)"})
        m = _call_msg(step)
        msgs.append(m)
        img_msgs = []
        for c in m.get("tool_calls") or []:
            r = results.get(c["id"])
            if r is None:
                if pending_ok:
                    continue
                content = "[not run: the chat moved on before this call finished]"
            else:
                content = result_content(r, r["seq"] in cleared)
                if r["seq"] in image_seqs and images and r["seq"] in images:
                    im = images[r["seq"]]
                    img_msgs.append({"role": "user", "content": [
                        {"type": "text", "text": f"(the image from view_output: {im.get('label', '')})"},
                        {"type": "image_url", "image_url": {"url": im["url"]}}]})
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": content})
        msgs.extend(img_msgs)
        step, step_id = [], None

    last = 0
    for e in events:
        last = e["seq"]
        if e["seq"] <= upto:
            continue
        t, p = e["type"], e["payload"]
        if t in ("assistant", "tool_call", "thinking"):
            sid = p.get("step")
            if step and sid != step_id:
                flush()
            if t != "thinking":
                step.append(e)
                step_id = sid
            continue
        if t == "user":
            flush()
            text = p.get("text") or ""
            if p.get("attachments"):
                text += "\n\n(attached: " + ", ".join(f"output:{a}" for a in p["attachments"]) + ")"
            msgs.append({"role": "user", "content": text})
        # tool results are placed with their step; everything else isn't sent to the model
    flush()
    return msgs, last


def meter(events: list[dict[str, Any]], window: int | None, parts: dict[str, int]) -> dict[str, Any]:
    """`{used, window, percent, breakdown, estimated}`. `parts`: estimated tokens per section."""
    last_usage = None
    for e in events:
        if e["type"] == "usage":
            last_usage = e
    est_total = sum(parts.values())
    if last_usage and any(e["type"] == "compact" and e["seq"] > last_usage["seq"] for e in events):
        last_usage = None       # compacted since the model last counted: the estimate of what's left is closer
    if last_usage:
        u = last_usage["payload"]
        # completion_tokens includes the thinking, which is never sent back: leave it out
        thought = sum(est(e["payload"].get("text") or "") for e in events
                      if e["type"] == "thinking" and e["seq"] < last_usage["seq"] and e["seq"] > last_usage["seq"] - 6)
        base = int(u.get("prompt_tokens") or 0) + max(0, int(u.get("completion_tokens") or 0) - thought)
        added = sum(est({k: v for k, v in e["payload"].items() if k != "thinking"}) for e in events
                    if e["seq"] > last_usage["seq"] and e["type"] in ("user", "tool_result", "assistant", "tool_call"))
        used = base + added
        scale = used / est_total if est_total else 1
    else:
        used, scale = est_total, 1.0
    breakdown = {k: int(v * scale) for k, v in parts.items()}
    return {"used": used, "window": window, "percent": round(100 * used / window, 1) if window else None,
            "breakdown": breakdown, "estimated": last_usage is None}


def turn_starts(events: list[dict[str, Any]]) -> list[int]:
    return [e["seq"] for e in events if e["type"] == "user"]


def clear_candidates(events: list[dict[str, Any]]) -> list[int]:
    """Tool results older than the last KEEP_TURNS user turns, not cleared yet, worth clearing."""
    starts = turn_starts(events)
    if len(starts) <= KEEP_TURNS:
        keep_from = starts[0] if starts else 0
        keep_from = max(keep_from, 0)
        # within the first turns: still clear results older than the newest step
        last_results = [e["seq"] for e in events if e["type"] == "tool_result"][-3:]
        keep_from = min(last_results) if last_results else keep_from
    else:
        keep_from = starts[-KEEP_TURNS]
    _, upto, cleared = summary_state(events)
    return [e["seq"] for e in events if e["type"] == "tool_result" and keep_from > e["seq"] > upto
            and e["seq"] not in cleared and est(e["payload"].get("content") or "") > 60]


def summary_cut(events: list[dict[str, Any]]) -> int | None:
    """The seq to summarize up to: before the last KEEP_TURNS user turns (None if too short)."""
    starts = turn_starts(events)
    if len(starts) <= KEEP_TURNS:
        return None
    _, upto, _ = summary_state(events)
    cut = starts[-KEEP_TURNS] - 1
    return cut if cut > upto else None
