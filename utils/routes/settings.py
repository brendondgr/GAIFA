"""The `settings` area: `GET/PUT /api/settings` (brief §6.2), `config.toml` as the Settings page edits it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from utils import settings as settings_mod
from utils.api_models import SavedSettings, Settings, SettingsPatch

router = APIRouter(tags=["settings"])


@router.get("/api/settings", summary="AIHub's settings (config.toml)", response_model=Settings)
async def get_settings(request: Request) -> dict[str, Any]:
    return settings_mod.view(request.app.state.hub)


@router.put("/api/settings", summary="Save settings: the whole form or any part; only real overrides are written", response_model=SavedSettings)
async def save_settings(body: SettingsPatch, request: Request) -> dict[str, Any]:
    settings, restart = await settings_mod.save(request.app.state.hub, body.model_dump(exclude_none=True))
    return {"settings": settings, "restart_required": restart}
