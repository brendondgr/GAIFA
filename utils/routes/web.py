"""The UI: `GET /` serves `web/Hub.dc.html`, adapted on the way out so a fresh
Claude Design export drops in unchanged (backend-plan 1.8):

- local React/ReactDOM and `/config.js` are added before `support.js`, so the
  runtime skips its unpkg download and knows which areas are live;
- Google Fonts `<link>`s become `/vendor/fonts.css` (in every `.dc.html`).

Everything else in `web/` is plain static files (the mount in `server.py`).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from utils.server import HubError

router = APIRouter(include_in_schema=False)

PAGE = "Hub.dc.html"
SUPPORT_TAG = re.compile(r'<script\b[^>]*\bsrc="(?:\./|/)?support\.js"[^>]*>\s*</script>')
FONT_PRECONNECT = re.compile(r'<link\b[^>]*\brel="preconnect"[^>]*\bhref="https://fonts\.(?:googleapis|gstatic)\.com"[^>]*>\s*')
FONT_SHEET = re.compile(r'<link\b[^>]*\bhref="https://fonts\.googleapis\.com/css2?\?[^"]*"[^>]*>')
HEAD_SCRIPTS = (
    '<script src="/vendor/react.production.min.js"></script>\n'
    '<script src="/vendor/react-dom.production.min.js"></script>\n'
    '<script src="/config.js"></script>\n'
)
NO_CACHE = {"Cache-Control": "no-cache"}


def local_fonts(html: str) -> str:
    html = FONT_PRECONNECT.sub("", html)
    return FONT_SHEET.sub('<link rel="stylesheet" href="/vendor/fonts.css">', html)


def page_html(html: str) -> str:
    """The shell page: local fonts, plus vendor scripts and /config.js before support.js."""
    html = local_fonts(html)
    m = SUPPORT_TAG.search(html)
    if not m:
        raise HubError(500, "hub_error", f"web/{PAGE} has no support.js <script>; is it a Claude Design export?")
    return html[: m.start()] + HEAD_SCRIPTS + html[m.start() :]


def _read(request: Request, name: str) -> str:
    path = request.app.state.hub.paths.web / name
    if not path.is_file():
        raise HubError(404, "not_found", f"web/{name} is missing")
    return path.read_text()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(page_html(_read(request, PAGE)), headers=NO_CACHE)


@router.get("/{name}.dc.html", response_class=HTMLResponse)
async def component(request: Request, name: str) -> HTMLResponse:
    if "/" in name or name.startswith("."):
        raise HubError(404, "not_found", "Not Found")
    return HTMLResponse(local_fonts(_read(request, f"{name}.dc.html")), headers=NO_CACHE)
