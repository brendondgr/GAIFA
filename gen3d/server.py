"""3DGenerate HTTP API. See README.md for the endpoint reference and curl examples."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings

log = logging.getLogger("gen3d")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="3DGenerate", version=__version__, lifespan=lifespan)

# Loopback origins only, so arbitrary websites cannot drive the API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="ui")


@app.middleware("http")
async def _revalidate_ui(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-cache"  # always pick up UI updates (304 when unchanged)
    return response


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/v1")
def info():
    return {"service": "3dgenerate", "version": __version__, "ui": "/ui/", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "data": str(settings.data),
            "cubeart": str(settings.cubeart), "fake_worker": settings.fake_worker}
