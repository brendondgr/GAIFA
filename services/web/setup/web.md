<!-- gaifa-setup
id = "web"
title = "Web (SearXNG search and page fetching)"
models = []
scan = []
summary = "Web: search through your SearXNG and fetch pages and PDFs into Outputs, for you and the agent"
recommended = true   # offered first for chat (capability-enablement 1.4)
gpu = false
disk_gb = 0.1
needs = ["uv"]
check = "gaifa start web && gaifa check web"
after = ["searxng"]             # capability-enablement 5.3: setting up web sets up search with it (yours, or GAIFA's own)
smoke = "curl -sf -X POST -H 'content-type: application/json' -d '{\"query\": \"gaifa\"}' \"${GAIFA_URL:-http://127.0.0.1:7000}/api/s/web/v1/search\" | grep -q '\"results\"'"

[[steps]]
run = "gaifa install web"
what = "makes .venv/ from requirements-dev.txt (about 70 MB, under a minute); search goes through the SearXNG the searxng setup finds or starts"

[[variants]]                    # plan 39.1: no GPU work, so one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# Web: setup

**The easy way:** paste the text of `gaifa setup --prompt web` into your coding agent (Claude Code, Codex): it reads this doc, runs the same commands and checks, and can fix what goes wrong. Or run `gaifa setup web` yourself.

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `web` mod's own venv (FastAPI, httpx, trafilatura) and the **SearXNG** it searches through. Setting up web sets up the `searxng` mod first (`after`), which uses a SearXNG of yours when one answers, or starts GAIFA's own in a container if you say yes (its setup doc). The web mod calls `GET <url>/search?q=…&format=json` and says in its status when search is off (`tools_off`: no SearXNG answers, or it refuses JSON). `web_search` needs SearXNG; `web_fetch` (pages and PDFs into Outputs) works without it. The rest of this doc is the by-hand way to run a SearXNG of your own.

## Tested with

Read from this machine on 2026-10-20:

- **SearXNG** `2026.6.22+952896d29`, image `searxng/searxng:latest` at `sha256:3f52dca114d96af03ab68c666614571395e1c1d9ac7b4eecf7f88ee5072a0942`, run with Docker `29.9.1` and Docker Compose `v5.6.0` on Fedora 44, from `~/Tools/SearchXNG/docker-compose.yml` with `restart: unless-stopped` and `network_mode: host`, settings bind-mounted from `~/Tools/SearchXNG/searxng/` to `/etc/searxng`.
- **Its settings:** `use_default_settings: true`; `search.formats: [html, json]`; `server.limiter: false`; `outgoing.request_timeout: 10.0`; engines google, bing, duckduckgo and wikipedia on top of the defaults.
- **The mod's venv:** Python 3.14.6 (uv-managed), fastapi 0.156.2, uvicorn 0.54.0, httpx 0.28.1, httpcore 1.0.9, trafilatura 2.3.1, lxml 6.1.3.

## Prerequisites

- [The hub](../../../docs/setup/hub.md).
- For search: Docker or Podman to run SearXNG (or any SearXNG reachable from this machine). Nothing from [host.md](../../../docs/setup/host.md) beyond that; no GPU, no models.

## Install

### SearXNG

Skip this if a SearXNG with the JSON format already answers (the check below).

Make a folder for it outside the project, for example `~/Tools/SearchXNG/`, with this `docker-compose.yml`:

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./searxng:/etc/searxng
    environment:
      - BASE_URL=http://localhost:8080/
      - INSTANCE_NAME=searxng-local
      - BIND_ADDRESS=127.0.0.1:8080
      - GRANIAN_HOST=127.0.0.1
```

and `searxng/settings.yml` next to it. The `json` format is what this mod needs; SearXNG refuses `format=json` with HTTP 403 without it:

```yaml
use_default_settings: true
server:
  secret_key: "<the output of: openssl rand -hex 32>"
  limiter: false
  image_proxy: false
search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - html
    - json
outgoing:
  request_timeout: 10.0
