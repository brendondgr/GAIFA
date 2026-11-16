<!-- gaifa-setup
id = "searxng"
title = "SearXNG watcher (the searxng mod)"
models = []
scan = []
summary = "Search for GAIFA: your SearXNG if one answers here, else GAIFA's own in a container; its health, engines and settings"
recommended = true   # offered first for chat (capability-enablement 1.4)
gpu = false
disk_gb = 0.03
needs = ["uv"]
check = "gaifa start searxng && gaifa check searxng"

smoke = ".venv/bin/python scripts/setup_search.py is yours || curl -sf 'http://127.0.0.1:5200/search?q=gaifa&format=json' | grep -q results"

[[steps]]
run = "gaifa install searxng"
what = "makes .venv/ from requirements-dev.txt (about 28 MB, under a minute)"

[[steps]]                       # capability-enablement 5.3: yours, when one answers with JSON
run = ".venv/bin/python scripts/setup_search.py use-yours"
what = "uses the SearXNG of yours that answers on this machine (nothing is created)"
ask_if = "python3 scripts/setup_search.py is yours"

[[steps]]
run = ".venv/bin/python scripts/setup_search.py json-on"
what = "turns the JSON format on in your SearXNG (settings.yml backed up first, restarted, checked; put back if the check fails)"
ask = "Your SearXNG answers but refuses JSON results, which GAIFA's search needs. Turn the JSON format on in it (settings.yml is backed up first)?"
ask_if = "python3 scripts/setup_search.py is yours_no_json"
optional = true
next = "to use GAIFA's own SearXNG instead, press Start GAIFA's own on the SearXNG page"

[[steps]]
run = ".venv/bin/python scripts/setup_search.py managed"
what = "starts GAIFA's own SearXNG: a container from SearXNG's image (about 0.4 GB, pinned), on 127.0.0.1:5200, settings in data/state/searxng/managed/"
ask = "No SearXNG answers on this machine. Start GAIFA's own? (A container from SearXNG's image, about 0.4 GB, on 127.0.0.1:5200, settings in data/state/searxng/managed/; without it web search stays off.)"
ask_if = "python3 scripts/setup_search.py can-manage"
optional = true
next = "web search stays off until a SearXNG answers: start GAIFA's own from the SearXNG page, or give yours (POST /v1/source)"

[[variants]]                    # plan 39.1: no GPU work, so one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# SearXNG watcher: setup

**The easy way:** paste the text of `gaifa setup --prompt searxng` into your coding agent (Claude Code, Codex): it reads this doc, runs the same commands and checks, and can fix what goes wrong. Or run `gaifa setup searxng` yourself.

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `searxng` mod's own venv (FastAPI, httpx, ruamel.yaml), and the SearXNG search goes through. Setting it up looks for a SearXNG of yours first (`SEARXNG_URL`, 127.0.0.1:8080 and :8888): one that answers with JSON is used as it is and nothing is created; one that refuses JSON gets a question (turn JSON on in it, with a backup of its `settings.yml`); when none answers, a question offers **GAIFA's own**: a container `gaifa-searxng` from SearXNG's own image (pinned by digest, about 0.4 GB), on 127.0.0.1:5200 (the next free port up to 5209), its settings in `data/state/searxng/managed/` (capability-enablement 5.3). A "no" leaves web search off until one answers. The mod then watches the SearXNG it uses and changes its settings when you or the agent ask (engines on or off, timeouts, safe search, the default language, the JSON format). The `web` mod reads the URL from this mod; without it, it uses its own `SEARXNG_URL`.

**Before deleting this mod's folder**, remove GAIFA's own SearXNG if you started it (`curl -X DELETE 'http://127.0.0.1:7000/api/s/searxng/v1/managed?image=true'`): the container and its image live in podman's or Docker's store. Its settings folder then belongs to SearXNG's own user; delete it with `podman unshare rm -rf data/state/searxng/managed` (rootless podman) or `sudo rm -rf data/state/searxng/managed` (Docker).

## Tested with

