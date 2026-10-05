"""The `outputs` area: `/api/outputs/...` (brief §6.2), backed by `utils/outputs/`.

File routes answer Range requests (Starlette's `FileResponse` returns 206), so audio and
video can seek. They only ever serve files the index lists for that output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from utils.api_models import Output, OutputPage
from utils.outputs import Outputs

router = APIRouter(tags=["outputs"])

MEDIA_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".bmp": "image/bmp", ".avif": "image/avif",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".obj": "model/obj", ".stl": "model/stl", ".ply": "application/octet-stream",
    ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".json": "application/json",
    ".srt": "text/plain; charset=utf-8", ".vtt": "text/vtt", ".csv": "text/csv; charset=utf-8", ".zip": "application/zip",
}


def _outs(request: Request) -> Outputs:
    return request.app.state.hub.outputs


def _send(p: Path, cache: str = "no-cache") -> FileResponse:
    return FileResponse(p, media_type=MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                        filename=p.name, content_disposition_type="inline", headers={"Cache-Control": cache})


@router.get("/api/outputs", summary="Outputs, newest first, with totals (cursor paging)", response_model=OutputPage, response_model_exclude_unset=True)
async def list_outputs(
    request: Request,
    service: str | None = Query(None, description="Comma-separated service ids"),
    kind: str | None = Query(None, description="Comma-separated: audio, image, video, model3d, text, archive, other"),
    q: str | None = Query(None, description="Words to find in the title, prompt or file name"),
    from_: float | None = Query(None, alias="from", description="Created at or after (unix seconds)"),
    to: float | None = Query(None, description="Created at or before (unix seconds)"),
    cursor: str | None = Query(None, description="`next_cursor` from the previous page"),
    limit: int = Query(60, ge=1, le=500),
) -> dict[str, Any]:
    return await _outs(request).list(service, kind, q, from_, to, cursor, limit)


@router.get("/api/outputs/{output_id}", summary="One output", response_model=Output, response_model_exclude_unset=True)
async def get_output(output_id: str, request: Request) -> dict[str, Any]:
    return await _outs(request).get(output_id)


@router.delete("/api/outputs/{output_id}", status_code=204, summary="Move an output (its files, sidecar and preview) to outputs/.trash")
async def delete_output(output_id: str, request: Request) -> Response:
    await _outs(request).delete(output_id)
    return Response(status_code=204)


@router.get("/api/outputs/{output_id}/file", summary="An output's main file (supports Range)")
@router.head("/api/outputs/{output_id}/file", include_in_schema=False)
async def output_file(output_id: str, request: Request) -> FileResponse:
    return _send(await _outs(request).file(output_id))


@router.get("/api/outputs/{output_id}/files/{path:path}", summary="A file inside a folder output (supports Range)")
@router.head("/api/outputs/{output_id}/files/{path:path}", include_in_schema=False)
async def output_folder_file(output_id: str, path: str, request: Request) -> FileResponse:
    return _send(await _outs(request).file(output_id, path))


@router.get("/api/outputs/{output_id}/preview", summary="An output's thumbnail or poster")
@router.head("/api/outputs/{output_id}/preview", include_in_schema=False)
async def output_preview(output_id: str, request: Request, v: str | None = None) -> FileResponse:
    # `?v=` changes whenever the output does, so a versioned URL can be cached.
    return _send(await _outs(request).preview(output_id), "private, max-age=604800" if v else "no-cache")
