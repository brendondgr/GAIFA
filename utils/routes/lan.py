"""The `lan` area (plan lan-access 1.3, 2.2): signing in from another device, and the network settings.

    GET    /signin                    the sign-in page (no app code before signing in)
    POST   /api/lan/signin            {password} → the device's cookie; 401 wrong_password, 429 locked
    POST   /api/lan/signout           this device
    GET    /api/lan/status            this machine: on, URLs, devices; a device on the network: its own session
    PUT    /api/lan/settings          this machine only: {enabled?, allow?, names?, https?, session_days?}
    PUT    /api/lan/password          this machine only: {password}; signs every device out
    DELETE /api/lan/sessions/{id}     this machine only: sign a device out ("all": every one)

The guard (`utils/lan/guard.py`) refuses the this-machine-only writes from the network (`limits.py`).
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from utils.lan import addresses
from utils.api_models import LanOk, LanStatus
from utils.lan.auth import COOKIE, MIN_LENGTH

router = APIRouter(tags=["lan"])


class SignIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class Password(BaseModel):
    password: str = Field(min_length=MIN_LENGTH, max_length=1024)


class LanSettings(BaseModel):
    enabled: bool | None = None
    allow: list[str] | None = Field(None, max_length=16)
    names: list[str] | None = Field(None, max_length=16)
    https: str | None = Field(None, pattern=r"^(off|also|only)$")
    session_days: int | None = Field(None, ge=1, le=365)


def _lan(request: Request):
    lan = getattr(request.app.state.hub, "lan", None)
    if lan is None:
        raise HTTPException(503, {"detail": "the network settings aren't loaded", "code": "lan_off"})
    return lan


def _remote(request: Request) -> dict[str, Any] | None:
    return (request.scope.get("state") or {}).get("lan")


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/api/lan/signin", summary="Sign in from a device on the network: its cookie for `session_days`", response_model=LanOk,
             responses={401: {"description": "wrong_password"}, 429: {"description": "locked: too many wrong passwords from this address"}})
async def sign_in(body: SignIn, request: Request) -> Response:
    lan = _lan(request)
    token, why = lan.auth.sign_in(body.password, _client(request), request.headers.get("user-agent", ""))
    if token is None:
        wait = round(lan.auth.locked_for(_client(request)))
        if why == "locked":
            return JSONResponse({"detail": f"Too many wrong passwords: try again in {wait} s.", "code": "locked", "data": {"retry_after": wait}},
                                status_code=429, headers={"retry-after": str(wait)})
        return JSONResponse({"detail": "That isn't the password.", "code": "wrong_password"}, status_code=401)
    hub = request.app.state.hub
    if hub.activity:
        s = lan.auth.session(token)
        await hub.activity.add(f"{s['label']} at {s['addr']} signed in to GAIFA from the network")
    r = JSONResponse({"ok": True})
    secure = request.url.scheme == "https"
    r.set_cookie(COOKIE, token, max_age=int(lan.cfg.session_days * 86400), httponly=True, samesite="strict", secure=secure, path="/")
    return r


@router.post("/api/lan/signout", summary="Sign this device out", response_model=LanOk)
async def sign_out(request: Request) -> Response:
    from utils.lan.guard import cookie

    lan = _lan(request)
    token = cookie({"cookie": request.headers.get("cookie", "")})
    if token:
        lan.auth.sign_out_token(token)
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r


@router.get("/api/lan/status", summary="Whether GAIFA is open to the network, its addresses and the devices signed in", response_model=LanStatus,
            response_model_exclude_none=True)
async def status(request: Request) -> dict[str, Any]:
    lan = _lan(request)
    me = _remote(request)
    if me is not None:                                          # a device on the network sees only itself
        return {"remote": True, "me": me, "on": lan.on}
    return {"remote": False, **lan.status()}


@router.put("/api/lan/settings", summary="Open GAIFA to the network or close it, and its other settings ([hub.lan]); "
            "turning it on or off takes a restart of GAIFA (restart_required)", response_model=LanStatus, response_model_exclude_none=True)
async def save_settings(body: LanSettings, request: Request) -> dict[str, Any]:
    from utils import config as config_mod

    lan, hub = _lan(request), request.app.state.hub
    changes = body.model_dump(exclude_none=True)
    try:
        if "allow" in changes:
            changes["allow"] = config_mod.Replace([addresses.check_cidr(c) for c in changes["allow"]] or None)
        if "names" in changes:
            changes["names"] = config_mod.Replace([n.strip().lower() for n in changes["names"] if n.strip()] or None)
    except ValueError as e:
        raise HTTPException(422, {"detail": str(e), "code": "invalid_settings"}) from None
    if changes.get("enabled") and not lan.auth.has_password():
        raise HTTPException(409, {"detail": "Set a password first: every device on the network will need it.", "code": "no_password"})
    was = lan.cfg.enabled
    try:
        cfg = config_mod.save(hub.paths.config_file, {"hub": {"lan": changes}}) if changes else hub.config
    except config_mod.ConfigError as e:
        raise HTTPException(422, {"detail": str(e), "code": "invalid_settings"}) from None
    hub.config = cfg
    lan.reconfigure(cfg.hub.lan)
    restart = cfg.hub.lan.enabled != lan.listening and (cfg.hub.lan.enabled or was)
    if hub.activity and "enabled" in changes:
        await hub.activity.add(("GAIFA opened to the network" if cfg.hub.lan.enabled else "GAIFA closed to the network")
                               + (" (restart GAIFA to apply)" if restart else ""))
    return {"remote": False, **lan.status(), "restart_required": bool(restart)}


@router.put("/api/lan/password", summary="Set the password devices on the network sign in with; every device is signed out", response_model=LanOk)
async def set_password(body: Password, request: Request) -> dict[str, Any]:
    lan = _lan(request)
    lan.auth.set_password(body.password)
    return {"ok": True, "has_password": True}


@router.delete("/api/lan/sessions/{sid}", summary="Sign a device out (`all`: every one)", response_model=LanOk)
async def drop_session(sid: str, request: Request) -> dict[str, Any]:
    lan = _lan(request)
    if sid == "all":
        lan.auth.sign_out_all()
        return {"ok": True}
    if not lan.auth.sign_out(sid):
        raise HTTPException(404, {"detail": f"no device {sid!r}", "code": "not_found"})
    return {"ok": True}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Sign in · GAIFA</title><style>
:root{color-scheme:light dark;--bg:#f5f6f8;--card:#fff;--tx:#151a22;--mut:#5b6474;--bd:#d6dbe3;--acc:#3563e9;--rd:#c4352b}
@media (prefers-color-scheme:dark){:root{--bg:#0b0e14;--card:#11151d;--tx:#e6eaf2;--mut:#8a94a6;--bd:#2a3547;--acc:#5b8cff;--rd:#f0786e}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--tx);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
form{width:100%;max-width:360px;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:24px;display:grid;gap:14px}
h1{margin:0;font-size:20px}p{margin:0;color:var(--mut);font-size:13.5px}label{display:grid;gap:6px;font-weight:600;font-size:13.5px}
input{font:inherit;padding:10px 12px;border-radius:8px;border:1px solid var(--bd);background:transparent;color:var(--tx)}
input:focus-visible,button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
button{font:inherit;font-weight:600;padding:10px 12px;border:0;border-radius:8px;background:var(--acc);color:#fff;cursor:pointer}
button:disabled{opacity:.6;cursor:default}#err{color:var(--rd);min-height:1.2em}</style></head><body>
<form id="f"><h1>GAIFA</h1><p>This is __HOST__. Sign in with the password set on the GAIFA machine (Settings → General → Network).</p>
<label>Password<input id="pw" type="password" autocomplete="current-password" required autofocus></label>
<div id="err" role="alert"></div><button id="go">Sign in</button></form>
<script>
const next = new URLSearchParams(location.search).get('next') || '/';
const safe = next.startsWith('/') && !next.startsWith('//') ? next : '/';
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault(); const go = document.getElementById('go'), err = document.getElementById('err'); go.disabled = true; err.textContent = '';
  try {
    const r = await fetch('/api/lan/signin', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password: document.getElementById('pw').value }) });
    if (r.ok) { location.replace(safe); return; }
    const b = await r.json().catch(() => ({})); err.textContent = b.detail || 'Signing in failed.';
  } catch { err.textContent = 'GAIFA didn’t answer.'; }
  go.disabled = false;
});
</script></body></html>"""


@router.get("/signin", include_in_schema=False)
async def signin_page(request: Request) -> HTMLResponse:
    import socket

    return HTMLResponse(PAGE.replace("__HOST__", escape(socket.gethostname())), headers={
        "cache-control": "no-store", "x-frame-options": "DENY",
        "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'"})
