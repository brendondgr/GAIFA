"""Fetch rules (plan 26.1): http/https only; never loopback, private, link-local or `.local`
addresses, checked after DNS and on every redirect; 10 MB and 20 s caps; robots.txt honoured.

The address check runs where the connection is made (`Guard.connect_tcp`, an httpcore network
backend): the name is resolved once, every address it resolves to must be public, and the socket
connects to the address that was checked. So a redirect, a robots.txt request or a DNS answer
that changes between check and connect can't reach this machine or the LAN.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 20.0
MAX_REDIRECTS = 5
ROBOTS_MAX_BYTES = 512 * 1024
ROBOTS_TTL_S = 3600.0
USER_AGENT = "AIHub-web/0.1 (a personal assistant fetching a page a person asked for)"
ROBOTS_AGENT = "AIHub-web"
BLOCKED_SUFFIXES = (".local", ".localhost", ".localdomain", ".internal", ".home.arpa", ".lan")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class Refused(Exception):
    """A fetch the rules don't allow; `code` is the error code, `fix` what the caller can do instead."""

    def __init__(self, code: str, detail: str, fix: str, status: int = 403) -> None:
        super().__init__(detail)
        self.code, self.detail, self.fix, self.status = code, detail, fix, status


def address_refused(ip: str) -> str | None:
    """Why an address is off-limits (loopback, private, link-local, …), or None if it is public."""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return "not an IP address"
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    for word, bad in (("loopback", a.is_loopback), ("link-local", a.is_link_local), ("multicast", a.is_multicast),
                      ("unspecified", a.is_unspecified), ("private", a.is_private), ("reserved", a.is_reserved)):
        if bad:
            return word
    return None if a.is_global else "not a public address"


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of a URL the rules allow by its text; raises Refused otherwise."""
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError as e:
        raise Refused("bad_url", f"{url!r} isn't a URL ({e})", "pass a full http:// or https:// URL", 422) from None
    if u.scheme not in ("http", "https"):
        raise Refused("bad_scheme", f"only http and https URLs can be fetched, not {u.scheme or 'no scheme'}:",
                      "pass a full http:// or https:// URL", 422)
    host = (u.hostname or "").rstrip(".").lower()
    if not host:
        raise Refused("bad_url", f"{url!r} has no host", "pass a full http:// or https:// URL", 422)
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise Refused("blocked_address", f"{host} is a local name; only public web pages can be fetched",
                      "fetch a page on the public internet")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        why = address_refused(host)
        if why:
            raise Refused("blocked_address", f"{host} is a {why} address; only public web pages can be fetched",
                          "fetch a page on the public internet")
    return u.scheme, host, port or (443 if u.scheme == "https" else 80)


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(i[4][0]) for i in infos))


class Guard(httpcore.AsyncNetworkBackend):
    """Resolves, checks every address, connects to a checked one. `public` lists (ip, port) pairs to
    treat as public anyway: tests use it for their local server; the server never sets it."""

    def __init__(self, resolve: Resolver = system_resolve, public: Iterable[tuple[str, int]] = ()) -> None:
        self.resolve, self.public = resolve, set(public)
        self.inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                          socket_options: Iterable[object] | None = None) -> httpcore.AsyncNetworkStream:
        try:
            ips = await self.resolve(host, port)
        except OSError as e:
            raise Refused("dns_failed", f"couldn't resolve {host} ({e})", "check the URL's spelling", 502) from None
        if not ips:
            raise Refused("dns_failed", f"{host} has no address", "check the URL's spelling", 502)
        for ip in ips:
            why = None if (ip, port) in self.public else address_refused(ip)
            if why:
                raise Refused("blocked_address", f"{host} resolves to {ip}, a {why} address; only public web pages can be fetched",
                              "fetch a page on the public internet")
        return await self.inner.connect_tcp(ips[0], port, timeout=timeout, local_address=local_address,
                                            socket_options=socket_options)  # type: ignore[arg-type]

    async def connect_unix_socket(self, *a: object, **k: object) -> httpcore.AsyncNetworkStream:
        raise Refused("blocked_address", "unix sockets can't be fetched", "fetch a page on the public internet")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx's transport with the connection pool built on `Guard`, no proxies from the environment."""

    def __init__(self, guard: Guard) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(), max_connections=20,
                                                  max_keepalive_connections=5, keepalive_expiry=5.0,
                                                  network_backend=guard)


