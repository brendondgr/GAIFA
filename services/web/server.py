"""Web: search the web through SearXNG and read pages as outputs (plan Phase 26).

AIHub runs this as `.venv/bin/python server.py` with AIHUB_PORT and AIHUB_OUTPUTS set
(architecture §4.4). SEARXNG_URL (default http://127.0.0.1:8080) is a SearXNG with the JSON
format enabled; it runs outside AIHub (setup/web.md). Fetch rules are in safety.py.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import fakeweb
import pages
import safety

DEFAULT_SEARXNG = "http://127.0.0.1:8080"
PROBE_TTL_S = 15.0
ENDPOINT_TTL_S = 60.0


def error(status: int, code: str, detail: str, fix: str) -> JSONResponse:
    """The hub's envelope ({detail, code}) plus `fix`, which reaches the model with the error."""
    return JSONResponse({"detail": detail, "code": code, "fix": fix}, status_code=status)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=400, description="What to search for, as you would type it into a search engine")
    categories: list[str] | None = Field(None, description="SearXNG categories: general (default), news, it, science, files, videos, …")
    time_range: Literal["day", "week", "month", "year"] | None = Field(None, description="Only results from the last day, week, month or year")
    language: str | None = Field(None, max_length=16, description="A language code such as en or de-DE; default: SearXNG's")
    limit: int = Field(8, ge=1, le=20, description="How many results to return (1–20)")


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    engine: str
    published: str | None = None


class SearchOut(BaseModel):
    query: str
    results: list[SearchResult]
    answers: list[str] = []
    suggestions: list[str] = []
    unresponsive: list[str] = Field([], description="Search engines that failed this time (rate limits, CAPTCHAs)")


class FetchIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048, description="An http:// or https:// URL on the public internet")
    max_chars: int = Field(6000, ge=0, le=50000, description="How much of the page's text to return (the whole page is saved)")


class FetchOut(BaseModel):
    path: str = Field(description="The saved output: the page as markdown, or the PDF")
    url: str
    final_url: str = Field(description="Where the URL led after redirects")
    title: str
    kind: Literal["text", "document"]
    content_type: str
    chars: int = Field(description="Length of the whole page's markdown (0 for a PDF)")
    content: str = Field(description="The first max_chars of the markdown")
    truncated: bool
    published: str | None = None
    note: str | None = None


