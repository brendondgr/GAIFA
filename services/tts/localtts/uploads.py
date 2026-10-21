"""Upload limits: bodies capped before they are read, files streamed to disk in pieces."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse


class LimitUploads:
    """413 for an upload body over its cap: up front from Content-Length, or while it streams in."""

    def __init__(self, app, caps: dict[str, int]):
        self.app, self.caps = app, caps   # POST path -> most bytes in its body

    async def __call__(self, scope, receive, send):
        cap = self.caps.get(scope.get("path", "")) if scope["type"] == "http" and scope["method"] == "POST" else None
        if cap is None:
            return await self.app(scope, receive, send)
        detail = f"upload is over {cap >> 20} MB"
        length = dict(scope["headers"]).get(b"content-length", b"")
        if length.isdigit() and int(length) > cap:
            return await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > cap:
                raise HTTPException(413, detail)
            return message

        await self.app(scope, limited, send)


def suffix(filename: str | None) -> str:
    """The upload's extension when it is a plain one (a hint for ffmpeg's probe), else .bin."""
    ext = Path(filename or "").suffix
    return ext if ext[1:].isalnum() and len(ext) <= 9 else ".bin"


async def copy_to(upload: UploadFile, dest: Path) -> int:
    """Stream an upload to `dest` in pieces (never whole in memory); -> bytes written."""
    size = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(1 << 20):
            fh.write(chunk)
            size += len(chunk)
    return size
