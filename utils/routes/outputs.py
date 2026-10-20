"""The `outputs` area: `/api/outputs/...` (brief §6.2), backed by `utils/outputs/`.

File routes answer Range requests (Starlette's `FileResponse` returns 206), so audio and
video can seek. They only ever serve files the index lists for that output.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from pydantic import BaseModel, ConfigDict

from utils.api_models import Output, OutputPage, OutputSearch, OutputText
from utils.outputs import OutputError, Outputs, reading, text
from utils.outputs.entries import kind_of
from utils.outputs.upload import MAX_BYTES, UploadError, save_upload

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
    ".pdf": "application/pdf", ".epub": "application/epub+zip", ".odt": "application/vnd.oasis.opendocument.text",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _media_type(p: Path) -> str:
    """Any other text file (code, HTML, notebooks, …) is served as plain text, so an uploaded page
    never runs as a page on the hub's origin."""
    return MEDIA_TYPES.get(p.suffix.lower()) or ("text/plain; charset=utf-8" if kind_of(p.name) == "text" else "application/octet-stream")


def _outs(request: Request) -> Outputs:
    return request.app.state.hub.outputs


def _send(p: Path, cache: str = "no-cache") -> FileResponse:
    return FileResponse(p, media_type=_media_type(p), filename=p.name, content_disposition_type="inline",
                        headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


@router.get("/api/outputs", summary="Outputs, newest first, with totals (cursor paging)", response_model=OutputPage, response_model_exclude_unset=True)
async def list_outputs(
    request: Request,
    service: str | None = Query(None, description="Comma-separated service ids"),
    kind: str | None = Query(None, description="Comma-separated: audio, image, video, model3d, text, document, archive, other"),
    q: str | None = Query(None, description="Words to find in the title, prompt or file name"),
    from_: float | None = Query(None, alias="from", description="Created at or after (unix seconds)"),
    to: float | None = Query(None, description="Created at or before (unix seconds)"),
    cursor: str | None = Query(None, description="`next_cursor` from the previous page"),
    limit: int = Query(60, ge=1, le=500),
) -> dict[str, Any]:
    return await _outs(request).list(service, kind, q, from_, to, cursor, limit)


@router.post("/api/outputs/upload", status_code=201, summary="Upload a file (the raw body) as an output in outputs/uploads/",
             response_model=Output, response_model_exclude_unset=True)
async def upload_output(request: Request, name: str = Query(..., description="The file's name (its extension sets the kind)")) -> dict[str, Any]:
    """An image, video, audio, text or document file of at most 64 MB, sent as the body. It becomes
    an ordinary output (`output:<id>` works wherever an output does). Errors: `upload_type` (415),
    `upload_encoding` (415, text that isn't UTF-8 or UTF-16 with a BOM), `upload_too_large` (413),
    `upload_empty` (400)."""
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise OutputError(413, "upload_too_large", f"uploads are at most {MAX_BYTES // 2**20} MB")
    outs = _outs(request)
    try:
        rel = await asyncio.to_thread(save_upload, outs.dir, name, await request.body())
    except UploadError as e:
        raise OutputError(e.status, e.code, e.detail) from None
    return await outs.ingest(rel)


@router.get("/api/outputs/{output_id}", summary="One output", response_model=Output, response_model_exclude_unset=True)
async def get_output(output_id: str, request: Request) -> dict[str, Any]:
    return await _outs(request).get(output_id)


class _F(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedbackIn(_F):
    value: Literal["up", "down"]
    note: str = ""
    origin: dict[str, Any] = {}


class Feedback(_F):
    output_id: str
    value: Literal["up", "down"]
    note: str
    ts: float


@router.post("/api/outputs/{output_id}/feedback", summary="Thumbs up or down on an output (plan 21.4); the newest counts",
             response_model=Feedback)
async def output_feedback(output_id: str, body: FeedbackIn, request: Request) -> dict[str, Any]:
    import json
    import time

    oid = output_id.removeprefix("output:")
    await _outs(request).get(oid)                      # 404 output_not_found for an unknown id
    now = time.time()
    await request.app.state.hub.db.execute("INSERT INTO output_feedback (output_id, value, note, origin, ts) VALUES (?, ?, ?, ?, ?)",
                                           (oid, body.value, body.note[:500], json.dumps(body.origin), now))
    return {"output_id": oid, "value": body.value, "note": body.note[:500], "ts": now}


@router.delete("/api/outputs/{output_id}", status_code=204, summary="Move an output (its files, sidecar and preview) to outputs/.trash")
async def delete_output(output_id: str, request: Request) -> Response:
    await _outs(request).delete(output_id)
    return Response(status_code=204)


@router.get("/api/outputs/{output_id}/text", summary="An output's text, a window at a time (text and documents)",
            response_model=OutputText, response_model_exclude_unset=True)
async def output_text(
    output_id: str, request: Request,
    offset: int = Query(0, ge=0, description="Character offset to start at"),
    limit: int = Query(reading.LIMIT, ge=1, le=reading.MAX_LIMIT, description="Characters to return"),
    page: int | None = Query(None, ge=1, description="Start at this page (PDFs)"),
    pages: str | None = Query(None, description='A page or a range, like "3" or "3-5" (PDFs)'),
) -> dict[str, Any]:
    """Errors: `not_text` (409) for kinds without text, `no_page` (404) for a page the document
    doesn't have."""
    ex = await _outs(request).text(output_id.removeprefix("output:"))
    spec = pages or (str(page) if page else None)
    return await asyncio.to_thread(reading.window, ex, offset, limit, spec)


@router.get("/api/outputs/{output_id}/search", summary="Find words, a \"phrase\" or a /regex/ in an output's text",
            response_model=OutputSearch, response_model_exclude_unset=True)
async def output_search(output_id: str, request: Request, q: str = Query(..., description='Words (all in one line or paragraph), a "quoted phrase", or /regex/ (/regex/i ignores case)'),
                        limit: int = Query(reading.SEARCH_LIMIT, ge=1, le=200)) -> dict[str, Any]:
    """Errors: `not_text` (409), `search_timeout` (422, a regex that ran over 1 s), `invalid_request` (422)."""
    ex = await _outs(request).text(output_id.removeprefix("output:"))
    return await asyncio.to_thread(reading.search, ex, q, limit)


@router.get("/api/outputs/{output_id}/page/{n}.png", summary="Page n of a PDF output as a PNG",
            response_class=FileResponse, responses={200: {"content": {"image/png": {}}, "description": "The page, rendered"}})
async def output_page(output_id: str, n: int, request: Request, width: int = Query(reading.PAGE_WIDTH, ge=64, le=2400)) -> FileResponse:
    """Errors: `not_text` (409) for outputs that aren't PDFs, `no_page` (404)."""
    outs = _outs(request)
    oid = output_id.removeprefix("output:")
    row = await outs.row(oid)
    if row["kind"] != "document" or not (row["main"] or "").lower().endswith(".pdf"):
        raise OutputError(409, "not_text", f'Output "{oid}" is not a PDF; only PDFs have page images')
    src = await outs.file(oid)
    out = outs.dir / text.PAGES_DIR / oid / f"p{n}-w{width}.png"
    return _send(await asyncio.to_thread(reading.page_png, src, n, width, out))


@router.get("/api/outputs/{output_id}/file", summary="An output's main file (supports Range)",
            response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}, "description": "The file (its own content type); Range requests answer 206"}})
@router.head("/api/outputs/{output_id}/file", include_in_schema=False)
async def output_file(output_id: str, request: Request) -> FileResponse:
    return _send(await _outs(request).file(output_id))


@router.get("/api/outputs/{output_id}/files/{path:path}", summary="A file inside a folder output (supports Range)",
            response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {}}, "description": "The file (its own content type); Range requests answer 206"}})
@router.head("/api/outputs/{output_id}/files/{path:path}", include_in_schema=False)
async def output_folder_file(output_id: str, path: str, request: Request) -> FileResponse:
    return _send(await _outs(request).file(output_id, path))


@router.get("/api/outputs/{output_id}/preview", summary="An output's thumbnail or poster",
            response_class=FileResponse, responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}, "description": "The preview image"}})
@router.head("/api/outputs/{output_id}/preview", include_in_schema=False)
async def output_preview(output_id: str, request: Request, v: str | None = None) -> FileResponse:
    # `?v=` changes whenever the output does, so a versioned URL can be cached.
    return _send(await _outs(request).preview(output_id), "private, max-age=604800" if v else "no-cache")
