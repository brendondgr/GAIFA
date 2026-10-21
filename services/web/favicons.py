"""Site icons for Chat's Sources (`GET /v1/favicon?host=<host>`): fetched once per host from the site
itself, never from a third-party icon service, and cached under `data/state/web/favicons/`.

Where the icon comes from: `https://<host>/favicon.ico`, else the `<link rel="icon">` (or
`shortcut icon`, `apple-touch-icon`) of the site's home page, robots.txt permitting that page.
Every request goes through the web mod's fetch rules (safety.py): http(s) only, the address check
on every connection, redirects followed by hand and checked (at most 5). An icon is at most
100 KB, must say it is an image (or say nothing / octet-stream) and must start like an ICO, PNG,
GIF, JPEG or WebP: SVG is refused (it can carry script). It is served with the type its bytes
show, `nosniff` and a week's browser cache.

The cache is bounded: hits are kept 30 days, misses (no usable icon, or the site didn't answer in 8 s)
1 day, at most 2000 files and 20 MB (the oldest go first).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

import safety

MAX_ICON_BYTES = 100 * 1024
MAX_PAGE_BYTES = 256 * 1024          # of the home page, read to find its <link rel="icon">
TIMEOUT_S = 8.0                      # for the whole lookup of one host
HIT_TTL_S = 30 * 86400
MISS_TTL_S = 86400
MAX_FILES = 2000
MAX_TOTAL_BYTES = 20 * 1024 * 1024
BROWSER_CACHE_S = 7 * 86400
CONCURRENCY = 4

HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# The types an icon may claim; the bytes decide what it is.
CLAIMS = re.compile(r"^(image/(x-icon|vnd\.microsoft\.icon|ico|png|gif|jpeg|jpg|pjpeg|webp)|application/octet-stream|)$")
EXT_TYPES = {"ico": "image/x-icon", "png": "image/png", "gif": "image/gif", "jpg": "image/jpeg", "webp": "image/webp"}


class NoIcon(Exception):
    """No usable icon for this host (the reason is for the log and the error's detail)."""


# What one failed try raises: the next source is tried, and when none is left the host is a miss.
FAILED = (NoIcon, safety.Refused, httpx.HTTPError, httpx.InvalidURL, ValueError)


def valid_host(host: str) -> str | None:
    """The host, lower case without a trailing dot, when it is a public-looking DNS name (not an IP, not a local name)."""
    h = (host or "").strip().rstrip(".").lower()
    if not HOST_RE.match(h) or h.endswith(safety.BLOCKED_SUFFIXES) or h == "localhost":
        return None
    return h


def sniff(data: bytes) -> str | None:
    """The icon's file extension from its first bytes, or None (SVG, HTML and everything else)."""
    if data.startswith(b"\x00\x00\x01\x00") or data.startswith(b"\x00\x00\x02\x00"):
        return "ico"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class _Links(HTMLParser):
    """`<link rel="… icon …" href>` in a page's head, with their sizes and types."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.icons: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower().split()
        if a.get("href") and ("icon" in rel or "apple-touch-icon" in rel):
            self.icons.append(a)


def icon_links(html: str, base: str) -> list[str]:
    """The page's icon URLs, best first: not SVG, the size nearest 32 px, `icon` before `apple-touch-icon`."""
    p = _Links()
    try:
        p.feed(html)
    except Exception:          # a malformed page: whatever was found so far
        pass

    def size(a: dict[str, str]) -> int:
        m = re.search(r"(\d+)x\d+", a.get("sizes", ""))
        return int(m[1]) if m else 32 if "apple-touch-icon" not in a.get("rel", "") else 180

    out = []
    for a in sorted(p.icons, key=lambda a: (abs(size(a) - 32), "apple-touch-icon" in a.get("rel", ""))):
        href = a["href"].strip()
        if "svg" in a.get("type", "").lower() or re.search(r"\.svgz?($|[?#])", href, re.I) or href.lower().startswith("data:"):
            continue
        url = urljoin(base, href)
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out[:3]


class Favicons:
    """The lookup and its cache. `origin(host)` is where a host's site is (`https://<host>`; tests point it at their server)."""

    def __init__(self, folder: Path, client: Callable[[], httpx.AsyncClient], robots: safety.Robots,
                 origin: Callable[[str], str] | None = None) -> None:
        self.folder, self.client, self.robots = folder, client, robots
        self.origin = origin or (lambda h: f"https://{h}")
        self.inflight: dict[str, asyncio.Future[tuple[bytes, str] | None]] = {}
        self.slots = asyncio.Semaphore(CONCURRENCY)

    # ---------- the cache ----------
    def _cached(self, host: str) -> tuple[bytes, str] | None | bool:
        """(bytes, ext) for a fresh hit, None for a fresh miss, False when there is nothing fresh."""
        now = time.time()
        for ext in EXT_TYPES:
            f = self.folder / f"{host}.{ext}"
            try:
                if now - f.stat().st_mtime < HIT_TTL_S:
                    return f.read_bytes(), ext
            except OSError:
                continue
        try:
            if now - (self.folder / f"{host}.miss").stat().st_mtime < MISS_TTL_S:
                return None
        except OSError:
            pass
        return False

    def _store(self, host: str, got: tuple[bytes, str] | None) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            for f in self.folder.glob(f"{glob_escape(host)}.*"):
                f.unlink(missing_ok=True)
            name = f"{host}.{got[1]}" if got else f"{host}.miss"
            tmp = self.folder / f".{name}.part"
            tmp.write_bytes(got[0] if got else b"")
            tmp.replace(self.folder / name)
            self.prune()
        except OSError:
            pass                 # a cache that can't be written still answers

    def prune(self) -> None:
        """Drops expired entries, then the oldest until the folder is within MAX_FILES and MAX_TOTAL_BYTES."""
        now, files = time.time(), []
        for f in self.folder.iterdir():
            try:
                st = f.stat()
            except OSError:
                continue
            ttl = MISS_TTL_S if f.suffix == ".miss" else HIT_TTL_S
            if f.name.startswith(".") and now - st.st_mtime > 60 or now - st.st_mtime > ttl:
                f.unlink(missing_ok=True)
            elif not f.name.startswith("."):
                files.append((st.st_mtime, st.st_size, f))
        files.sort()
        total = sum(s for _, s, _ in files)
        while files and (len(files) > MAX_FILES or total > MAX_TOTAL_BYTES):
            _, s, f = files.pop(0)
            f.unlink(missing_ok=True)
            total -= s

    # ---------- the lookup ----------
    async def get(self, host: str) -> tuple[bytes, str] | None:
        """(bytes, ext) of the host's icon, or None when it has none we can serve. One lookup per host at a time."""
        hit = self._cached(host)
        if hit is not False:
            return hit  # type: ignore[return-value]
        if host in self.inflight:
            return await asyncio.shield(self.inflight[host])
        fut: asyncio.Future[tuple[bytes, str] | None] = asyncio.get_running_loop().create_future()
        self.inflight[host] = fut
        try:
            async with self.slots:
                try:
                    async with asyncio.timeout(TIMEOUT_S):
                        got = await self._lookup(host)
                except (*FAILED, TimeoutError):
                    got = None
            self._store(host, got)
            fut.set_result(got)
            return got
        except BaseException as e:
            if not fut.done():
                fut.set_exception(e)
                fut.exception()      # retrieved: nobody else may be waiting
            raise
        finally:
            self.inflight.pop(host, None)

    async def _lookup(self, host: str) -> tuple[bytes, str]:
        base = self.origin(host)
        try:
            return await self._icon(base + "/favicon.ico")
        except FAILED as e:
            first: Exception = e
        if isinstance(first, safety.Refused) and first.code == "blocked_address":
            raise first          # the host itself is off-limits: don't try its page either
        ok, _ = await self.robots.allowed(self.client(), base + "/")
        if not ok:
            raise NoIcon(f"{host}/favicon.ico: {first}; robots.txt disallows its home page")
        page, url, _ = await self._get(base + "/", MAX_PAGE_BYTES, truncate=True, accept="text/html,application/xhtml+xml")
        for link in icon_links(page.decode("utf-8", "replace"), url):
            try:
                return await self._icon(link)
            except FAILED:
                continue
        raise NoIcon(f"{host} has no icon that can be served")

    async def _icon(self, url: str) -> tuple[bytes, str]:
        body, _, ctype = await self._get(url, MAX_ICON_BYTES, accept="image/*")
        if not CLAIMS.match(ctype):
            raise NoIcon(f"{url} is {ctype}, not an icon")
        ext = sniff(body)
        if not ext:
            raise NoIcon(f"{url} isn't an ICO, PNG, GIF, JPEG or WebP image")
        return body, ext

    async def _get(self, url: str, cap: int, *, accept: str, truncate: bool = False) -> tuple[bytes, str, str]:
        """(body, final URL, content type) of a GET under the fetch rules: every hop checked, redirects by hand;
        the body capped (refused over `cap`, or cut there with `truncate`)."""
        client = self.client()
        for _ in range(safety.MAX_REDIRECTS + 1):
            safety.check_url(url)
            async with client.stream("GET", url, headers={"Accept": accept}) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        raise NoIcon(f"{url} redirects without a Location")
                    url = urljoin(url, loc)
                    continue
                if r.status_code >= 400:
                    raise NoIcon(f"{url} answered HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if truncate:
                    body = await _read_some(r, cap)
                else:
                    try:
                        body = await safety._read_capped(r, cap)
                    except safety.Refused:
                        raise NoIcon(f"{url} is over {cap // 1024} KB") from None
                return body, str(r.url), ctype
        raise NoIcon(f"{url}: more than {safety.MAX_REDIRECTS} redirects")


async def _read_some(r: httpx.Response, cap: int) -> bytes:
    """Up to `cap` bytes of the body (the rest isn't read)."""
    chunks, size = [], 0
    async for chunk in r.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= cap:
            break
    return b"".join(chunks)[:cap]


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", s)


def default_folder() -> Path:
    """`$WEB_STATE/favicons`, else `$AIHUB_ROOT/data/state/web/favicons`, else `./data/state/web/favicons`."""
    if os.environ.get("WEB_STATE"):
        return Path(os.environ["WEB_STATE"]) / "favicons"
    return Path(os.environ.get("AIHUB_ROOT") or ".") / "data" / "state" / "web" / "favicons"
