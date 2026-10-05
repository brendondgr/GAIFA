"""The UI: `GET /` serves `web/Hub.dc.html`, adapted on the way out so a fresh
Claude Design export drops in unchanged (backend-plan 1.8):

- local React/ReactDOM and `/config.js` are added before `support.js`, so the
  runtime skips its unpkg download and knows which areas are live;
- Google Fonts `<link>`s become `/vendor/fonts.css` (in every `.dc.html`);
- a page load (`Sec-Fetch-Mode: navigate`) gets the page with an empty `<x-dc>`: the runtime
  renders from its own `fetch` of the same URL, which gets the full template. So the browser
  never parses the raw template, whose `{{ … }}` in `src`, `poster` and SVG `d` attributes
  made it request `/{{ … }}` URLs and log path errors (brief §11.2).

Mod pages (design brief §5): `/ui/services/<id>/<path>` serves `services/<id>/ui/`,
and `/Mod_<id>.dc.html` a mod's `ui/Page.dc.html`.

Everything else in `web/` is plain static files (the mount in `server.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

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
MOD_PREFIX = "Mod_"
UI_ID = re.compile(r"^_?[a-z][a-z0-9-]{0,40}$")


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


def blank_template(html: str) -> str:
    """The page with nothing inside `<x-dc>` (first `<x-dc>` to last `</x-dc>`, as support.js reads it)."""
    m = re.search(r"<x-dc(?:\s[^>]*)?>", html)
    end = html.rfind("</x-dc>")
    if not m or end < m.end():
        return html
    return html[: m.end()] + html[end:]


def _read(request: Request, name: str) -> str:
    path = request.app.state.hub.paths.web / name
    if not path.is_file():
        raise HubError(404, "not_found", f"web/{name} is missing")
    return path.read_text()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    html = page_html(_read(request, PAGE))
    if request.headers.get("sec-fetch-mode") == "navigate":
        html = blank_template(html)
    return HTMLResponse(html, headers={**NO_CACHE, "Vary": "Sec-Fetch-Mode"})


@router.get("/{name}.dc.html", response_class=HTMLResponse)
async def component(request: Request, name: str) -> HTMLResponse:
    if "/" in name or name.startswith("."):
        raise HubError(404, "not_found", "Not Found")
    if name.startswith(MOD_PREFIX):  # a mod's ui/Page.dc.html under a name <dc-import> can find
        path = _mod_ui_file(request, name[len(MOD_PREFIX):], "Page.dc.html")
        return HTMLResponse(local_fonts(path.read_text()), headers=NO_CACHE)
    return HTMLResponse(local_fonts(_read(request, f"{name}.dc.html")), headers=NO_CACHE)


@router.get("/ui/services/{service_id}/{path:path}")
async def mod_ui(request: Request, service_id: str, path: str) -> FileResponse:
    """A mod's `ui/` folder (page modules and their assets), never cached."""
    return FileResponse(_mod_ui_file(request, service_id, path), headers=NO_CACHE)


def _mod_ui_file(request: Request, service_id: str, path: str) -> Path:
    """`services/<id>/ui/<path>`, refusing anything outside that folder and hidden files.
    `_template` is allowed, so the mock Example mod can show the template's page."""
    hub = request.app.state.hub
    if not UI_ID.match(service_id):
        raise HubError(404, "not_found", f"no mod {service_id!r}")
    parts = Path(path).parts
    if not path or any(p.startswith(".") for p in parts) or Path(path).is_absolute():
        raise HubError(404, "not_found", "Not Found")
    dirs = hub.services.dirs if hub.services else [hub.paths.services]
    for base in dirs:
        ui = (base / service_id / "ui").resolve()
        target = (ui / path).resolve()
        if target.is_relative_to(ui) and target.is_file():
            return target
    raise HubError(404, "not_found", f"services/{service_id}/ui/{path} not found")