```

Then, in that folder:

```bash
docker compose up -d
```

Pulls `searxng/searxng` from Docker Hub (376 MB on disk here, a minute or two) and starts it on `127.0.0.1:8080`. `restart: unless-stopped` brings it back after a reboot once Docker starts. Podman works the same with `podman compose up -d` (or `podman run` with the same options).

### The mod

```bash
gaifa install web
```

Makes `.venv/` in this folder from `requirements-dev.txt` (the server's packages and pytest; about 70 MB, under a minute).

## Choosing models

None: the mod runs no model. Pages are read with trafilatura, and search is whatever engines your SearXNG asks.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `SEARXNG_URL` | `services/web/.env` (copy `.env.example`), or `config.toml [services.web] env` | optional | The SearXNG to search through; default `http://127.0.0.1:8080` |
| `port` | `service.toml [run]` | fixed | 5102 (architecture §2) |

## Check

Run both, in order: the mod's own check, then a page and a search through the hub.

```bash
gaifa check web --start
```

Expect `web: all checks passed`.

```bash
curl -s -X POST -H 'content-type: application/json' -d '{"url":"https://example.com"}' "$(gaifa url api/s/web/v1/fetch)" | head -c 200
```

Expect JSON starting `{"path":".../outputs/web/<date>/…-example-com-example-domain.md","url":"https://example.com",…,"kind":"text"`: reading pages works (it needs no SearXNG).

```bash
curl -s -X POST -H 'content-type: application/json' -d '{"query":"GAIFA test"}' "$(gaifa url api/s/web/v1/search)" | head -c 200
```

Expect `{"query":"GAIFA test","results":[{"title":…`: search works through SearXNG. `{"code":"searxng_down",…}` means no SearXNG answers (set up the `searxng` mod).

## When it fails

| What you see | What to check | The fix |
|---|---|---|
| a search answers `searxng_down`; the Web page says *Search isn't connected* | `curl -s "$(gaifa url api/s/searxng/v1/search-state)"` (`up`, `json`, `using`) | `gaifa setup searxng` (yours or GAIFA's own), or Connect search on the Web page |
| a search answers HTML `403 Forbidden` | `curl -s "http://127.0.0.1:8080/search?q=test&format=json" \| head -c 100` | add `json` to `search.formats` in SearXNG's `settings.yml` (the searxng mod's Search settings tab does it with a backup) |
| a fetch is refused with a reason (`blocked_address`, `robots_disallowed`, `too_large`) | the answer's `detail` | not a fault: the page is local, disallowed or too big (README's rules); fetch another source |
| a page comes back nearly empty | the output's text (`chars` in the answer) | the page builds itself with JavaScript: try another source |
| `gaifa status` shows web `not set up`; a chat says it isn't set up | `ls services/web/.venv` | `gaifa setup web` (or the Set up dialog: Settings → Services → Set up) |
| `gaifa status` shows web `failed` | `gaifa logs web` (the last lines say why) | fix what the log names, then `gaifa start web`; still failing: `gaifa setup --prompt web` for your coding agent |
| web is off (Settings → Services shows its switch off) | Settings → Services | turn its switch on, or ask GAIFA's agent to turn it on; `gaifa start web` starts it once |

## What to look for

- **Engines that fail.** SearXNG asks several engines at once; some answer with CAPTCHAs or rate limits (on this machine brave, duckduckgo and startpage did on 2026-10-20, while bing and google answered). A search still returns what the others found, and lists the failed ones in `unresponsive`. If results get thin, disable the failing engines in `settings.yml` or add others.
- **Rate limiter.** With `server.limiter: true` SearXNG may answer 429 to bursts from the agent; the mod reports `searxng_limited`. On a machine only you use, leave it off.
- **Listening on every interface.** With `network_mode: host`, the image's server (granian) listens on `GRANIAN_HOST`, which the image sets to `::` (every interface), whatever `BIND_ADDRESS` says. This machine's container doesn't set `GRANIAN_HOST`, so its SearXNG answers on `*:8080`, from the LAN too. Set `GRANIAN_HOST=127.0.0.1` (as above) and `docker compose up -d` again to keep it on loopback.
- **Pages the rules refuse.** `web_fetch` never reaches local or private addresses (so it can't be pointed at SearXNG, the hub or the LAN), honours `robots.txt`, and stops at 10 MB or 20 s. These are refusals with a reason, not faults: the README lists the rules.
- **Pages that need JavaScript.** The fetch reads the HTML the server sends; a page that builds itself in the browser comes back nearly empty. Try another source.

## Known gaps

- GAIFA doesn't install or start SearXNG; `gaifa doctor` doesn't check it yet.
- `~/Tools/SearchXNG/searxng-docker.service` (a system unit that runs `docker compose up -d`) exists on this machine but isn't installed; the container comes back after a reboot through Docker's restart policy instead.
