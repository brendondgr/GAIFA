"""GAIFA's [llm] engine contract (plan llm-servers 3.2): the same four routes every local LLM engine
serves, so the hub, Settings → LLMs and the Chat picker treat vLLM and llama.cpp alike. They wrap the
profile routes: a catalog entry is a profile, load starts it (one at a time, so another stops first),
unload stops it."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from .engine import Engine, EngineError
from .profiles import load_profiles

router = APIRouter()
GB = 1024 ** 3


def _loaded(eng: Engine) -> list[str]:
    return [eng.profile.id] if eng.profile and eng.state in ("starting", "ready") else []


@router.get("/v1/llm/catalog", summary="What vLLM can run: each profile as an [llm] catalog entry")
def catalog(request: Request) -> dict:
    found, _ = load_profiles(request.app.state.settings.profiles_dir)
    eng: Engine = request.app.state.engine
    dl = request.app.state.downloads
    loaded = set(_loaded(eng))
    models = []
    for p in found.values():
        size = dl.local_bytes(p)
        models.append({"id": p.id, "name": p.name, "format": "hf", "model": p.model,
                       "size_gb": round(size / GB, 2) if size else None, "memory_gb": p.memory_gb,
                       "context": p.max_model_len, "downloaded": bool(dl.local_commit(p)), "loaded": p.id in loaded,
                       "relay_model": p.alias or p.served_name or None})
    return {"models": models}


@router.get("/v1/llm/engine", summary="What vLLM runs now: its state and the loaded profile")
def engine(request: Request) -> dict:
    eng: Engine = request.app.state.engine
    v = eng.view()
    return {"state": v.get("state") or eng.state, "stage": v.get("stage"), "loaded": _loaded(eng)}


@router.post("/v1/llm/load", status_code=202, summary="Start vLLM with a profile ({id}); answers at once")
async def load(request: Request, body: dict = Body(...)) -> dict:
    pid = body.get("id")
    found, _ = load_profiles(request.app.state.settings.profiles_dir)
    if pid not in found:
        raise EngineError(404, "not_found", f"no profile {pid!r}", {"profiles": list(found)})
    room = request.headers.get("x-gaifa-make-room", "").strip().lower() in ("1", "true", "yes")
    return await request.app.state.engine.load(pid, make_room=room, wait=False)


@router.post("/v1/llm/unload", summary="Stop vLLM ({id} must be the loaded profile, or leave it out)")
async def unload(request: Request, body: dict | None = Body(None)) -> dict:
    eng: Engine = request.app.state.engine
    pid = (body or {}).get("id")
    if pid and pid not in _loaded(eng):
        return {"loaded": _loaded(eng)}
    await eng.unload()
    return {"loaded": _loaded(eng)}