def create_app(searxng_url: str | None = None, outputs: Path | None = None, guard: safety.Guard | None = None,
               hub_url: str | None = None) -> FastAPI:
    """`hub_url`: where to ask the searxng mod for its URL (default AIHUB_URL; tests pass their own)."""
    own = (searxng_url or os.environ.get("SEARXNG_URL") or DEFAULT_SEARXNG).rstrip("/")
    hub = (hub_url if hub_url is not None else ("" if searxng_url else os.environ.get("AIHUB_URL", ""))).rstrip("/")
    found = {"url": own, "source": "SEARXNG_URL", "at": 0.0}
    out_dir = outputs or Path(os.environ.get("AIHUB_OUTPUTS", "outputs"))
    state = {"searches": 0, "fetches": 0, "refused": 0, "busy": 0, "last_used": time.time(),
             "probe": (0.0, False, "not checked yet")}
    robots = safety.Robots()
    fake: list[fakeweb.FakeWeb] = []          # loaded on the first dry run

    def fake_web() -> fakeweb.FakeWeb:
        if not fake:
            fake.append(fakeweb.FakeWeb.load())
        return fake[0]
    clients: dict[str, httpx.AsyncClient] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        clients["web"] = safety.make_client(guard)
        clients["searxng"] = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0), trust_env=False,
                                               headers={"User-Agent": safety.USER_AGENT})
        yield
        await asyncio.gather(*(c.aclose() for c in clients.values()))

    app = FastAPI(title="Web", version="0.1.0", lifespan=lifespan,
                  description="Search the web through SearXNG and save pages as outputs.")

    def used() -> None:
        state["last_used"] = time.time()

    async def searxng() -> str:
        """The URL the searxng mod publishes (plan 26.3), asked at most once a minute, else SEARXNG_URL."""
        if not hub or time.monotonic() - found["at"] < ENDPOINT_TTL_S:
            return found["url"]
        found["at"] = time.monotonic()
        try:
            r = await clients["searxng"].get(f"{hub}/api/s/searxng/v1/endpoint", timeout=2.0)
            url = r.json().get("url") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError, AttributeError):
            url = None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            if url.rstrip("/") != found["url"]:
                state["probe"] = (0.0, False, "not checked yet")
            found.update(url=url.rstrip("/"), source="the searxng mod")
        else:
            if found["source"] != "SEARXNG_URL":
                state["probe"] = (0.0, False, "not checked yet")
            found.update(url=own, source="SEARXNG_URL")
        return found["url"]

    async def probe() -> tuple[bool, str]:
        base = await searxng()
        at, up, why = state["probe"]
        if at and time.monotonic() - at < PROBE_TTL_S:
            return up, why
        try:
            r = await clients["searxng"].get(f"{base}/healthz", timeout=2.0)
            up, why = r.status_code < 400, f"{base} answers" if r.status_code < 400 else f"{base}/healthz: HTTP {r.status_code}"
        except httpx.HTTPError as e:
            up, why = False, f"{base} doesn't answer ({type(e).__name__})"
        state["probe"] = (time.monotonic(), up, why)
        return up, why

    @app.get("/health")
    def health() -> dict:
        """Up when this server is; whether SearXNG answers is in /v1/status."""
        return {"status": "ok"}

    @app.get("/v1/status")
    async def status() -> dict:
        up, why = await probe()
        return {
            "loaded": None,
            "busy": state["busy"] > 0,
            "idle_s": round(time.time() - state["last_used"], 1),
            "stats": [
                {"label": "SearXNG", "value": "up" if up else "down", "hint": why},
                {"label": "Searches", "value": state["searches"]},
                {"label": "Pages fetched", "value": state["fetches"]},
                {"label": "Refused", "value": state["refused"]},
            ],
            "jobs": [],
            "searxng": {"url": found["url"], "from": found["source"], "up": up, "detail": why},
        }

    @app.post("/v1/search", summary="Search the web", response_model=SearchOut,
              responses={503: {"description": "SearXNG doesn't answer"}, 502: {"description": "SearXNG refused or failed"}})
    async def search(body: SearchIn, x_aihub_origin: str | None = Header(None, include_in_schema=False)):
        """Results come from SearXNG: title, URL, a snippet, the engine that found it, and the date when known."""
        used()
        if fakeweb.is_dry_run(x_aihub_origin):   # the agent eval: the fake web, never the internet
            return SearchOut(query=body.query, results=[SearchResult(**r) for r in fake_web().search(body.query, body.limit)])
        params = {"q": body.query, "format": "json", "pageno": 1}
        if body.categories:
            params["categories"] = ",".join(body.categories)
        if body.time_range:
            params["time_range"] = body.time_range
        if body.language:
            params["language"] = body.language
        state["busy"] += 1
        try:
            base = await searxng()
            r = await clients["searxng"].get(f"{base}/search", params=params)
        except httpx.HTTPError as e:
            state["probe"] = (time.monotonic(), False, f"{base} doesn't answer ({type(e).__name__})")
            return error(503, "searxng_down", f"SearXNG at {base} doesn't answer ({type(e).__name__})",
                         "the web search service is down; tell the user (setup: services/web/setup/web.md) and don't retry now")
        finally:
            state["busy"] -= 1
        if r.status_code == 403:
            return error(502, "searxng_no_json", f"SearXNG at {base} refused format=json (HTTP 403)",
                         "SearXNG needs `json` under search.formats in its settings.yml (services/web/setup/web.md)")
        if r.status_code == 429:
            return error(502, "searxng_limited", "SearXNG's rate limiter refused the search (HTTP 429)",
                         "wait a minute, or turn off server.limiter in SearXNG's settings.yml")
        try:
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError(f"expected a JSON object, got {type(data).__name__}")
        except (httpx.HTTPError, ValueError) as e:
            return error(502, "searxng_failed", f"SearXNG failed: {e}", "try again with a different query")
        state["searches"] += 1
        seen: set[str] = set()
        results = []
        for it in data.get("results") or []:
            url = it.get("url")
            if not isinstance(url, str) or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(title=str(it.get("title") or url), url=url,
                                        snippet=str(it.get("content") or "")[:500],
                                        engine=str(it.get("engine") or ",".join(it.get("engines") or []) or "?"),
                                        published=it.get("publishedDate") or None))
            if len(results) >= body.limit:
                break
        answers = [a if isinstance(a, str) else str(a.get("answer") or "") for a in data.get("answers") or []]
        return SearchOut(query=body.query, results=results, answers=[a for a in answers if a][:3],
                         suggestions=[str(s) for s in data.get("suggestions") or []][:5],
                         unresponsive=[str(u[0]) if isinstance(u, list) and u else str(u) for u in data.get("unresponsive_engines") or []])

    @app.post("/v1/fetch", summary="Fetch a web page and save it as an output", response_model=FetchOut,
              responses={403: {"description": "Not allowed: a local or private address, or robots.txt"},
                         413: {"description": "Over 10 MB"}, 415: {"description": "Not a page, text or PDF"},
                         502: {"description": "The site failed"}, 504: {"description": "Over 20 s"}})
    async def fetch(body: FetchIn, x_aihub_origin: str | None = Header(None, include_in_schema=False)):
        """The page becomes markdown (main content only), saved under the web mod's outputs with a
        sidecar (URL, title, fetch time). PDFs are saved as documents. Only public http(s) pages;
        robots.txt is honoured; 10 MB and 20 s at most."""
        used()
        dry = fakeweb.is_dry_run(x_aihub_origin)
        state["busy"] += 1
        try:
            if dry:   # the agent eval: the fake web, never the internet
                f = fake_web().fetch(body.url.strip())
                if f is None:
                    raise safety.Refused("http_error", f"{body.url} answered HTTP 404 (the fake web of a dry run has no such page)",
                                         "fetch one of the search results", 502)
            else:
                f = await safety.fetch(clients["web"], robots, body.url.strip())
            page = await asyncio.to_thread(pages.convert, f, datetime.now().astimezone().isoformat(timespec="seconds"))
            path = await asyncio.to_thread(pages.save, out_dir, page, body.url.strip(), f.url, f.content_type, dry)
        except safety.Refused as e:
            state["refused"] += 1
            return error(e.status, e.code, e.detail, e.fix)
        except TimeoutError:
            state["refused"] += 1
            return error(504, "timeout", f"{body.url} took longer than {safety.TIMEOUT_S:.0f} s", "try another source")
        except httpx.InvalidURL as e:          # a URL or redirect httpx can't send (check_url refuses the known ones)
            state["refused"] += 1
            return error(422, "bad_url", f"{body.url} isn't a URL that can be fetched ({e})", "pass a full http:// or https:// URL")
        except httpx.HTTPError as e:
            return error(502, "fetch_failed", f"couldn't fetch {body.url} ({type(e).__name__}: {e})", "try another source")
        finally:
            state["busy"] -= 1
        state["fetches"] += 1
        note = None
        if page.kind == "document":
            note = "a PDF, saved as a document output: read it with the hub's document tools (hub_read_document)"
        return FetchOut(path=str(path.resolve()), url=body.url, final_url=f.url, title=page.title, kind=page.kind,
                        content_type=f.content_type, chars=len(page.text), content=page.text[:body.max_chars],
                        truncated=len(page.text) > body.max_chars, published=page.published, note=note)

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("AIHUB_PORT", "5102")), log_level="info")