Read from this machine on 2026-10-20: SearXNG `2026.6.22+952896d29` in the Docker container `searxng` (image `searxng/searxng:latest`), compose project `~/Tools/SearchXNG`, settings in `~/Tools/SearchXNG/searxng/settings.yml` (owned by the container's `searxng` user, uid 977, mode 644); Docker 29.9.1, Docker Compose v5.6.0; the mod's venv: Python 3.14 (uv-managed), fastapi, httpx, ruamel.yaml 0.19.1.

## Prerequisites

- SearXNG running in a Docker or podman container whose image is `searxng/*`, with its settings folder bind-mounted (the usual compose setup in [the web mod's setup doc](../../web/setup/web.md)).
- To change settings: your user can run `docker` (the `docker` group) or `podman` for that container. Watching works without it.

## Install

```bash
gaifa install searxng
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

## Check

```bash
gaifa check searxng --start
```

Expect `searxng: all checks passed`.

```bash
curl -s "$(gaifa url api/s/searxng/v1/search-state)"
```

Expect `"up":true,"json":true` and `"using":"yours"` (with your SearXNG's `url`) or `"using":"managed"` (GAIFA's own, `http://127.0.0.1:52xx`). `"using":"none"` means no SearXNG answers yet.

## When it fails

| What you see | What to check | The fix |
|---|---|---|
| `"using":"none"`; the SearXNG page says *No SearXNG answers* | `curl -s http://127.0.0.1:8080/healthz` (yours), `podman ps -a --filter name=gaifa-searxng` (GAIFA's) | start yours, or *Start GAIFA's own* on the SearXNG page (`POST /api/s/searxng/v1/managed`), or `gaifa setup searxng` and answer GAIFA's own |
| `"json":false` | `curl -s "<url>/search?q=test&format=json" \| head -c 100` gives `403` | add `json` to `search.formats` (the Search settings tab, with a backup); GAIFA's own has it already |
| GAIFA's own won't start: `no_runtime` | `podman --version; docker --version` | install podman (`sudo dnf install podman`, or `sudo apt install podman`), then *Start GAIFA's own* again |
| `docker`: permission denied | `id -nG` lacks `docker` | use podman (rootless), or `sudo usermod -aG docker $USER` and log in again (yours to run) |
| `no_port`: ports 5200–5209 all taken | `ss -ltn \| grep ':52'` | free one, or use your own SearXNG (*Use mine on port …*) |
| a change is refused with `settings_invalid` | the SearXNG page (it says where `settings.yml` doesn't parse) | fix the YAML, or copy the newest `settings.yml.gaifa-<date>` back |
| `gaifa status` shows searxng `not set up`; a chat says it isn't set up | `ls services/searxng/.venv` | `gaifa setup searxng` (or the Set up dialog: Settings → Services → Set up) |
| `gaifa status` shows searxng `failed` | `gaifa logs searxng` (the last lines say why) | fix what the log names, then `gaifa start searxng`; still failing: `gaifa setup --prompt searxng` for your coding agent |
| searxng is off (Settings → Services shows its switch off) | Settings → Services | turn its switch on, or ask GAIFA's agent to turn it on; `gaifa start searxng` starts it once |

## What to look for

- **What a change does.** It copies `settings.yml` to `settings.yml.gaifa-<date>` next to it, writes the new file through the container (to `.settings.yml.gaifa-new`, a copy with the same owner and mode, checked for size, then renamed over `settings.yml`, so a write that breaks off leaves the old file whole), runs `docker compose restart searxng` in the compose folder (or `docker restart` without compose), waits for `/healthz`, runs a test search and checks the change shows in `/config`. If any step fails it copies the backup back the same way and restarts again. The newest 10 backups are kept; each change deletes older `settings.yml.gaifa-<date>` files (only names of that exact form).
- **settings.yml doesn't parse.** After a hand edit that broke the YAML (or a file that isn't a mapping), the mod still starts; its status, the Engines tab and `GET /v1/settings` (`409 settings_invalid`) say where ("settings.yml doesn't parse: … at line 4, column 1"), and every change is refused with the same answer until the file is fixed or a backup is copied back.
- **Docker itself broken.** If `docker exec` fails (on this machine on 2026-10-20, containerd crashed on a damaged `meta.db`), changes fail with `backup_failed` before anything is written. Watching keeps working, since it only reads.
- **Network binding.** This mod never changes how SearXNG listens. Here it listens on every interface (`GRANIAN_HOST=::` from the image, with `network_mode: host`), by the user's choice.
- **Engines that fail.** The Engines tab's "Failing" filter lists engines with recent errors (CAPTCHAs, rate limits). Turning them off makes searches faster; they recover on their own after SearXNG's suspension times.

## Known gaps

- Default categories aren't adjustable: SearXNG keeps them as a per-browser preference, not a setting.
- Per-engine response times aren't shown: SearXNG's JSON doesn't have them (its `/stats` page does).
