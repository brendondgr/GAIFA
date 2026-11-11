"""Voice mode on a speech-to-speech model (plan voice-speech-model 2.3): the voice mod answers by itself, so the
agent only gives it what the chat knows and writes each spoken turn into the chat.

    GET  /v1/threads/{tid}/voice-context   the profile, the calendar, a short project, and the last turns as text
    POST /v1/threads/{tid}/voice-turn      a `user` and an `assistant` event, with no model call

The events are ordinary ones (`via: "voice"`), so the chat shows the talk and the chat's own model reads it the
next time you type.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import context as ctx
from .prompting import thread_settings

log = logging.getLogger(__name__)

HISTORY_CHARS = 24000            # about 6,000 tokens of the model's 32K
PROJECT_TOKENS = 2000
TURN_CHARS = 2000                # one turn's share of the history


class VoiceTurn(BaseModel):
    user: str = Field(min_length=1, max_length=8000, description="What you said, as text")
    assistant: str = Field("", max_length=16000, description="What the model said (as far as it was heard, when interrupted)")
    model: str = Field("voice", max_length=120)
    first_audio_ms: int | None = Field(None, ge=0)
    interrupted: bool = False


def history(events: list[dict[str, Any]], limit: int = HISTORY_CHARS) -> list[dict[str, str]]:
    """The chat's messages as text, newest kept: what you wrote and what was answered, no tool calls or results."""
    _, upto, _ = ctx.summary_state(events)
    turns: list[dict[str, str]] = []
    for e in events:
        if e["seq"] <= upto:
            continue
        p = e["payload"]
        if e["type"] == "user" and (text := ctx.said(p).strip()):
            turns.append({"role": "user", "text": text[:TURN_CHARS]})
        elif e["type"] == "assistant" and (text := str(p.get("text") or "").strip()):
            if turns and turns[-1]["role"] == "assistant":        # the steps of one turn read as one answer
                turns[-1]["text"] = (turns[-1]["text"] + " " + text)[:TURN_CHARS]
            else:
                turns.append({"role": "assistant", "text": text[:TURN_CHARS]})
    kept: list[dict[str, str]] = []
    used = 0
    for t in reversed(turns):
        used += len(t["text"]) + 12
        if used > limit:
            break
        kept.append(t)
    return list(reversed(kept))


async def instructions(agent: Any, tid: str) -> str:
    """What every prompt of this chat carries that a small spoken model can use: who you are, your days, the project."""
    from .knowledge import Knowledge

    st = thread_settings(agent.store, tid) or {}
    project = agent.project_of(tid)
    parts: list[str] = []
    try:
        services = await agent.hub.services()
    except Exception:  # noqa: BLE001
        services = None
    try:
        _, tree = agent.harness_of(tid)
        k = Knowledge(agent.cfg.data, agent.hub, tree, agent.memory)
        fdata = await ctx.chat_folders(agent.hub, tid, st, services, set(), agent.projects)
        profile = k.profile((fdata or {}).get("folders"), (project or {}).get("id"),
                            user=st.get("use_profile", True) is not False,
                            own_project=st.get("use_project_memory", True) is not False)
        if profile:
            parts.append(profile.strip())
    except Exception as e:  # noqa: BLE001
        log.warning("voice context: no profile (%s)", e)
    try:
        if agenda := await ctx.chat_agenda(agent.hub, services, set(), (project or {}).get("id")):
            parts.append(agenda.strip())
    except Exception as e:  # noqa: BLE001
        log.warning("voice context: no agenda (%s)", e)
    if project is not None:
        from .projects import knowledge

        text = knowledge.project_text(project)
        if text and ctx.est(text) <= PROJECT_TOKENS:
            parts.append(text.strip())
    return "\n\n".join(parts)


def add_routes(app: FastAPI) -> None:
    def agent_of(request: Request) -> Any:
        return request.app.state.agent

    def thread_or_404(agent: Any, tid: str) -> dict[str, Any]:
        t = agent.store.thread(tid)
        if t is None:
            raise HTTPException(404, {"code": "not_found", "detail": f"no thread {tid!r}"})
        return t

    @app.get("/v1/threads/{tid}/voice-context", summary="What a voice session starts with: the profile, the calendar, a short "
             "project, and the chat's last turns as text (plan voice-speech-model 2.3)")
    async def voice_context(tid: str, request: Request) -> dict[str, Any]:
        agent = agent_of(request)
        thread_or_404(agent, tid)
        return {"instructions": await instructions(agent, tid), "history": history(agent.store.events(tid)),
                "language": None}

    @app.post("/v1/threads/{tid}/voice-turn", status_code=201, summary="Write one spoken turn into the chat: your words and "
              "the speech model's answer, with no model call")
    async def voice_turn(tid: str, body: VoiceTurn, request: Request) -> dict[str, Any]:
        from .loop import _title_from

        agent = agent_of(request)
        thread = thread_or_404(agent, tid)
        if agent.busy(tid):
            raise HTTPException(409, {"code": "turn_running", "detail": "the chat's own turn is running"})
        user = agent.emit(tid, "user", {"text": body.user.strip(), "via": "voice"})
        if not thread["title"]:
            agent.store.update_thread(tid, title=_title_from(body.user))
        out = {"user_seq": user["seq"], "assistant_seq": None}
        if body.assistant.strip():
            ev = agent.emit(tid, "assistant", {
                "text": body.assistant.strip(), "model": body.model, "via": "voice", "step": f"voice-{user['seq']}",
                **({"interrupted": True} if body.interrupted else {}),
                **({"first_audio_ms": body.first_audio_ms} if body.first_audio_ms is not None else {})})
            out["assistant_seq"] = ev["seq"]
        return out
