# SearXNG

An AIHub mod (plan 26.3): finds the SearXNG this machine runs, watches it and its engines, and adjusts its settings. SearXNG itself runs outside AIHub, in Docker ([the web mod's setup doc](../web/setup/web.md)); this mod's setup is [setup/searxng.md](setup/searxng.md). The guide to mods is [docs/mods.md](../../docs/mods.md).

| Route | What it does |
|---|---|
| `GET /health` | 200 while this server is up |
| `GET /v1/status` | SearXNG up or down, engines on, engines failing, the last test search's time |
| `GET /v1/endpoint` | `{url, found_by, up}`: the URL the `web` mod uses |
| `GET /v1/found`, `POST /v1/detect` | what was found (URL, container, compose folder, settings file); look again |
| `GET /v1/health`, `POST /v1/health/query` | `/healthz`, the last test search, recent history; run a test search now |
| `GET /v1/engines?enabled=&failing=` | every engine: on or off, categories, timeout, recent errors |
| `POST /v1/engines/{name} {enabled}` | turn an engine on or off |
| `GET /v1/settings`, `POST /v1/settings` | safe search, default language, timeouts, the JSON format; backups and recent changes |

Agent tools: `searxng_engines` and `searxng_health` (read), `searxng_set_engine` and `searxng_adjust` (risk `write`, so they show a card).

## How a change works (`searx.py`)

One change at a time:
1. Read `settings.yml`, edit it with ruamel.yaml so comments and layout stay (`settings.py`), and stop if nothing changed.
2. Back it up as `settings.yml.aihub-<date>` next to it.
3. Write it through the container, restart the container, wait for `/healthz`, run a test search (JSON when on), and check the change shows in `/config`.
4. If the check fails, put the backup back, restart again, and answer `409 change_failed` saying why.

A read or backup that fails (Docker down) is a `503` that changed nothing.

**Why through the container.** The file belongs to the container's `searxng` user and isn't writable from the host. `docker exec` runs as root inside the container (the `docker` group allows it), and writes the file in place, so its owner and mode stay. `containers.py` only ever touches `settings.yml` and its backups. They are the only files a mod writes outside the project (plan Phase 12.4's allowlist).

## Watching

`/healthz`, `/config` and `/stats/errors` every 60 s (`SEARXNG_WATCH_S`), and a test search every 10 min (`SEARXNG_QUERY_S`; each one asks the upstream engines, so not every minute).

## Working on it

```bash
.venv/bin/python -m pytest      # a fake SearXNG, a fake runtime, a fake docker CLI
aihub check searxng --start
```
