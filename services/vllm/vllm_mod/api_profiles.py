"""Profile routes for the page (plan 18.6): the form's schema, save and delete. Deleting a profile
never deletes its downloaded files (they stay on GAIFA's Models page)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from pydantic import ValidationError

from .engine import EngineError
from .profiles import ID_RE, Profile, load_profiles, save_profile, schema

router = APIRouter()


@router.get("/v1/profiles/schema", summary="The profile form's JSON Schema")
def profile_schema() -> dict:
    return schema()


@router.put("/v1/profiles/{pid}", summary="Create or replace a profile")
def put_profile(request: Request, pid: str, body: dict[str, Any] = Body(...)) -> dict:
    if not ID_RE.match(pid):
        raise EngineError(422, "invalid_id", "lowercase letters, digits, '.', '_' and '-'; starts with a letter or digit")
    eng = request.app.state.engine
    try:
        p = Profile(**{**{k: v for k, v in body.items() if k != "id"}, "id": pid})
    except ValidationError as e:
        raise EngineError(422, "invalid_profile", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                                            for x in e.errors()), {"errors": e.errors(include_url=False)}) from e
    save_profile(request.app.state.settings.profiles_dir, p)
    note = "it applies at the next load" if eng.profile and eng.profile.id == pid and eng.state != "unloaded" else None
    return {"profile": p.model_dump(), "note": note}


@router.delete("/v1/profiles/{pid}", summary="Delete a profile (not its downloaded model)")
def delete_profile(request: Request, pid: str) -> dict:
    eng = request.app.state.engine
    found, _ = load_profiles(request.app.state.settings.profiles_dir)
    if pid not in found:
        raise EngineError(404, "not_found", f"no profile {pid!r}")
    if eng.profile and eng.profile.id == pid and eng.state not in ("unloaded", "failed"):
        raise EngineError(409, "in_use", f"{found[pid].name} is loaded; unload it first")
    (request.app.state.settings.profiles_dir / f"{pid}.toml").unlink()
    return {"deleted": pid}