def make_client(guard: Guard | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=GuardedTransport(guard or Guard()), follow_redirects=False, trust_env=False,
                             headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5"},
                             timeout=httpx.Timeout(TIMEOUT_S, connect=10.0))


@dataclass
class Fetched:
    url: str              # the final URL, after redirects
    status: int
    content_type: str     # lower case, without parameters
    charset: str | None
    body: bytes


async def _read_capped(r: httpx.Response, cap: int) -> bytes:
    n = r.headers.get("content-length")
    if n and n.isdigit() and int(n) > cap:
        raise Refused("too_large", f"the page is {int(n) / 1e6:.1f} MB; the limit is {cap // (1024 * 1024)} MB",
                      "fetch a smaller page", 413)
    chunks, size = [], 0
    async for chunk in r.aiter_bytes():
        size += len(chunk)
        if size > cap:
            raise Refused("too_large", f"the page is over {cap // (1024 * 1024)} MB", "fetch a smaller page", 413)
        chunks.append(chunk)
    return b"".join(chunks)


class Robots:
    """robots.txt per origin, cached for an hour. 4xx means no rules; 5xx or no answer means none
    of the site may be fetched (RFC 9309 §2.3.1)."""

    def __init__(self) -> None:
        self.cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
        u = urlsplit(url)
        origin = f"{u.scheme}://{u.netloc}"
        hit = self.cache.get(origin)
        if not hit or time.monotonic() - hit[0] > ROBOTS_TTL_S:
            hit = (time.monotonic(), await self._load(client, origin))
            self.cache[origin] = hit
        rp = hit[1]
        if rp is None:
            return False, f"{origin}/robots.txt couldn't be read"
        return rp.can_fetch(ROBOTS_AGENT, url), f"{origin}/robots.txt disallows it"

    async def _load(self, client: httpx.AsyncClient, origin: str) -> urllib.robotparser.RobotFileParser | None:
        rp = urllib.robotparser.RobotFileParser(origin + "/robots.txt")
        url = origin + "/robots.txt"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                check_url(url)
                async with client.stream("GET", url, timeout=8.0) as r:
                    if r.is_redirect and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if 400 <= r.status_code < 500:
                        rp.parse([])
                        return rp
                    if r.status_code >= 500:
                        return None
                    body = await _read_capped(r, ROBOTS_MAX_BYTES)
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                    return rp
        except Refused as e:
            if e.code != "too_large":  # a refused or unknown address refuses the page too
                raise
            return None
        except httpx.HTTPError:
            return None
        rp.parse([])  # a redirect loop: treat as no rules
        return rp


async def fetch(client: httpx.AsyncClient, robots: Robots, url: str, cap: int | None = None) -> Fetched:
    """GET `url` under the rules: every hop is checked (scheme, host, address, robots.txt)."""
    cap = cap or MAX_BYTES
    async with asyncio.timeout(TIMEOUT_S):
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            ok, why = await robots.allowed(client, url)
            if not ok:
                raise Refused("robots_disallowed", f"{url}: {why} for automated fetches",
                              "open it in a browser yourself, or try another source")
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        raise Refused("bad_redirect", f"{url} redirects without a Location", "try another source", 502)
                    url = urljoin(url, loc)
                    continue
                if r.status_code >= 400:
                    raise Refused("http_error", f"{url} answered HTTP {r.status_code}", "try another source", 502)
                ctype = r.headers.get("content-type", "")
                body = await _read_capped(r, cap)
                return Fetched(str(r.url), r.status_code, ctype.split(";", 1)[0].strip().lower(), r.charset_encoding, body)
        raise Refused("too_many_redirects", f"more than {MAX_REDIRECTS} redirects", "try another source", 502)
