"""The `widgets` area: mods' dashboard widgets (brief §11.7), proxied and cached for 30 s."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from utils.api_models import WidgetData, WidgetInfo

router = APIRouter(tags=["widgets"])


@router.get("/api/widgets", summary="Every [[ui.widgets]] entry of the running mods", response_model=list[WidgetInfo])
async def list_widgets(request: Request) -> list[dict[str, Any]]:
    return request.app.state.hub.widgets.list()


@router.get("/api/widgets/{service_id}/{widget_id}", summary="A widget's data from its mod (cached 30 s, validated)", response_model=WidgetData, response_model_exclude_none=True)
async def get_widget(service_id: str, widget_id: str, request: Request,
                     range: str | None = Query(None, description="One of the widget's ranges (default: its first)")) -> dict[str, Any]:
    return await request.app.state.hub.widgets.get(service_id, widget_id, range)
