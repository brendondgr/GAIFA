"""`POST /api/web/read`: read a web page for the user (plan 30.8), from Chat's composer (a pasted URL, "Add a web
page") and the web mod's Read a page tab.

The user asked for this page, so there is no approval card (like an upload); the web mod's fetch rules all apply
(public http(s) only, robots.txt, 10 MB, 20 s; `services/web/safety.py`). The page is saved as the web mod's
output (markdown, or a PDF document), then its whole text is screened (`screen_store.screen_whole`: patterns, then
the `[agent.screen]` model, in pieces) and the report kept with the output, so the chat agent's later reads of it
(`hub_read_document`, an attachment sent whole) reuse it instead of screening again. The chat sends the output as
an attachment; the agent reads it inside `<untrusted>`, screened.

`GET /api/web/reading`: what Settings → Agent shows about reading pages: the screening model in use (and the judge's),
the models each backend offers (`choices`: the relay's, and the decide mod's when it's up; never started for this),
and what `[agent.web] relevance` uses now.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from utils.api_models import Output
from utils.server import HubError
from utils.tools import results, screen, screen_store, webread

router = APIRouter(tags=["web"])

WEB = "web"                    # the web mod (services/web)
TIMEOUT_S = 40.0               # the web mod gives up at 20 s, robots.txt included


class ReadIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048, description="An http:// or https:// URL on the public internet")
    text: bool = Field(False, description="Also return the page's markdown, whole and as screened")


class Removed(BaseModel):
    passage: int
    why: str
    by: str = Field(description="pattern | model | fail-closed")
    excerpt: str = Field(description="The passage's first 80 characters")
    line: int


class Screening(BaseModel):
    removed: int
    checked: str = Field(description="patterns+model, or patterns when the model didn't answer")
    ms: float
    model: str | None = None
    covered: int = Field(description="Characters screened: all of the page, or its first 400,000")
    findings: list[Removed]


class WebPage(BaseModel):
    output: Output
    url: str
    final_url: str
    title: str
    kind: Literal["text", "document"]
    chars: int = Field(description="Length of the page's text")
    screening: Screening | None = Field(description="null when [agent.screen] pages is off")
    markdown: str | None = Field(None, description="With text=true: the page's text")
    screened: str | None = Field(None, description="With text=true: the text as the chat model reads it")


async def _web_mod(hub: Any) -> Any:
    mgr = hub.services
    svc = mgr.get(WEB)                                  # 404 service_not_found without the mod
    if not svc.up:
        svc = await mgr.start(WEB, wait=True)
        if not svc.up:
            raise HubError(503, "service_not_running", f"{svc.mod.name} didn't start ({svc.state}); see its Logs tab")
    return svc


async def _fetch(svc: Any, url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(TIMEOUT_S, connect=5)) as c:
        svc.in_flight += 1
        try:
            r = await c.post(svc.url + "/v1/fetch", json={"url": url, "max_chars": 0})   # the text is read from the output
        except httpx.HTTPError as e:
            raise HubError(502, "upstream_error", f"{svc.mod.name} didn't answer ({type(e).__name__})") from None
        finally:
            svc.in_flight -= 1
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:   # the mod's own reason: local address, robots.txt, too large, not a page…
        detail = body.get("detail") if isinstance(body, dict) else None
        fix = body.get("fix") if isinstance(body, dict) else None
        raise HubError(r.status_code if r.status_code < 500 else 502, str(body.get("code") or "upstream_error"),
                       str(detail if isinstance(detail, str) else f"{svc.mod.name}: HTTP {r.status_code}")[:600],
                       {"fix": fix} if isinstance(fix, str) else None)
    if not isinstance(body, dict) or not isinstance(body.get("path"), str):
        raise HubError(502, "upstream_error", f"{svc.mod.name} answered without the saved page")
    return body


@router.post("/api/web/read", summary="Read a web page: saved as an output, screened whole", response_model=WebPage,
             response_model_exclude_none=True)
async def read_page(body: ReadIn, request: Request) -> dict[str, Any]:
    """The web mod fetches the page and saves it as an output; the hub screens all of its text and keeps the report.
    Errors are the web mod's (`blocked_address` 403, `robots` 403, `too_large` 413, `unsupported_type` 415,
    `timeout` 504, …) with its `fix` in `data`, `service_not_found` (404) without the web mod."""
    hub = request.app.state.hub
    svc = await _web_mod(hub)
    got = await _fetch(svc, body.url.strip())
    found = await results.outputs_for(hub, results.candidates(hub, WEB, got))
    if not found:
        raise HubError(502, "upstream_error", f"{svc.mod.name} saved the page where the outputs index can't see it")
    o = await hub.outputs.get(found[0]["output_id"])
    ex = await hub.outputs.text(o["id"])
    s, rep = await screen_store.screen_whole(hub.outputs.dir, hub.config, o["id"], ex.text, "page")
    out: dict[str, Any] = {"output": o, "url": body.url.strip(), "final_url": str(got.get("final_url") or body.url),
                           "title": o["title"], "kind": "document" if got.get("kind") == "document" else "text",
                           "chars": len(ex.text), "screening": None}
    if s is not None:
        out["screening"] = {**screen.user_report(s, screen.screen_config(hub.config)),
                            "covered": (rep or {}).get("covered", len(ex.text))}
    if body.text:
        out["markdown"] = ex.text
        out["screened"] = s.text + ex.text[out["screening"]["covered"]:] if s is not None else ex.text
    return out


class ScreenNow(BaseModel):
    backend: Literal["relay", "decide"]
    model: str
    confirm: str | None = Field(None, description="decide: the chat model that re-reads what it flags")
    same_as_judge: bool = Field(description="[agent.screen] names no model of its own: the judge's")


class Reading(BaseModel):
    screen: ScreenNow
    judge: dict[str, str] = Field(description="{backend, model} of the Auto judge")
    choices: dict[str, list[str]] = Field(description="Models each backend offers now: relay (chat models), decide "
                                          "(decision models; empty while the decide mod is down)")
    relevance: str = Field(description="What [agent.web] relevance uses now: decide, lexical or off")
    decide_up: bool


_choices: dict[str, Any] = {}
CHOICES_TTL_S = 30.0


async def _models(url: str, backend: str) -> list[str]:
    key = (url, backend)
    hit = _choices.get(key)
    if hit and time.monotonic() - hit[0] < CHOICES_TTL_S:
        return hit[1]
    out: list[str] = []
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(3)) as c:
            r = await c.get(f"{url.rstrip('/')}/v1/models")
            r.raise_for_status()
            d = r.json()
        if backend == "decide":
            out = [str(m.get("id")) for m in d.get("models", []) if m.get("usable") and m.get("id")]
        else:
            out = sorted({str(m.get("id")) for m in d.get("data", []) if m.get("id")} - {"auto", "agent"})
            out = [i for i in out if "/" not in i]           # local and named models, as the judge's picker
    except (httpx.HTTPError, ValueError, AttributeError):
        out = []
    _choices[key] = (time.monotonic(), out)
    return out


@router.get("/api/web/reading", summary="How web pages are read: the screening model, choices, relevance", response_model=Reading)
async def reading(request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    cfg = hub.config
    sc = screen.screen_config(cfg)
    jc = cfg.agent.judge
    try:
        decide_up = bool(hub.services.get("decide").up)
    except Exception:  # noqa: BLE001: no decide mod
        decide_up = False
    from utils.tools.judge import config_from

    relay_url = (sc.url if sc.backend == "relay" else sc.confirm.url if sc.confirm else
                 config_from(jc).url if jc.backend == "relay" else screen.RELAY_DEFAULTS["url"])
    decide_url = (cfg.agent.screen.url if cfg.agent.screen.backend == "decide" and cfg.agent.screen.url
                  else jc.url if jc.backend == "decide" else screen.DECIDE_DEFAULTS["url"])
    relay, decide = await _models(relay_url, "relay"), (await _models(decide_url, "decide") if decide_up else [])
    return {"screen": {"backend": sc.backend, "model": sc.model, "confirm": sc.confirm.model if sc.confirm else None,
                       "same_as_judge": not cfg.agent.screen.backend and not cfg.agent.screen.model},
            "judge": {"backend": jc.backend, "model": jc.model},
            "choices": {"relay": relay, "decide": decide},
            "relevance": webread.backend(hub), "decide_up": decide_up}
