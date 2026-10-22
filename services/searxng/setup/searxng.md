<!-- aihub-setup
id = "searxng"
title = "SearXNG watcher (the searxng mod)"
models = []
scan = []
summary = "SearXNG watcher: see your SearXNG's health and engines, and change its settings from AIHub or the agent"
gpu = false
disk_gb = 0.03
needs = ["uv"]
check = "aihub start searxng && aihub check searxng"

[[steps]]
run = "aihub install searxng"
what = "makes .venv/ from requirements-dev.txt (about 28 MB, under a minute); SearXNG itself is set up as in the web mod's setup doc"

[[variants]]                    # plan 39.1: no GPU work, so one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# SearXNG watcher: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `searxng` mod's own venv (FastAPI, httpx, ruamel.yaml). It finds the SearXNG this machine runs, watches it and its engines, and changes its settings when you or the agent ask (engines on or off, timeouts, safe search, the default language, the JSON format). It doesn't install SearXNG: that is in [the web mod's setup doc](../../web/setup/web.md). The `web` mod reads the URL this mod finds; without this mod it uses its own `SEARXNG_URL`.

## Tested with

Read from this machine on 2026-10-20: SearXNG `2026.6.22+952896d29` in the Docker container `searxng` (image `searxng/searxng:latest`), compose project `~/Tools/SearchXNG`, settings in `~/Tools/SearchXNG/searxng/settings.yml` (owned by the container's `searxng` user, uid 977, mode 644); Docker 29.9.1, Docker Compose v5.6.0; the mod's venv: Python 3.14 (uv-managed), fastapi, httpx, ruamel.yaml 0.19.1.

## Prerequisites

- SearXNG running in a Docker or podman container whose image is `searxng/*`, with its settings folder bind-mounted (the usual compose setup in [the web mod's setup doc](../../web/setup/web.md)).
- To change settings: your user can run `docker` (the `docker` group) or `podman` for that container. Watching works without it.

## Install

```bash
aihub install searxng
```

Makes `.venv/` from `requirements-dev.txt` (under a minute).

## Choosing models

None: the mod runs no model. Which search engines SearXNG asks is chosen on its Engines tab.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `SEARXNG_URL` | `services/searxng/.env` | optional | Where SearXNG answers; default: probe `127.0.0.1:8080` and `:8888`, then the container's own URL |
| `SEARXNG_WATCH_S` | same | optional | Seconds between health checks (default 60) |
| `SEARXNG_QUERY_S` | same | optional | Seconds between test searches (default 600; each one asks the upstream engines) |

## Check it works

```bash
aihub start searxng && aihub check searxng
```

Expect `all checks passed`. The mod's Engines tab shows SearXNG up, the container, its compose folder and settings file, and every engine with its errors.

```bash
services/searxng/.venv/bin/python -m pytest services/searxng/tests -q
```

The tests use a fake SearXNG, a fake runtime and a fake `docker` command; they never touch the real container.

## What to look for

- **What a change does.** It copies `settings.yml` to `settings.yml.aihub-<date>` next to it, writes the new file through the container (to `.settings.yml.aihub-new`, a copy with the same owner and mode, checked for size, then renamed over `settings.yml`, so a write that breaks off leaves the old file whole), runs `docker compose restart searxng` in the compose folder (or `docker restart` without compose), waits for `/healthz`, runs a test search and checks the change shows in `/config`. If any step fails it copies the backup back the same way and restarts again. The newest 10 backups are kept; each change deletes older `settings.yml.aihub-<date>` files (only names of that exact form).
- **settings.yml doesn't parse.** After a hand edit that broke the YAML (or a file that isn't a mapping), the mod still starts; its status, the Engines tab and `GET /v1/settings` (`409 settings_invalid`) say where ("settings.yml doesn't parse: … at line 4, column 1"), and every change is refused with the same answer until the file is fixed or a backup is copied back.
- **Docker itself broken.** If `docker exec` fails (on this machine on 2026-10-20, containerd crashed on a damaged `meta.db`), changes fail with `backup_failed` before anything is written. Watching keeps working, since it only reads.
- **Network binding.** This mod never changes how SearXNG listens. Here it listens on every interface (`GRANIAN_HOST=::` from the image, with `network_mode: host`), by the user's choice.
- **Engines that fail.** The Engines tab's "Failing" filter lists engines with recent errors (CAPTCHAs, rate limits). Turning them off makes searches faster; they recover on their own after SearXNG's suspension times.

## Known gaps

- Default categories aren't adjustable: SearXNG keeps them as a per-browser preference, not a setting.
- Per-engine response times aren't shown: SearXNG's JSON doesn't have them (its `/stats` page does).
