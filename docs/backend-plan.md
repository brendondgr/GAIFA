# AIHub — Build plan

How AIHub gets built, step by step: the backend described in [architecture.md](architecture.md), and the UI from [design-brief-ui.md](design-brief-ui.md) **wired in as each piece of the backend lands**. The visual and structural reference throughout is Claude Design's Part A v1 export in [reference/ui-export-2026-10-04/](reference/ui-export-2026-10-04/README.md).

> This is a plan. Ticked steps have landed; the rest is not implemented yet.

**How to work this plan**
- **Every phase has three parts:**
  1. **Build:** the backend steps.
  2. **Wire:** the UI areas that switch from mock to live data. The UI is complete from the start (Phase 1), and each phase replaces mock data with real data in its areas.
  3. **Checks & deliverables:** what must be true, and what exists, before the phase counts as done. The next phase doesn't start until they're all ticked.
- **Each step ends with its tests passing and a commit** (message style: `AIHub (2.3): Service state machine with health checks`). Check steps off here as they land.
- **Every phase ends with the docs in sync.** If behavior changed, `architecture.md` and the brief's API sections are updated in the same commit.
- **Sizes:** **S** ≈ a short session, **M** ≈ one or two sessions, **L** ≈ several.

**Stages**

| Stage | Phases | What | Touches what works today? |
|---|---|---|---|
| A — Foundation | 0–6 | The hub, built against fake mods, with the UI wired area by area. Ends with Part A revision 2 (compact + graphical) fully live. | No (Phase 0 only commits pending work) |
| B — Moving the apps in | 7–10 | One app per phase, each with its Part B page | One app at a time; each old app runs until its cutover step |
| C — New capabilities | 11–13 | The ComfyUI mod, runtimes moved inside, the agent-ready API (tool catalog, approvals, model facts, MCP, the agent eval) | ComfyUI and the old venvs; nothing is deleted without approval |
| D — Chat interface | 14–16 | Chat with our own Claude-Code-style agent, save states, everything inside the folder | No |
| E — Image to 3D | 17 | Hunyuan3D 2.1, TRELLIS.2, SAM 3D Body and SAM 3D Objects as image engines in `gen3d` | gen3d and comfy; Cube3D keeps working |
| F — vLLM | 18 | A `vllm` mod: vLLM on this machine (Strix Halo, gfx1151) in kyuz0's container, published to the relay | relay (new registrations); lcpp untouched |
| G — Chat activity | 19 | The Chat page shows a turn's work as one compact fold of steps (thinking, tools, approvals), from the design study's picks | `web/chat/` only; the agent's events are unchanged |

| Phase | What | Size | UI that goes live |
|---|---|---|---|
| 0 | Prep in the existing repos | S | — |
| 1 | Repo, skeleton, UI baseline | M | `system` area |
| 2 | Running mods: supervisor, proxy, operations, template | L | `services`, `logs`, `operations`, `proxy`, `events` |
| 3 | Models registry | M | `models` |
| 4 | Outputs index | M | `outputs` |
| 5 | Memory manager | M | `memory` |
| 6 | Metrics, dashboards and UI revision 2 | M–L | `settings`, `metrics`, `widgets`; after this, everything is live by default |
| 7 | Move in `tts` (LocalTTS) | M | Speech page (Part B3) |
| 8 | Move in `gen3d` (3DGenerate) | M | 3D Generate page (B4) |
| 9 | Move in `relay` (DashLLM) + `opencode` | M | LLM Relay page (B2) + its traffic widget |
| 10 | Move in `lcpp` (LLMs) | M | LLM Launcher page (B1) |
| 11 | New `comfy` mod (ComfyUI) | L | Images & Video page (B5) |
| 12 | Runtimes moved inside the mods | M | Doctor panel in Settings |
| 13 | Agent-ready API (tools, approvals, model facts, MCP, eval) | L | `tools`: tool badges + the approvals popover (parameter cards) |
| 14 | Chat and the agent | L | `chat`: the Chat page, Settings → Agent |
| 15 | Save states: sessions | M | `sessions`: the Sessions panel |
| 16 | Everything inside the folder | S–M | Logs read from `data/logs/` |
| 17 | Image to 3D in `gen3d` | L | 3D Generate page: engine picker, image input, per-engine settings |
| 18 | New `vllm` mod (vLLM) | M–L | vLLM page (profiles, engine log, throughput); its models in the relay and Chat |
| 19 | Chat activity: steps, not cards | M | `chat`: the thread view (activity fold, output strip, the dock above the composer) |

# Stage A — Foundation

---

## Phase 0 — Prep in the existing repos

- [x] **0.1 Commit LocalTTS's uncommitted work.** 8 files are live in the running service but not committed: the 180 s idle default, the ROCm profiler fix, `KillMode=mixed`, and request de-duplication. Also fix the README, which still says engines unload after "10 minutes".
  *Done when:* `git status` is clean and `localtts status` is healthy.
- [x] **0.2 Commit lcpp's uncommitted work and fix its known bugs.**
  - Commit the Hugging Face downloads feature (`downloads.py`, its routes and tests; 10 modified and 3 untracked files).
  - Fix `web/assets/utils.js:20`: `download()` calls `h()`, which only exists in `app.js`, so the logs drawer's "Download .log" button throws.
  - Make `supervisor._exit_future` fall back to polling when `os.pidfd_open` is missing.
  - Clean stale data: `data/generated/*.ini` (removed models), `serenity-26B-A4B` in `data/recent.local.json`, and the model in `utils/e2e_live.sh`.
  - **Ask the user** whether the catalog entries `gemma-4-E4B-it` and `ornith1-35B` (files missing) should be removed or kept for a re-download.
  *Done when:* 82/82 tests pass (81 + the no-pidfd test), and "Download .log" works.
- [x] **0.3 Check the other two repos.** Commit anything pending in 3DGenerate and DashLLM. Remove the dead `RELAY_ADMIN_TOKEN`, `RELAY_API_KEY` and `RELAY_REQUIRE_CLIENT_KEY` from DashLLM's `.env` (`.env.example` was already clean).
- [x] **0.4 Back up what will move** (small; the models are not copied, because moving them is a reversible rename). Copy these into `~/Backups/aihub-premigration-<date>/`:
  - `relay.db` and `gen3d.db`, using SQLite's online backup, not `cp`
  - LocalTTS `data/voices/`
  - lcpp `data/*.json`
  - `~/.config/tts-engines/engines.json`
  - `~/.config/systemd/user/{relay,opencode,lcpp,localtts,gen3d}.service`
  - `~/.local/bin/{comfyui,localtts,gen3d,lcpp,relay}`
  - the four repos' `.env` / `*.env` files
- [x] **0.5 Capture each app's OpenAPI** while they're running. Save `:5040/openapi.json`, `:5050/openapi.json`, `:7710/api/openapi.json` and `:4000/openapi.json` into the backup folder from 0.4. Step 1.7 copies them into `utils/tests/fixtures/openapi/`, and Phase 2.6 tests the operation converter on these real files.

## Phase 1 — Repo, skeleton and UI baseline

- [x] **1.1 Create the repo.**
  - `git init`.
  - `.gitignore`:
    ```
    .venv/
    __pycache__/
    .pytest_cache/
    /data/models/*
    !/data/models/registry.json
    !/data/models/.gitkeep
    /data/databases/*
    !/data/databases/.gitkeep
    /outputs/*
    !/outputs/.gitkeep
    /services/*/.venv/
    /services/*/runtime/
    /services/*/.env
    ```
  - Empty `data/models/registry.json` (`{"version": 1, "models": {}}`), and `.gitkeep`s.
  - `pyproject.toml`:
    - deps: `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic>=2`, `tomlkit`, `watchfiles`, `pillow`
    - dev: `pytest`, `pytest-asyncio`
  - `uv venv && uv sync`.
  - **CLAUDE.md**, short and true today:
    - what AIHub is, and the layout (pointing at `docs/architecture.md`)
    - the commands
    - the mod contract in 5 lines
    - rules: **never `git clean -x/-X`** (deletes the models); nothing is written outside the project root except the allowlist in Phase 12.4; mods talk to the hub only over HTTP; no import-time side effects; tests pass before every commit; keep `docs/` in sync with behavior
  *Done when:* the first commit contains the docs, the skeleton folders and CLAUDE.md.
- [x] **1.2 `utils/paths.py` + `utils/config.py`.**
  - **`Paths`:** the root is `app.py`'s folder, or `AIHUB_ROOT`. Derived dirs are created on startup. `write_atomic()` writes a temp file, then fsyncs and renames.
  - **`Config` (pydantic):** mirrors architecture §9. It's loaded with `tomllib`, and a missing file means defaults.
  - **Refuse to start** if `hub.host` isn't loopback (`127.0.0.1`, `::1` or `localhost`).
  - **`save()`** goes through `tomlkit`: it changes only the keys given, and keeps comments and order.
  - **`service_override(id)`** merges `[services.<id>]` over the manifest.
  *Done when:* tests cover defaults, invalid values (clear error naming the key), a round trip that keeps comments, and the non-loopback refusal.
- [x] **1.3 `utils/db.py`.**
  - `data/databases/hub.db` in WAL mode, with migrations by `PRAGMA user_version`.
  - Migration 001: `activity(id, ts, service, level, text, route)`, `service_peaks(service PK, peak_bytes, updated_ts)`, `kv(key PK, value)`.
  - One writer thread, a reader connection per thread, and `async` helpers (`execute`, `fetchone`, `fetchall`) built on `asyncio.to_thread`.
  *Done when:* migrations apply once and are idempotent; concurrent reads during a write work.
- [x] **1.4 `utils/events.py`.**
  - **`EventBus`:** one bounded asyncio queue (1000) per subscriber. On overflow, drop that subscriber's queued events and send `{"type":"resync"}` (the UI refetches, so the backlog is stale).
  - **`publish(HubEvent)`**.
  - **`ActivityLog`:** persisted, last 500 kept in memory, pruned after 30 days.
  - **`Alerts`:** a keyed set; publishes `alert` / `alert_cleared`.
  - **`GET /api/events`** (router in `utils/routes/events.py`): SSE with `retry: 3000` and a `: ping` comment every 15 s.
  *Done when:* tests cover subscriber fan-out, overflow → resync, and SSE framing.
- [x] **1.5 `utils/server.py` + `app.py`.**
  - **`create_app(paths, config, backend)`:** nothing at import time. The lifespan starts subsystems in the order in architecture §5 and stops them in reverse.
  - **Error envelope:** `{detail, code, data?}` for `HTTPException` and validation errors.
  - **Routes:**
    - `/api/system`
    - `/config.js`
    - `/api/docs` and `/api/openapi.json`
    - static `web/` at `/` (the UI baseline arrives in 1.8)
  - **`app.py`:** argparse `--port`, `--dev` (subprocess backend), `--no-autostart`, `--demo-mods` (also load the fake mods from `utils/tests/fixtures/mods/`, for UI work before the real apps move in). It binds **both `127.0.0.1` and `[::1]`**; reuse gen3d's `__main__` socket code, which fixes browsers resolving `localhost` to IPv6.
  - *As built:* `--dev` and `--demo-mods` are accepted and stored on `Options`; they take effect when the backends (2.2) and fake mods (1.7) exist. Ctrl+C exits 0; a `SIGINT`/`SIGTERM` first closes open SSE streams so shutdown doesn't wait on them.
  *Done when:* `python app.py` serves `/api/system` and `/api/docs`.
- [x] **1.6 `bin/aihub` + `utils/cli.py` + `bin/aihub.service.in`.**
  - **The bash wrapper** runs `utils/cli.py` (standard library only, `urllib`, like lcpp's CLI) with the hub venv.
  - **Commands:**
    - `serve` (foreground = `python app.py`)
    - `install` / `uninstall` (write and enable `~/.config/systemd/user/aihub.service` from the template; symlink `~/.local/bin/aihub`)
    - `start|stop|restart [id|all]` (no id = the hub itself)
    - `status`, `logs [id] [-f] [-n N]`, `load|unload <id>`
    - `open [route]`, `url`
    - `new <id>` (Phase 2.8)
    - `models scan|list|verify <id>` (Phase 3)
    - `doctor` (grows over time; Phase 12.4)
  - **When the hub is down**, it says so and suggests `aihub start`.
  - *As built:* `logs` reads the journal (`aihub.service`, or `aihub-<id>.service` for a mod), so it works with the hub down. `new` and `models` exit 2 naming the phase that builds them. Mod commands get the hub's `not_found` until Phase 2. Installed 2026-10-04; linger was already on.
  *Done when:* `aihub install && aihub status` works and survives a logout/login (linger).
- [x] **1.7 Test harness.**
  - `utils/tests/conftest.py`: a temporary project root, the app built with `SubprocessBackend`, and an `httpx.AsyncClient` over ASGI.
  - Copy the real OpenAPI files from 0.5 into `utils/tests/fixtures/openapi/`.
  - **Fake mods** in `utils/tests/fixtures/mods/` (hyphenated, since mod ids can't contain `_`):
    - `fake-ok`: health, status, openapi, echo, an audio route, an SSE route, and a route that writes an output
    - `fake-slow`: becomes healthy after 3 s
    - `fake-crash`: exits after 1 s
    - `fake-mem`: allocates N MB on `/v1/load` and frees it on `/v1/unload`
  - *As built:* the four share one standard-library server, `fixtures/mods/_fakemod.py` (`python3 ../_fakemod.py <mode>` in each `service.toml`), so they also prove a mod needs nothing but HTTP. `conftest.py` also has `fake_mod(mode)` (runs one on a free port), `hub_process` (a real `app.py`) and `services_dir(*ids)`. The app is built with no backend until 2.2 adds `SubprocessBackend`.
  *Done when:* `uv run pytest` is green.
- [x] **1.8 The UI baseline in `web/`.**
  - Copy the v1 export from `docs/reference/ui-export-2026-10-04/` into `web/`: `Hub.dc.html`, `OutputCard.dc.html`, `JsonView.dc.html`, `mock.js` and `support.js`.
  - Put React 18.3.1 and ReactDOM 18.3.1 (UMD production builds) in `web/vendor/`. Do the same for the IBM Plex Sans and JetBrains Mono fonts, with a local `@font-face` stylesheet.
  - **Serving `/`:** `utils/server.py` serves `Hub.dc.html` and adds `<script src="/vendor/react.production.min.js">`, `react-dom` and `<script src="/config.js">` before `support.js` as it goes out. The runtime then skips its unpkg download, and a future export drops in unchanged.
  - **Font links:** the Google Fonts `<link>`s are rewritten to the local stylesheet the same way.
  - **Component files:** `*.dc.html` are served as static files from `web/`.
  - **`web/PATCHES.md`** starts here. It lists every edit made to an export: the Hub → AIHub renames, and the 1.9 mode switch. Revision 2 (Phase 6) asks Claude Design to build these in, so the list goes back to empty.
  - *As built:* the serving code is `utils/routes/web.py` (`GET /`, `GET /{name}.dc.html`). Fonts are the Latin subsets of `@fontsource` (400/500/600) with their OFL licenses in `web/vendor/fonts/`. Checked 2026-10-04 in the browser: every request went to 127.0.0.1:7000.
  *Done when:* `python app.py`, then opening `http://127.0.0.1:7000/`, shows the full v1 UI on mock data, and the browser's network panel shows **no request leaving 127.0.0.1**.
- [x] **1.9 `web/api.js`: the hybrid API.**
  - **HTTP client:** `ApiError` plus an HTTP implementation of every method in brief §6.2 and §11.7, returning the same shapes as the mock. SSE goes through `EventSource`, and non-JSON responses (audio, files) become blobs with object URLs.
  - **`createApi({base, liveAreas, mock})`:** routes each method to HTTP when its area is live, and to the mock otherwise. The method → area map follows brief §6.1.
  - **`subscribe`** merges the live `/api/events` stream (filtered to live areas) with mock events for the rest.
  - **Methods that span areas** (`getOverview`) are assembled from the per-area calls until the aggregate route exists (Phase 6).
  - **`/config.js`** sets `AIHUB_API_BASE = ""` and `AIHUB_LIVE_AREAS`. That list comes from a registry in the hub: each subsystem registers its area when its routes are mounted. `?mock` forces everything to mock.
  - **Patch the export:** replace `import('mock.js')` → `createMockApi()` in `Hub.dc.html` with `createApi(...)`, and record it in `PATCHES.md`.
  - **Unit tests** (Node, no browser): area routing, merged subscribe, error mapping.
  - *As built:* tests in `utils/tests/web/api.test.mjs`, run by `utils/tests/web/test_api_js.py` (Node from PATH, or the host's via `flatpak-spawn --host` inside the toolbox). While any area is live, `subscribe` keeps `/api/events` open even with `events` mocked: its error is how the UI sees the hub go down. `callService` turns a mod's own error into `upstream_error`. The hub's own errors carry an `X-AIHub-Error: <code>` header so the two can be told apart. Settings shows a MOCK note per section (`SETTINGS_AREAS`, patch 5).

**Wire — Phase 1:** the `system` area goes live:
- the sidebar footer (version, hub status dot)
- Settings → General, Paths and About
- the "AIHub not responding" banner, which appears when the hub stops and clears when it's back

**Checks & deliverables — Phase 1**
- [x] `uv run pytest` is green, and `aihub install && aihub status` works after a re-login. *(Green: 88 tests. Installed 2026-10-04 with linger on and the unit enabled; the re-login itself is for the user to confirm.)*
- [x] Opening `/` shows the full UI. Settings → About shows the real version, PID and uptime, and every other section shows a **MOCK** marker. *(The process info is under General; Paths is live too, so it has no marker.)*
- [x] Stopping the hub shows the down banner within one retry; starting it clears it.
- [x] No requests go to outside hosts, checked in the browser's network panel.
- [x] Delivered: the repo, CLAUDE.md, `app.py`, `bin/aihub`, `utils/` (paths, config, db, events, server, cli), `web/` (baseline, vendor, `api.js`, `PATCHES.md`), and the test harness.

## Phase 2 — Running mods

- [x] **2.1 `utils/manifest.py`.**
  - **Schema:** pydantic, exactly architecture §4.3, including `health = "tcp"` for binaries without an HTTP health route (a TCP connect counts as healthy).
  - **Discovery:** `services/*/service.toml`, skipping folders that start with `_` or `.`, so `_template` is never run.
  - **Errors are collected** into `manifest_errors` and never crash the hub.
  - **Placeholders and env:** expand them (architecture §4.4), build the env (hub vars + `env_file` + manifest `env` + config override), and resolve the effective port.
  - *As built:* `discover()` returns a `Mod` per folder (id = folder name, even when the manifest is broken, so the UI can list it). Unknown keys are errors, to catch typos. `command` may be a string (shell-split). Ports that clash with another mod or the hub are manifest errors; clashes created by `config.toml` overrides come from `check_effective_ports()`. An unknown `{placeholder}` raises `ManifestError` at launch; `env_file` values are not expanded and a missing `env_file` is allowed. `start_order()` applies `after` (unknown ids ignored, cycles broken).
  *Done when:* tests cover a valid manifest, each error kind, placeholders, override merging and the `_template` skip.
- [x] **2.2 Backends: `utils/backends/{base,systemd,subprocess}.py`.**
  - **Protocol:** `start(spec)`, `stop(id, timeout)`, `state(id)` (`active|inactive|failed`, pid, started_ts), `list_ours()`, `logs(id, n)`, `follow(id)`.
  - **systemd:**
    - start: `systemd-run --user --unit=aihub-<id> --property=KillMode=mixed --property=TimeoutStopSec=<stop_timeout_s> --working-directory=<cwd> --setenv=… -- <argv>`. Clear a stale failed unit with the same name first (`systemctl --user reset-failed aihub-<id>`).
    - stop: `systemctl --user stop`.
    - state: `systemctl --user show -p ActiveState,SubState,MainPID,ExecMainStartTimestamp,ControlGroup`.
    - logs: `journalctl --user -u aihub-<id> -o json` (`-n N`, `-f`).
    - Port the existing pieces from `services/lcpp/src/lcpp/backends/systemd.py` (today at `~/Models/LLMs/src/lcpp/backends/systemd.py`).
  - **subprocess:** an asyncio subprocess in its own process group, with a log ring buffer. Used by tests and `--dev`.
  - *As built:* the protocol is async (`start`, `stop`, `state` → `UnitState(active, pid, started_ts, result, exit_status)`, `list_ours`, `logs`, `follow`, `close`). `SystemdBackend(prefix=)` lets tests use their own unit names; logs use `journalctl --user -u`, so systemd's own lines (exit status) are included. `SubprocessBackend` stops like `KillMode=mixed` (SIGTERM to the main process, then SIGKILL to the group) and stops every child on `close()`. Starting a mod that is already running is a `BackendError` in both.
  *Done when:* both backends pass the same contract tests (systemd ones are marked and skipped where systemd isn't available).
- [x] **2.3 `utils/services.py`: the state machine.** `ServiceManager` holds one `Service` per manifest: state, load, timestamps, pid, health and status caches, stats, `last_error`, `in_flight`, `last_request_ts`.
  - **start:**
    - If the port is taken by something that isn't our unit → `failed` / `port_in_use`, naming the process holding it (`proc.port_owner`).
    - Otherwise launch, then poll health every 0.5 s up to `start_timeout_s` → `ready`. On failure → `failed`, with the last 20 log lines in `last_error`.
  - **monitor:**
    - When ready, health is checked every 5 s. 2 misses → `degraded`; 5 misses or the unit inactive → `failed`.
    - `restart = "on-failure"` retries after 2 / 4 / 8 s, at most 3 times per 5 min.
  - **stop:** `stopping` → backend stop → `stopped`. **restart** = stop + start.
  - **On hub boot:** adopt running `aihub-*` units (→ health check → `ready`), then autostart the enabled mods in `after` order, then config order.
  - **`kind = "external"`:** health only; start/stop return `not_unloadable`-style errors.
  - Every change publishes a `service` event and an activity item.
  - *As built:* start and stop return at once (`wait=True` blocks until settled); a generation number per service makes stale health and restart tasks give up. A mod that never gets healthy is stopped before it is marked failed, as is one that misses 5 health checks. Failures set an alert (`svc-<id>`, cleared on ready or stop) and an activity item linking to Logs. Adoption only takes units whose working directory is inside this hub's root; a running unit whose folder was deleted is stopped, again only if it ran from this root. A unit that failed while the hub was down shows as `failed` "… while AIHub was down". Starting a disabled mod is `409 service_disabled`; start/stop on an external mod is `409 external_service`. Summaries are built in `utils/services/views.py` (the supervisor became the `utils/services/` package in 2.8); `utils/proc.py` has `port_owner()`. `app.py` uses the systemd backend, or child processes with `--dev` (and where no systemd user manager answers).
  *Done when:* tests cover ready, slow-start timeout, crash → restart → failed, adoption, disabled mods never starting, and a port conflict.
- [x] **2.4 Status polling.** For mods with `[run] status`:
  - Poll every 2 s while loading, busy or running jobs, otherwise every 10 s, and only while ready.
  - Map to `load`, `idle_s`, `busy`, `stats` and `jobs`; publish `service` / `job` events only on change.
  - **Without a status route:** `load = "n/a"`, unless the mod has `[memory]`. Then the load state follows the hub's own load/unload calls, confirmed by memory.
  - *As built:* `utils/services/status.py`. `validate()` keeps the valid parts of a status body and lists the problems (2.10 reports them). Changes to load, busy, stats, the estimate or jobs publish a `service` event; `idle_s` alone doesn't. A hub-started `loading`/`unloading` holds until the mod confirms. A job that disappears while active is published as `done`; jobs still active when the mod stops become `cancelled` (`failed` when it crashed). The fake mod gained `POST /v1/jobs` and `FAKE_BAD_STATUS=1`.
  *Done when:* tests cover the stats, load and jobs mapping, events only on change, and a malformed status body.
- [x] **2.5 `utils/proxy.py`: `ANY /api/s/{id}/{path:path}`.**
  - **Streaming both ways:** the request body streams to httpx, and the response is `StreamingResponse(resp.aiter_raw())` with `resp.aclose` as a background task.
  - **Headers:** drop hop-by-hop headers; add `X-Forwarded-Prefix: /api/s/<id>`.
  - **Timeouts:** connect 3 s, write 300 s (uploads), read none (streams), pool 10 s.
  - **Errors:** `503 service_not_running` unless the mod is ready or degraded; `502 upstream_error` on connection errors. Mod responses, including 4xx and 5xx, pass through unchanged.
  - **Tracking:** an `in_flight` counter and `last_request_ts`.
  - **No GZip middleware** on this route.
  - **Client disconnects** close the upstream request.
  - Leave a hook point for memory triggers (Phase 5.5).
  - *As built:* the path is forwarded still percent-encoded, as the client sent it. Headers named in `Connection:` are dropped too, and `X-Forwarded-Host` / `-Proto` are added. `Location` headers pointing at the mod (`/x` or `http://127.0.0.1:<port>/x`) are rewritten to `/api/s/<id>/x`. The proxy client ignores `HTTP(S)_PROXY`. `ServiceManager.before_proxy` is the 5.5 hook. Tests run against a real uvicorn server (the in-process ASGI client buffers responses).
  *Done when:* tests cover JSON, binary audio, a 50 MB multipart upload, SSE arriving unbuffered (first event in under 200 ms), 4xx passthrough, and a mod that's down → 503.
- [x] **2.6 `utils/operations.py` + `GET /api/services/{id}/operations`.**
  - **Fetching:** fetch the mod's OpenAPI each time it becomes ready, and cache it per process start.
  - **Conversion to the brief's `Operation`:**
    - Resolve local `$ref`s.
    - Path and query params.
    - Body: JSON preferred; multipart with `format: binary` → file field.
    - Response kind: `[api.responses]` override, then the declared 2xx content type (audio, image, video, `model/gltf-binary`, `text/event-stream`, octet-stream or zip → file), then 204 → empty, else json.
    - Hide `[api] hide` entries plus `/docs`, `/redoc`, the openapi route, static mounts, HEAD and OPTIONS.
    - `destructive` = DELETE or `confirm`.
    - `tool` comes from `[tools]`.
  - *As built:* schemas are inlined and simplified for a generic form: `anyOf: [T, null]` → `T` + `nullable: true`, a single `allOf` is merged, and OpenAPI 3.1 file fields (`contentMediaType`) get `format: binary`. Recursive refs stop with a `(recursive: Name)` placeholder. `[api] hide` entries are globs on `"METHOD /path"` (`"* /admin/*/tunnel*"`). Without tags, the tag is the first path segment after `v1`/`api`. The list is fetched in the background when a mod becomes ready, cached per process start (pid + start time), and kept while the mod is stopped; a mod never read and not running gives `503 service_not_running`. Snapshots: `fixtures/openapi/snapshots/` (regenerate with `UPDATE_SNAPSHOTS=1`).
  *Done when:* tests convert `fake-ok` and the four real OpenAPI fixtures from 0.5, with snapshot assertions.
- [x] **2.7 Service routes** (UI brief §6.2): list, detail, start, stop, restart, load, unload, logs, logs/stream, operations, and `PUT config`.
  - **load/unload:** call the manifest operations through the proxy client. Make-room logic is added in Phase 5.
  - **`PUT config`:** validate, then save through `config.save()`. Port, env and command changes return `restart_required: true`. Enabled and autostart apply immediately.
  - *As built:* response models in `utils/api_models.py`; load/unload in `utils/services/loading.py` (in the background: 202 with `loading`, then a `service` event; on failure the load state goes back and an error activity item says why; `make_room` is accepted and ignored until Phase 5). start/stop/restart take `?wait=1`, which the CLI uses to print the final state (and `last_error` on failure). `PUT config` validates port clashes first and leaves the file untouched on any error (`422 invalid_config`); `env` replaces the whole table; `idle_unload_s: null` removes the key; disabling a running mod stops it. Log streams end when the hub shuts down (`EventBus.closing`). `services`, `logs`, `operations`, `proxy` and `events` are live in `/config.js`.
  *Done when:* the route tests pass, and pydantic response models match the brief's §6.4 types.
- [x] **2.8 `services/_template/` + `aihub new`.**
  - **The template:**
    - `service.toml`
    - `server.py`: FastAPI with `/health`, `/v1/status`, `GET /v1/hello?name=`, `POST /v1/echo`, and `POST /v1/note`, which writes a text output to `{outputs}` following the conventions
    - `requirements.txt`, and `install.sh` (`uv venv` + install)
    - `README.md`: the mod contract on one page
    - `ui/page.js`: the Example mod's Hello tab, moved out of the export in 2.9
  - **`aihub new <id> [--name] [--port]`:** copy the template, fill in the id, name and first free port in 5100–5199, run `install.sh`, and print the next steps.
  - *As built:* no hub restart is needed: `aihub new` calls the new `POST /api/services/rescan` (also `aihub rescan`), which adds, removes and updates mods and autostarts new ones; a running hub reports the new mod's state. The template also has `GET /v1/widgets/calls` + a `[[ui.widgets]]` entry, a `[tools]` entry, and `install.sh` uses uv-managed Python (`--python-preference only-managed`) so the venv works on the host and in a toolbox. `aihub install <id>` reruns a mod's install script. The mod commands live in `utils/cli_mods.py`. Found while testing: `[run].command` paths must not follow symlinks (a venv's `bin/python` is one), and tests now get an isolated `AIHUB_ROOT`/`AIHUB_URL` by default.
  *Done when:* `aihub new hello && aihub restart` gives a working mod at `/api/s/hello/v1/hello`, with operations listed.
- [x] **2.9 Mod pages in the shell.**
  - Check whether the dc runtime's `<dc-import>` accepts a bound (dynamic) `name`.
  - **Either way:**
    - Serve `GET /Mod_<id>.dc.html` from `services/<id>/ui/Page.dc.html`.
    - Add a `ModPage.dc.html` host that loads `/ui/services/<id>/page.js` and calls `mount(el, ctx)` on a ref, with cleanup on unmount. Build the `ctx` from brief §5 out of the hybrid `api`.
  - **If dynamic names don't work:** the shell keeps a static list of built-in `Mod_<id>` imports, and third-party mods use `page.js`.
  - Move the Example **Hello** tab out of `Hub.dc.html` into `services/_template/ui/page.js`, and record it in `PATCHES.md`.
  - *As built:* the dc runtime reads `<dc-import name>` once, as a literal (`walkComponent`), and refuses a bound `<x-import from>`, so dynamic names don't work. Every `page.js` therefore goes through one static host, `web/ModPage.dc.html`, which `import()`s the module and mounts it on a callback ref; it remounts when the mod, tab, params or running state change, and otherwise just refreshes `ctx.service`. `ctx.ui` is `web/mod-ui.js` (themed DOM helpers: `h`, `card`, `button`, `input`, `field`, `json`, `empty`, `badge`, `table`, …). Summaries gained `page_url` (`/ui/services/<id>/<file>` or `/Mod_<id>.dc.html`). `Page.dc.html` pages (Part B) are served at `/Mod_<id>.dc.html`; the shell gets a literal `<dc-import name="Mod_<id>">` per built-in page when its phase lands. The shell now also handles `resync`. Checked in the browser: `aihub new hello` against a running hub shows its Hello tab, which calls the mod through the proxy; stopping it remounts the page's Start state; `?mock` shows the template's page for Example. Shell patch: `web/PATCHES.md` #6.
  *Done when:* `aihub new hello` gives a mod whose custom tab renders inside the shell.
- [x] **2.10 `aihub check <id>`: a mod self-test.**
  - **Route:** `GET /api/services/{id}/check` returns `{ok, checks: [{name, ok, detail}]}`. The CLI prints it and exits 1 on any failure.
  - **Checks, in order:**
    - the manifest parses (each `manifest_errors` entry is one failure)
    - the command's executable exists and `cwd` is a folder
    - the port is free or held by this mod
    - health answers 2xx while the mod is ready
    - the OpenAPI document loads and converts (2.6)
    - the `status` route matches architecture §4.6 (≤ 4 stats, numeric or string values, jobs shaped like `Job`)
    - each `[[ui.widgets]]` source answers with `WidgetData`
    - `ui/page.js` or `ui/Page.dc.html` exists when declared, and `page.js` has a default export with `tabs` and `mount`
    - `[memory]` and `[tools]` operations name operations that exist in the OpenAPI
  - **Why:** gives a person or an agent writing a mod a fast write → check → fix loop without opening the UI.
  - *As built:* `utils/services/check.py`. Each check has a `status` (ok, fail, warn, skip) as well as `ok`; the mod passes when nothing failed. Checks that need the mod running are skipped with a hint while it's stopped, and `?start=1` / `aihub check <id> --start` starts it first. Also checked: the `state` (a failed mod reports its `last_error`), a missing `env_file` (warn), widget sources being in the OpenAPI, and page modules calling `fetch()` (warn). The manifest parser now reports a missing `[run].command` alongside field errors, so a bad manifest shows every problem at once.
  *Done when:* tests run it against `fake-ok` (all pass), a mod with a bad manifest, a mod whose health fails, and a status route with the wrong shape; `aihub check hello` passes on a fresh `aihub new hello`.
- [x] **2.11 The mod-authoring guide.**
  - **`docs/mods.md`:** the whole mod contract on one page, as a how-to:
    - the three requirements and the `service.toml` reference (linking architecture §4)
    - the four UI levels: nothing (generic page), `status` stats (auto-charted), `[[ui.widgets]]`, and a custom `ui/page.js` with its `ctx`
    - outputs, memory, models and tools
    - turning an existing app into a mod (`kind = "external"` or a wrapped command)
    - the `aihub new` → edit → `aihub check` → `aihub restart` loop, and the common errors with their fixes
  - **Skill `.claude/skills/aihub-mod/SKILL.md`:** for agents asked to build or port a mod; points at `docs/mods.md` and the template, and requires `aihub check` to pass.
  - Link both from `CLAUDE.md`, the `aihub` skill and `services/_template/README.md`.
  - *As built:* checked by following it: `aihub new hello` against a running hub passes `aihub check hello` (manifest, command, health, OpenAPI, operations, status, widget data, page) and shows its Hello tab inside the shell. The widget is validated by the check now and drawn on the dashboard from Phase 6. Writing the guide surfaced `openapi = ""` for mods with no OpenAPI (TOML has no null).
  *Done when:* following `docs/mods.md` from a clean checkout gives a mod that passes `aihub check` and shows its custom tab and a widget.

**Wire — Phase 2:** `services`, `logs`, `operations`, `proxy` and `events` go live:
- the sidebar service list with status dots
- the Overview services tiles and the activity feed
- every service page: header actions, the Overview, API, Logs and Settings tabs, and custom tabs
- the jobs chip, for mods that report jobs
- the command palette's start/stop actions

The live mods at this point are the fake mods (`python app.py --dev --demo-mods`) and any mod made with `aihub new`.
- *As wired:* the overview's activity, alerts and jobs also come from the hub, through `GET /api/events/recent` (until `/api/overview` in Phase 6). The memory panel, models, outputs and settings stay mock until their phases.

**Checks & deliverables — Phase 2**
- [x] With fake mods, every brief §8 service-page state can be reached for real:
  - stopped, starting, ready, degraded, failed (with log excerpt), and unreachable
  - the manifest-error tile
  - API tab responses: JSON, audio, stream with Stop, upstream error, multipart upload, destructive confirm
  - Logs follow / pause / filter
  - Settings save with restart-required
  - *Checked 2026-10-04* in the browser against `python app.py --dev --demo-mods`:
    - every state above: degraded by freezing a mod; starting via a slow mod; failed with its log tail; the manifest-error tile from a broken folder
    - every API response kind, including a 200 KB multipart upload and a 50-event stream stopped partway
    - the Logs live tail and filter, and Settings saved with the restart note
    - the jobs chip, and the palette's "Start Fake OK"
  - *Fixed along the way:*
    - a port change no longer breaks the running mod
    - Settings saves no longer pin defaults into config.toml
    - stopping a stream keeps its lines
    - `web/` files are revalidated, so upgrades reach the browser
    - the activity feed is real
- [x] On a hub restart, running mods stay up and are adopted, and the UI reconnects by itself.
  - *Checked* with the installed hub (systemd): `aihub restart` left `aihub-demo.service` running with the same PID, and the hub logged "Adopted Demo, already running". The open page went: down banner → "Reconnected" toast → normal.
- [x] `aihub new demo`, then restart: the mod appears in the sidebar, its tile and its API tab, **with no hub code changed**.
  - *Checked:* no restart was needed (rescan). `demo` ran as `aihub-demo.service`, passed `aihub check demo`, showed its Hello tab, served journal logs and answered `/api/s/demo/v1/hello`. It was then removed.
- [x] Delivered: `manifest.py`, `backends/`, `services/` (the supervisor package), `proxy.py`, `operations.py`, the service routes, `_template`, `aihub new`, `ModPage`, `aihub check` and `docs/mods.md`.

## Phase 3 — Models registry

- [x] **3.1 `utils/registry.py` core + routes.**
  - **Storage:** load and save `registry.json` atomically, with sorted keys and 2-space indent.
  - **Status** is computed when read, from file stats and sha256 fields: `ok`, `missing`, `partial`, `unverified`, `checksum_mismatch` or `verifying`.
  - **Totals** by kind, plus disk usage.
  - **Routes:** `GET /api/models` (filters), `GET/PUT /api/models/{id}`, and `DELETE /api/models/{id}?files=`.
  - **Deleting files** only touches paths inside `data/models`, removes empty folders, and returns `model_in_use` while any mod using the model is loading, loaded or busy.
  - *As built:* a package, `utils/registry/` (`model.py` stored shape and validation, `store.py` the `Registry`), with routes in `utils/routes/models.py`. The registry reloads itself when `registry.json` changes on disk. An entry that fails validation is kept unchanged on save and reported in `Registry.errors`; an unreadable file (bad JSON, another version) makes the registry read-only (`409 registry_invalid`) so it is never overwritten. Status rules: `missing` when no file exists; `partial` when one is missing, smaller or larger than recorded, or still a `<file>.part`; `checksum_mismatch` when verify recorded an `actual_sha256`; `ok` when every file has a checksum and hasn't been modified since `verified_at`; otherwise `unverified`. A running mod with no `[memory]` section counts as holding the model. Deleting a symlinked file removes the link, and its target only when that lies inside the model's own folder (hf-cache blobs); a folder link that leads out of `data/models` is refused. Deletes publish `{"type": "model_deleted", "id"}`.
- [x] **3.2 Scanner: `POST /api/models/scan` + `POST /api/models`.** Rules for recognising models:
  - **`llm/`:** GGUF grouping ported from lcpp's `catalog.discover` (sidecars `mmproj-*`/`mtp-*`, split tails `-0000N-of-0000M`).
  - **Hugging Face folders:** a folder with `config.json`, `model_index.json`, or `*.safetensors` + config is one `hf-dir` model.
  - **`comfyui/<role>/<file>`:** one model per file.
    - `diffusion_models`, `unet` and `checkpoints` → `image`, or `video` when the name matches `wan|scail|t2v|i2v|video`.
    - `text_encoders` → `text-encoder`; `vae`; `loras` → `lora`; `clip_vision` → `vision`; `upscale_models` → `upscale`.
  - **`voices/<slug>/voice.json`** → `voice`.
  - **`hf-cache/hub/models--org--name`** → source `huggingface`, with the revision from `refs/main`.
  - **Skip** dotfiles, `*.part`, `*.lock` and `.cache/`.
  - **Output:** unregistered entries with a suggested id, kind and name. `POST /api/models` adds one.
  - *As built:* `utils/registry/scan.py` (the rules) and `adding.py` (filtering out what's registered, and `POST /api/models`). Beyond the rules above: any other folder of weights one level below a top folder (`3d/cube3d-v0.5/`, no config) is one model; loose weight files are one model each; a Hugging Face folder with no weight files yet is skipped; GGUF sidecars only join a folder holding exactly one model; symlinked folders are followed, except ones that loop back up. `Discovered` also carries `suggested_id` (unique), `format`, `files` and, for hf-cache and voices, `source`. `POST /api/models` accepts optional `id`, `files`, `format`, `tags` and `notes` (for mods registering a download); without `files` it uses the scanner's grouping for that path. A file already registered elsewhere, or a taken id, is `409 model_exists`; a scanner-known source replaces the UI's bare `{"type": "local"}`. A registered HF folder owns everything inside it, so a new file there isn't offered separately; a GGUF folder doesn't, so a second quant is. Checked against the real folders (read-only, through symlinks): 45 models, 200 GB, every kind as expected.
- [x] **3.3 Verify: `POST /api/models/{id}/verify`.**
  - A one-at-a-time background queue that hashes in 8 MB reads in a thread, with `model` progress events every second.
  - If no checksum is recorded it records one; otherwise it compares and flags `checksum_mismatch`.
  - Cancelled cleanly on shutdown.
  - *As built:* `utils/registry/verify.py` (`Verifier`). While queued or hashing, a Model has status `verifying` and `progress` (0–1). `?reset=1` forgets the recorded checksums and records new ones (how a re-downloaded file is accepted). A model with no files on disk is `409 model_files_missing`. Deleting a model cancels its verification; shutdown stops the hashing thread within one 8 MB read and records nothing half-done. A file that changes size while being read is reported, not recorded. Results go to the activity feed (a mismatch at `error` level). `aihub models list | show | scan [--add] | verify <id>… | --all [--reset]` is in `utils/cli_models.py`. Hashing ran at ~1.6 GB/s on a real 2.7 GB GGUF.
- [x] **3.4 "Used by".** A model's `services` are the explicit list plus every mod whose `[models] dirs` contains the model's top folder. `ServiceDetail.models` is filled from this.
  - *As built:* a `[models] dirs` entry matches the model's path by folder prefix, so it can be a top folder (`comfyui`) or a deeper one (`comfyui/loras`); `comfyui/loras` doesn't match `comfyui/loras-extra`. The explicit list comes first, then matching mods in sidebar order. The same list drives the `?service=` filter and the in-use rule for deletes. `ServiceDetail.models` is `Registry.used_by(id)`.
- [x] **3.5 Registry alerts.** Keep alerts current for missing, partial and checksum-mismatch counts.
  - *As built:* `utils/registry/alerts.py`. The ids match the mock: `models-missing` and `models-partial` (warn, counts, linking to the filtered list), `sum-<id>` (error, one per mismatched model), plus `registry-invalid` when registry.json or one of its entries can't be read. They are recomputed after every change, whenever the list is read, and once a minute by a watcher that also picks up edits to registry.json.

**Wire — Phase 3:** `models` goes live:
- the Models page: summary, filters, table, drawer, scan → add, verify with live progress, and the rule that blocks deleting models in use
- the registry alerts on Overview
- "models used" on service pages
- *As wired:* web patch 7 (`web/PATCHES.md`): the `model_deleted` event; verify `progress` on the status badge and the drawer's button ("verifying 42%"); the in-use rule in the delete dialog matches the hub's; an empty registry offers "Scan for new files" instead of "Clear filters"; the Discovered list drops paths that get registered elsewhere (CLI, a mod). The hub also publishes a `model` event whenever a status changes on disk (checked once a minute and on every list), so the table follows files appearing or vanishing without a reload.

**Checks & deliverables — Phase 3**
- [x] On a fake `data/models/` tree that covers every rule in 3.2, the scanner finds exactly the expected entries.
  - *Checked:* `utils/tests/models/test_scan.py` (24 models from one example of every rule, plus everything that must be skipped), then all of them added through `POST /api/models` until a rescan found nothing. Also run read-only on the real model folders (45 models, 200 GB).
- [x] Verify shows live progress, and a deliberately corrupted file ends as **checksum mismatch**.
  - *Checked 2026-10-04* in the browser against a dev hub on a scratch root: a 6 GB file went "verifying 35%" → "71%" → ok in the drawer and the table; a file with one byte changed (same size, same mtime) ended as checksum mismatch, with an error alert on the Overview. Tests: `test_verify.py`, `test_cli_models.py`.
- [x] Deleting the files of a model used by a loaded fake mod is refused with `model_in_use`.
  - *Checked:* `test_used_by.py` (fake-mem with `[models] dirs`, loaded: refused; unloaded: deleted, empty folders removed) and in the browser: the delete dialog disables "Delete files too" while Speech Demo has the model loaded, and the API answers `409 model_in_use`.
- [x] Delivered: `registry.py`, the model routes, and `aihub models scan|list|verify`.
  - *As built:* the `utils/registry/` package, `utils/routes/models.py`, and `aihub models list | show | scan [--add] | verify`.
  - *Fixed along the way:* `app.py` no longer marks the hub's listening sockets inheritable. uvloop's subprocess spawn doesn't close inheritable fds, so every `--dev` child mod held the hub's port, and could keep it bound after the hub exited (regression test in `core/test_server.py`). Installed (systemd) mods were never affected.

## Phase 4 — Outputs index

- [x] **4.1 Indexer** (migration 002: an `outputs` table with `id`, `service`, `kind`, `title`, `path` UNIQUE, `is_dir`, `main`, `preview`, `size_bytes`, `created_ts`, `duration_s`, `width`, `height`, `meta` JSON and `search`; indexes on `(created_ts DESC, id)` and `(service, created_ts DESC)`).
  - **Where things are:**
    - Parse `outputs/<mod>/<date>/<entry>`, and be forgiving about files outside a date folder (use the mtime).
    - Skip `*.part`, dotfiles and sidecars.
    - Folder outputs are indexed only once `output.json` has `complete: true`.
  - **What gets recorded:**
    - Merge the sidecar.
    - Title fallback: the slug turned back into words.
    - Kind from the sidecar, else the extension.
    - A folder's main file comes from the sidecar `main`, else priority model3d > video > image > audio.
  - **Media details:**
    - Duration via the stdlib `wave` module, falling back to `ffprobe`.
    - Image size via Pillow; video size via `ffprobe`.
  - **ids** = `sha1(relative path)[:12]`.
  - *As built:* a package, `utils/outputs/`: `entries.py` (what counts as an output), `describe.py` (an output → its row), `media.py` (durations, sizes, previews), `index.py` (`Outputs`: the table, list/get/delete/files). The table also has `files` (JSON) and `sig` (sizes + mtimes, so a rescan skips unchanged outputs). Paths are relative to `outputs/`. Rules beyond the step:
    - A folder **with** `output.json` is one folder output, skipped as a whole until it says `"complete": true`. Any **other** folder (a date folder, or a mod's own subfolder such as ComfyUI's `video/`) is walked into, and each file in it is an output.
    - A sidecar is `<file>.json`, or `<stem>.json` next to a non-JSON file with that stem. A lone `.json` is a text output. Unfinished `*.tmp`, `*.crdownload` and `*.incomplete` files are skipped like `*.part`.
    - Created time: the sidecar's `created_ts` if given; inside a date folder, that date plus the name's `HHMMSS-` time (or the file's time of day); otherwise the mtime.
    - Text outputs without a prompt get `meta.excerpt` (the first 400 characters) for their card.
    - Folder files get roles: `main`, `preview`, or their subfolder's name made singular (`parts/` → `part`).
    - WAV durations use `wave`; float WAVs, other audio and video use `ffprobe`. Without ffmpeg, videos simply have no poster or duration.
    - Symlinked folders are followed, except ones that loop back up.
  - *Fixed along the way:* `Database.close()` could close a reader connection while a worker thread was mid-query (an app shutting down with a `to_thread` read in flight), which segfaults SQLite (3 crashes in 12 test runs). Each reader connection now has a lock held for the query, `close()` waits on it, and reads after close raise `database is closed` (regression test in `core/test_db.py`).
- [x] **4.2 Watcher.**
  - `watchfiles.awatch` on `outputs/`, debounced 1 s, indexing once a file's size is stable.
  - New or changed files are indexed and publish `output`; deleted ones are removed and publish `output_deleted`.
  - **On startup**, a background rescan reconciles the database with the disk, with no event per file.
  *Done when:* tests cover `.part` → rename, a folder becoming complete, deletes, and the startup reconcile.
  - *As built:* `utils/outputs/watch.py`. A change marks its folder (`<service>/<date>`, else `<service>`) for a rescan; an output is indexed once its sig has held for 1 s (a time-based check, so an extra rescan mid-write can't index a half-written file). New and changed outputs publish `output`, removed ones `output_deleted`. The startup reconcile runs in the background in chunks of 25 and ends with one `output_deleted` with id `*` if anything changed (the UI refetches on it). If watching fails, e.g. `outputs/` was removed, an `outputs-watch` error alert is raised, the folder is recreated, and everything is rescanned once watching resumes. Tests: `test_watch.py`, including fake-ok's output appearing through the hub in under 2 s.
- [x] **4.3 Previews.**
  - Images over 4 MP get a cached 640 px JPEG; videos get a poster frame at 1 s (`ffmpeg`). Both are stored as `.<name>.preview.jpg`.
  - 3D outputs use the sidecar `preview` or `preview.png`; audio has none.
  - Generated off the event loop; failures are logged and never block indexing.
  - *As built:* images up to 4 MP are their own preview. A preview is made ahead of time by a one-at-a-time background queue, or on the first request for it (at most 2 at once), and remade when its file changes. Preview URLs carry `?v=<version>` and are cacheable for a week. If a big image can't be shrunk, its original is served; a video whose poster fails gets 404, and isn't retried until the file changes. Clips shorter than 1 s use their first frame. Tests: `test_previews.py` (video tests use the host's ffmpeg via `flatpak-spawn` inside the toolbox).
- [x] **4.4 Output routes.**
  - **List:** filters for service, kind, `q`, `from` and `to`; keyset cursor on `(created_ts, id)`; totals by aggregate.
  - **Get** and **delete:** delete removes the file, sidecar and preview, or the whole folder, only inside `outputs/`, then publishes `output_deleted`.
  - **Files:** `file`, `files/{path}` (path-traversal guarded) and `preview`, all with **HTTP Range**. Check that Starlette's `FileResponse` returns 206; if not, implement it.
  *Done when:* tests cover paging, totals, Range and the traversal guard.
  - *As built:* `utils/routes/outputs.py`. `service` and `kind` take comma-separated lists; `q` matches every word against title, prompt and file name. `totals.by_kind` counts with every filter except kind, and `by_service` with every filter except service (the filter chips' counts). The cursor is `<created_ts>:<id>`; paging is stable across equal timestamps. **Delete moves the output to `outputs/.trash/<YYYY-MM-DD>/`** (your decision, 2026-10-05) with its sidecar and preview, or the whole folder; the trash is ignored by the index and purged after 30 days (at startup and every 6 h). A `<stem>.json` shared with another file stays. An output that resolves outside `outputs/` (a symlinked folder) is `409 output_not_deletable`. Starlette's `FileResponse` already answers Range with 206 (and 416 past the end). `files/{path}` only serves paths listed in that output's `files`, so traversal can't reach anything else. Tests: `test_routes.py`, `test_delete.py`.
- [x] **4.5 Activity for outputs.** Each new output adds an activity item. Batch them: more than 5 from one mod within 10 s become a single "gen3d created 8 files".
  - *As built:* `utils/outputs/announce.py`. A mod's new outputs are collected until it has been quiet for 2 s, or 10 s after the first; up to 5 become one item each (`Speech created "Good morning"`, linking to the output), more become one (`3D Generate created 8 outputs`). Changed outputs and the startup reconcile add none. Deleting adds `Moved "<title>" to the outputs trash`.

**Wire — Phase 4:** `outputs` goes live:
- the Outputs page: grid and list, filters, day groups, infinite scroll, and the detail drawer with every viewer
- Overview's recent outputs
- each service's Outputs tab
- new outputs arriving live
- *As wired:* `api.js` already routed the outputs methods and the overview's recent outputs by area, so marking `outputs` live was enough for the data. Web patch 8 (`web/PATCHES.md`):
  - the drawer plays live videos in a real `<video>` with the poster, and offers Download for files the hub serves
  - an `output` event for an output already shown replaces its card (a changed file, or a sidecar written after its file, is published again)
  - live totals and filter-chip counts follow added and deleted outputs
  - text cards fall back to `meta.excerpt`, and the delete dialog names the trash
  - the drawer's 3D and video boxes no longer collapse to 0 px when the drawer's content overflows (an export bug, in the mock too)
  - navigating to another page closes an open output drawer
  - The 3D drawer still shows the preview image; the three.js viewer arrives with gen3d in Phase 8 (8.7).

**Checks & deliverables — Phase 4**
- [x] Calling `fake-ok`'s output route makes the file appear on the Outputs page within 2 s, with no reload.
  - *Checked 2026-10-05* in the browser against a dev hub (on the host, for ffmpeg) on a scratch root: the card appeared after 1.1 s on the Outputs page and 1.07 s on Fake OK's Outputs tab, highlighted, with the counts updated and one card although the sidecar is written after the file. Test: `test_watch.py::test_a_mods_output_appears_live_through_the_hub` (hub's own watcher, default timings).
- [x] Audio seeking works (Range requests) in Chromium and Firefox.
  - *Checked in Chromium:* the drawer's player seeks a WAV (0:04 of 0:05 after clicking at 75 %), and a video plays and seeks, through `206 Partial Content`. Range itself is covered in `test_routes.py` (206, suffix ranges, 416).
  - *Checked in Firefox 157* (headless, driven over WebDriver BiDi, 7 Oct 2026): in the Outputs drawer, a 52.8 MB, 18:20 WAV played, a click at 75 % of the bar seeked to 13:45 and a click at 10 % to 1:53. Firefox fetched the file with `Range: bytes=0-`, then `Range: bytes=39583744-` for the seek, and the hub answered `206` both times; a 5 s MP4 also played and seeked.
- [x] Deleting an output from the drawer removes its file, sidecar and preview.
  - *Checked:* deleting a 6 MP PNG from the drawer moved the image, its `.json` sidecar and its `.preview.jpg` to `outputs/.trash/2026-10-05/comfy/2026-10-04/`, the page updated to 19 items without a reload, and the activity feed says `Moved "ComfyUI big 00002" to the outputs trash`. Tests: `test_delete.py`.
- [x] 2,000 generated outputs page smoothly, and the totals stay correct.
  - *Checked:* 2,000 files dropped into a running hub's `outputs/bulk/` were all indexed, with one activity item (`bulk created 2000 outputs`). Through the API, 34 pages of 60 returned 2,021 unique outputs (slowest page 7 ms). In the UI, infinite scroll loaded all 2,021 cards in 31 day groups, with "2,021 items · 4.0 MB" and the chip counts correct throughout.
- [x] Delivered: `outputs.py` (indexer, watcher, previews) and the output routes.
  - *As built:* the `utils/outputs/` package, `utils/routes/outputs.py`, and web patch 8.

## Phase 5 — Memory manager

- [x] **5.1 `utils/proc.py`.**
  - Port lcpp's `proc.py`: `meminfo`, `gpu`, `rss_bytes`, `gpu_bytes` (DRM fdinfo), `process_tree`, `port_free`, `port_owner`.
  - Add **unit pids**: `ControlGroup` from `systemctl show`, then that cgroup's `cgroup.procs`.
  - Add **container pids**: `podman inspect --format '{{.State.Pid}}'` plus its process tree.
  - *As built:* `meminfo`, `gpu`, `process_tree`, `rss_bytes`, `gpu_bytes` (each DRM client counted once, across the whole tree), `footprint(pids)`, `unit_cgroup`/`cgroup_pids`/`unit_pids` (sub-cgroups included), `units_matching(glob)` and `container_pid`. `port_free` wasn't ported: the hub's own `port_listening`/`port_owner` (Phase 2) already cover ports. Each backend gained `pids(id)`: systemd reads the unit's cgroup (its path cached while it exists), the subprocess backend returns its child. Checked live: the real meminfo and GPU, `aihub.service`'s cgroup, and a real systemd test unit's 48 MB child (`test_backends.py`). The GPU name comes from `/usr/share/hwdata/pci.ids`, which the toolbox lacks (it shows `GPU 1002:1586` there; the installed hub, on the host, gets the real name).
- [x] **5.2 Sampler** (every 2 s), producing the brief's `Memory` shape:
  - **Per mod:** its unit, plus `extra_units` (globs resolved with `systemctl --user list-units`), plus `containers`. Each process counts RSS plus GPU memory.
  - **`other_bytes`** = used − the mods' total.
  - **Peaks:** update `service_peaks` while a mod is loaded and its usage exceeds the stored peak.
  - **Events and alerts:** publish `memory` when something moves by more than 1%, or every 10 s. Raise an alert above 92%.
  - *As built:* `utils/memory/` (`source.py` collects pids and reads numbers; `manager.py` the `MemoryManager`). `extra_units` globs and `containers` are re-resolved every 10 s; an external mod with neither is measured as whoever listens on its port. `by_service` lists mods with `[memory]` or measured use. A `memory` event also goes out when a load state changes or the reserve is edited. Peaks are written when a loaded mod's use grows by 1% or more. The `memory-high` alert (warn) clears below 90%. `ServiceSummary.memory` now carries the measured `used_bytes` and the learned `peak_bytes`. The source is injectable (`Hub.memory_source`), so the tests drive it with a fake that follows real fake mods' load states.
- [x] **5.3 Planner: `plan(service, needs_bytes)`** following architecture §7, plus `GET /api/memory` and `POST /api/memory/plan`.
  *Done when:* tests with an injected fake memory source cover enough room, a covering plan, a not-enough plan, `never_unload` and busy exclusion.
  - *As built:* `utils/memory/planner.py` is a pure function (`make_plan`). Candidates must also be up and have an `unload` operation, and `auto_unload` must be on. Each frees its measured use, or its estimate if it isn't measured yet. `needs` is max(estimate, learned peak), where the estimate is the status's `memory_estimate_gb` or else the manifest's. Routes are in `utils/routes/memory.py`; `POST /api/memory/plan` takes an optional `needs_bytes`. The `needs_room` detail reads like "Loading Fake Memory 2 needs ~40.0 GB, 28.0 GB available. Unloading fake-mem makes room." Tests: `test_planner.py`, `test_make_room.py`.
- [x] **5.4 Executor.**
  - **`make_room(plan)`:** unload one mod at a time through the manifest `unload` operation, then wait until memory drops by at least 70% of what's expected (30 s timeout). Each unload adds an activity item.
  - **Routes:** `POST /api/services/{id}/load?make_room=` and `POST /api/memory/acquire`.
    - `auto_make_room = false` and no `make_room` → `409 needs_room` with `data.plan`.
    - Acquire returns `{granted: true, freed: [...]}`.
  - **One global lock**, so two loads never race for the same memory.
  *Done when:* an end-to-end test with two `fake-mem` mods passes.
  - *As built:* `MemoryManager.ensure_room()` is the one way in for loads, triggers and acquire. Under the lock it plans, unloads one mod at a time (awaiting each mod's answer, then memory dropping by 70% of the expected amount within 30 s, with a warning activity if it doesn't), re-plans, and then **reserves** the bytes the load needs. The lock isn't held while a load runs (models can take minutes to load). Instead, a reservation keeps a second load from planning with the same memory: it shrinks as the mod's measured use grows, ends a couple of samples after the load finishes, and an unload clears it. Load routes answer `409 needs_room` at once when room is needed and wasn't allowed. Otherwise they return `202` and make room in the background; if room is gone by then, the load fails with an activity item. Two loads racing for the same 48 GB never both load (tested). Acquire reservations last 120 s. Activity: "Unloaded Speech to make room for 3D Generate (1.2s)", "Made room for lcpp (gemma-4)". Tests: `test_make_room.py` (two real fake-mem mods, 40 GB each in a 68 GB budget, on a fake source).
- [x] **5.5 Proxy triggers.**
  - A proxied request that matches a mod's `[memory] triggers` while the mod is unloaded runs the load rule first.
  - `needs_room` goes back to the caller as 409, and the caller retries with the header `X-AIHub-Make-Room: 1`.
  - Mods with `in_flight > 0` are never unload candidates.
  - *As built:* `utils/memory/triggers.py`, as a `before_proxy` hook (which now also gets the request headers). Trigger paths may use `{name}` for one segment and end in `*`. The mod loads by itself once the call arrives, so the hub only makes room and reserves (for 300 s, shrinking as use grows). The mod's load state still comes from its status. `X-AIHub-Make-Room: 1` is also accepted by `POST /api/memory/acquire`, as is `?make_room=1`. Tests: `test_triggers.py`.
- [x] **5.6 Idle unload stays inside the mods.** AIHub passes `idle_unload_s` from `config.toml` to each mod through the env variable named in its manifest (`LOCALTTS_IDLE_UNLOAD_S`, `GEN3D_IDLE_UNLOAD_S`). Document the mapping in each manifest.
  - *As built:* `[memory] idle_unload_s` (the mod's default) and `idle_unload_env` (the variable it reads) in `service.toml`. Every mod with `[memory]` gets `AIHUB_IDLE_UNLOAD_S`, plus the named variable, in seconds, with **0 meaning never**. A mod's explicit `env` still wins. `config.toml` writes "never" as `idle_unload_s = 0` when the mod's default isn't never (TOML has no null), and the Settings tab's Never box saves that. Changing it on a mod with `[memory]` now says "restart required". LocalTTS and 3DGenerate read 0 as "unload at once" today, so steps 7.2 and 8.2 must make 0 mean never. Tests: `test_idle_unload.py`.

**Wire — Phase 5:** `memory` goes live:
- the header memory meter and its popover
- Overview's memory panel
- the load/unload buttons everywhere
- the **Make room** dialog, on a real `needs_room`
- *As wired:* marking `memory` live was enough for the meter, popover, Overview panel and buttons, since `api.js` already routed them by area. Web patch 9 (`web/PATCHES.md`):
  - a proxied call answered with `needs_room` opens the Make-room dialog from the API tab
  - "Unload & continue" resends it with `X-AIHub-Make-Room: 1` (`callService(…, { makeRoom: true })` in `api.js`)
  - *Fixed along the way:* the hub converted `reserve_gb` and `estimate_gb` with 1024³ while the UI (and the mock) show decimal GB, so "12 GB reserved" displayed as 12.9 GB and the hub's messages disagreed with the screen. **GB is 10⁹ bytes everywhere now**: config, manifests, status, the hub's messages, and `aihub`'s output. `GET /api/memory` returns the last sample's numbers with current load states.

**Checks & deliverables — Phase 5**
- [x] With two `fake-mem` mods sized so they can't both fit:
  - loading the second shows the Make-room plan
  - "Unload & continue" frees the first and loads the second
  - the memory meter follows within 2 s
  - *Checked 2026-10-05* in the browser against a dev hub on a scratch root. Two fake-mem mods really allocated 2 GB each, with the reserve set so ~3.3 GB was free:
    - Loading the second showed "needs ~2.0 GB; 0.9 GB is available… AIHub will unload: Big Model A, idle 11s, frees 2.2 GB" (its measured use).
    - "Unload & continue" unloaded A in 0.1 s, when the meter went from 22.7 to 20.6 GB, and loaded B in 1.8 s, when the meter was back at 22.7 GB.
    - Activity: "Unloaded Big Model A to make room for Big Model B".
    - Tests: `test_make_room.py`.
- [x] A proxied trigger call (a "speak"-style operation on a fake mod, from the API tab) goes through the same flow.
  - *Checked:* `POST /v1/load` (a trigger) from Big Model B's API tab, with A loaded, opened the Make-room dialog ("needs ~2.2 GB", the learned peak). "Unload & continue" resent it and got the mod's `200 {"loaded": true, "mb": 2048}`, with A unloaded. Tests: `test_triggers.py`.
- [x] Mods in `never_unload`, and busy mods, never appear in a plan.
  - *Checked:* `test_planner.py` (never_unload, busy, in flight, auto_unload off, not loaded, no unload operation, the target itself), and end to end in `test_make_room.py::test_never_unload_mods_stay`, `test_busy_mods_stay` and `test_triggers.py` (a request in flight).
- [x] Delivered: `proc.py`, `memory.py` (sampler, planner, executor, acquire), and proxy triggers.
  - *As built:* `utils/proc.py`, the `utils/memory/` package, `utils/routes/memory.py`, `Backend.pids()`, and web patch 9.

## Phase 6 — Metrics, dashboards and UI revision 2

> **Revision 2 was built by hand** (6.5). The original plan was to ask Claude Design for it.

- [x] **6.1 `utils/metrics.py`: the recorder** (architecture §13). *As built:* the `utils/metrics/` package (`store.py`, `recorder.py`); stats are recorded every 10 s from each mod's latest status; the low-disk alert from 6.4 is checked on each tick.
  - **Tables:** `metrics_raw`, `metrics_1m`, `metrics_1h`, `service_states`, `load_intervals`, `job_history`.
  - **Recording:**
    - the memory sampler writes `mem.*`, `gpu.*` and `mem.svc.<id>` every 10 s
    - status polls write `svc.<id>.stat.<slug>` for numeric stats, respecting `reset: daily`
    - service, job and load events fill the event tables
  - **Hourly maintenance:** roll up and prune.
  *Done when:* tests cover rollup correctness (avg, min, max), retention, and null gaps across a simulated hub downtime.
- [x] **6.2 Chart data routes** (brief §11.7). *As built:* `utils/routes/metrics.py`, `utils/routes/widgets.py`, `utils/metrics/charts.py` and `utils/widgets.py`; the details are under brief §11.7 "As built".
  - `GET /api/metrics` (range → table, an even `t` axis, `.*` families) and `GET /api/metrics/series`
  - `GET /api/timeline`
  - `GET /api/outputs/stats`
  - `GET /api/activity/stats`
  - `GET /api/jobs/stats`
  - `GET /api/widgets` and `GET /api/widgets/{service}/{id}`: proxy each mod's `[[ui.widgets]]` source, cache it for 30 s, and validate it against `WidgetData`
  - `fake-ok` gains one widget, for the tests
- [x] **6.3 Overview, system and settings routes.** *As built:* `utils/routes/overview.py`, `utils/routes/settings.py` and `utils/settings.py`; a save writes only the values that changed (one changed back to the default removes its key), and `hub.port` reports the port in use until a restart. `[ui] density` now defaults to `compact`.
  - `GET /api/overview` aggregates services, memory, the 8 newest outputs, 30 activity items, alerts, jobs and system.
  - `GET/PUT /api/settings` reads and writes `config.toml`; changing the hub port returns `restart_required`.
  - **The dashboard layout** (brief §11.5, Customize) is saved under `[ui.dashboard]` in `config.toml`, so it follows you between browsers.
- [x] **6.4 Alert rules.** *As built:* the table in architecture §6; `manifest-<id>` and `disk-low` are new. Final list: manifest errors, failed mods, registry problems, disk free under 50 GB, memory over 92%, and watcher errors.
- [x] **6.5 Part A revision 2.** *As built (2026-10-05):* built by hand in this repo at the user's request, instead of a Claude Design pass. Differences from §11 are in brief §11.11.
  - **New modules:** `web/chart-kit.js` and `charts.js` (the §11.6 components), `views.js` and `dashboard.js` (the Overview views and the charts on other pages), and `mock-history.js` (§11.9). `Hub.dc.html` gets the compact shell, the view switch, compact tiles and the §11.8 graphics.
  - **The raw-template fix (§11.2):** `utils/routes/web.py` serves a page load with an empty `<x-dc>`.
  - **Docs:** `web/PATCHES.md` now records the history; the edits table starts empty.
  - **API:** no changes to brief §6/§11.7.
  - **Tests:** `utils/tests/web/charts.test.mjs`, `mockhistory.test.mjs`, and the page-load tests in `test_web.py`.
  - *Checked in the browser:* everything below, on mock data and against a dev hub with the demo mods.
    - At 1440 × 900 in compact, the Dashboard shows alerts, the KPI strip, every service and three charts with no scrolling.
    - All four views, the service page, the memory popover, Models, the Outputs drag filter, and the Settings reserve line following the unsaved value.
    - Customize hides a widget and writes `[ui.dashboard]` to `config.toml`; Reset removes it.
    - "View as table" on every chart widget.
    - Light theme.
    - No horizontal page scroll at 360 px on any view or page.
    - With mock data, the Dashboard is fully loaded about 220 ms after switching to it.
- [x] **6.6 Contract test.** *As built:* `utils/tests/web/test_contract.py` parses `createHttpApi` in `web/api.js` (38 routes, the proxy included) and compares each brief §6.4/§11.7 interface's top-level fields with its pydantic model (`utils/api_models.py`). Parse the method → route table from `web/api.js` and assert that every route exists with the right method. Response models are pydantic classes matching brief §6.4 and §11.7, so `/api/openapi.json` documents the hub itself.
- [x] **6.7 Hub operations for the agent.** *As built:* the same test checks that every `/api/…` operation has a summary and a JSON response model (files, images and event streams declare their content type). The proxy stays out of the spec; the spec's description points to `/api/s/{id}/…` and `/operations`. Give every hub route a summary and response model, so `/api/openapi.json` is complete and Phase 13 can build tools from it.

**Wire — Phase 6:** `settings`, `metrics` and `widgets` go live, along with the `getOverview` aggregate.
- **What that shows:**
  - the Overview Dashboard, Services, Table and Timeline views with real history
  - the KPI strip and tile sparklines
  - the memory popover chart
  - the Models treemap and the Outputs histogram
  - the Settings → Memory chart, and the full Settings page
- **All of Part A is now live.** The hybrid defaults to every area live, and mock data appears only with `?mock`.

*Status (2026-10-05):* wired. `/config.js` lists `metrics`, `widgets`, `overview` and `settings` as live, and revision 2 (6.5) draws everything above from them. Every Part A area except `tools` (Phase 13) is live.

**Checks & deliverables — Phase 6** *(approved by the user 2026-10-06)*
- [x] After fake mods have run for 2 h with load/unload cycles, every dashboard widget shows real data, and a planned 10-minute hub stop shows as a **gap**. *Checked:* a 2 h soak on a scratch hub (125 load/unload cycles, 125 jobs, 42 outputs); the 10-minute stop is 9 null 60 s buckets and no timeline band crosses it. "Model storage" and "LLM traffic" need real mods, so they are checked in Phases 7 and 9.
- [x] The brief's §11.3 above-the-fold rule holds at 1440 × 900 in compact. Every chart has "View as table". Every view works at 360 px.
- [x] The §8 and §11.10 states can be reached against the live backend. States only the mock can produce (e.g. "Many outputs") are listed as mock-only in `PATCHES.md`.
- [x] The contract test passes, and `web/PATCHES.md` is empty or every entry is explained.
- [x] Delivered: `metrics.py`, the chart-data routes, the overview and settings routes, the revision 2 UI, and a fully live Part A.

---

# Stage B — Moving the apps in

**For every move (Phases 7–10)**
1. The old app is committed (Phase 0) and backed up (0.4).
2. `git subtree add --prefix=services/<id> <old repo path> <branch>` (with a clean AIHub tree).
3. Copy the app's **ignored-but-needed** files, which the subtree does not bring.
4. Create its `.venv` inside the mod folder.
5. Make the code changes and write `service.toml`.
6. Stop the old unit, then move models and databases (`mv` is an instant rename on this btrfs subvolume) and leave a symlink at each old path.
7. Cut over: `systemctl --user disable --now <old>.service`, then `aihub start <id>`, then verify.
8. Add a `MOVED.md` to the old repo pointing at `services/<id>`. Nothing is deleted until Phase 12.
9. **Part B page:** give Claude Design the brief's Part B section for this mod plus the current `web/` export. Put the result in `services/<id>/ui/`, wire it live through the proxy, and extend `mock.js` with the mod's native endpoints.
10. **Checks & deliverables** for the phase are met before the next move starts.

## Phase 7 — Move in `tts` (LocalTTS)

- [x] **7.1 Subtree + venv.** *As built:* the venv uses uv's managed Python 3.12 (in `~/.local/share/uv`), so it works on the host and in the toolbox; `aihub-install.sh` rebuilds it, and `requirements-dev.txt` adds pytest.
  - `git subtree add --prefix=services/tts ~/Projects/LocalTTS main`.
  - `uv venv --python 3.12 services/tts/.venv && uv pip install -r services/tts/requirements.txt`.
  - Ignored state: only `data/voices/` (moved in 7.4).
- [x] **7.2 Code changes in `services/tts`.** *As built:* `localtts/outputs.py` and `localtts/hub.py`; the sidecar also records `engine`, and a `save_dir` (relative only) replaces the dated folder. 20 tests in `services/tts/tests/`.
  - **`GET /v1/status`:**
    - `loaded` = any engine worker up; `busy` = any engine lock held; `idle_s`
    - stats: Voices, Engines installed, Clips today
  - **`LOCALTTS_VOICES_DIR`**, defaulting to `$LOCALTTS_DATA/voices`.
  - **`LOCALTTS_IDLE_UNLOAD_S=0` means never** (plan 5.6; today 0 unloads at once). The manifest sets `[memory] idle_unload_s = 180` and `idle_unload_env = "LOCALTTS_IDLE_UNLOAD_S"`.
  - **Output path:**
    - `{outputs}/<YYYY-MM-DD>/<HHMMSS>-<slug(text[:40])>-<voice>.<ext>`, written as `.part`, then renamed.
    - Sidecar `<file>.json`: title, `kind: audio`, prompt = text, voice, engine, model, params (instructions, speed, format), `duration_s`, `source.request_id`.
    - `save_dir` is limited to subfolders of the outputs folder. It currently accepts absolute paths and can write anywhere.
    - `/v1/outputs` listing becomes recursive.
  - **First tests for LocalTTS:** output naming, the sidecar writer, and the status route with the engines stubbed.
- [x] **7.3 `services/tts/service.toml`.** *As built:* also `LOCALTTS_DATA={service_dir}/data`, `install = "aihub-install.sh"`, and the "Clips per day" widget from 7.7.
  - **run:** `command = [".venv/bin/python", "-m", "localtts"]`, port 5040, health `/health`, status `/v1/status`.
  - **env:**
    - `LOCALTTS_HOST=127.0.0.1`, `LOCALTTS_PORT={port}`, `LOCALTTS_NO_SYSTEMD=1`
    - `LOCALTTS_OUTPUTS_DIR={outputs}`, `LOCALTTS_VOICES_DIR={models}/voices`
    - `LOCALTTS_IDLE_UNLOAD_S` (from config)
    - `LOCALTTS_BREEZE_PYTHON=~/venvs/breeze-tts/bin/python`, `LOCALTTS_KOKORO_PYTHON=~/venvs/kokoro/bin/python` (until Phase 12; now `{service_dir}/runtime/venvs/…`)
    - `BREEZE_MODEL={models}/tts/breeze-tts-2`
    - `HF_HOME={hf_home}`, `HF_HUB_OFFLINE=1`
    - `LOCALTTS_LLM_URL=http://127.0.0.1:4000/v1`
  - **memory:** `estimate_gb = 9.2`, load `POST /v1/load`, unload `POST /v1/unload`.
    - triggers: `POST /v1/speech`, `POST /v1/audio/speech`, `POST /v1/voices/design`, `POST /v1/voices` (it transcribes), `POST /v1/align`.
  - **models:** `dirs = ["tts", "voices"]`.
  - **outputs:** audio.
  - **ui:** `native = "/ui/"`.
  - **api.responses:** speech routes and voice audio → `audio`.
  - **tools:** `speak`, `list_voices`, `design_voice`, `clone_voice`, `delete_voice` (confirm).
- [x] **7.4 Move models and voices** (old service stopped). *As built (2026-10-06):* Whisper copied as `refs/` + dereferenced `snapshots/` only (no duplicate blob store); Kokoro's model and all 28 English voices downloaded into `data/models/hf-cache`; registered as `breeze-tts-2`, `kokoro-82m`, `whisper-large-v3-turbo`, `voice-arabella`, `voice-brendon`, `voice-hope`.
  - `mv ~/models/breeze-tts-2 data/models/tts/`, and leave a symlink back.
  - Fetch the rest of Kokoro's voices (only 6 of 28 are cached) into the new cache: `HF_HOME=data/models/hf-cache` with the kokoro venv's `hf download hexgrad/Kokoro-82M`.
  - `cp -rL` `models--openai--whisper-large-v3-turbo` into `data/models/hf-cache/hub/`. Copy, don't move: the old cache's shared blob store is used by other projects.
  - `mv ~/Projects/LocalTTS/data/voices data/models/voices`, and leave a symlink back.
  - Update `~/.config/tts-engines/engines.json` (`breeze.weights`, `voices_dirs`); **video-maker reads it**.
  - `aihub models scan`, then register `breeze-tts-2`, `kokoro-82m`, `whisper-large-v3-turbo` and the three voices with their sources.
- [x] **7.5 Cut over.** *As built:* Kokoro and Breeze speak through the proxy; both clips are on the Outputs page with sidecars; both engines unloaded after 180 s idle; video-maker's calls (Breeze `stream` + `no_save`, `/v1/align`, Kokoro `timings`) work on `:5040`. The memory panel first showed 30 GB: the hub summed RSS over Breeze's forked compile workers, so mod memory now counts PSS (Breeze ≈ 13 GB with its GTT; the manifest estimate is 13). `localtts` delegates start/stop/restart/logs/status to `aihub` when it runs from `services/tts`.
  - `systemctl --user disable --now localtts.service`, then `aihub start tts`.
  - **Verify:**
    - Health works through the proxy.
    - The API tab's speak call plays audio.
    - The output shows on the Outputs page with its sidecar.
    - The memory panel shows about 9 GB loaded, and the engine unloads after 180 s idle.
    - video-maker still works on `:5040`.
  - Point `~/.local/bin/localtts` at `services/tts/bin/localtts`. Its start/stop/enable subcommands now delegate to `aihub`.
- [x] **7.6** `MOVED.md` in `~/Projects/LocalTTS`.
- [x] **7.7 Speech page (Part B3).** *As built:* `services/tts/ui/page.js`, by hand (no Claude Design pass), on two new shared modules, `web/mod-kit.js` and `web/mod-charts.js`. Speak: engine switch, voice picker, direction or speed, Enhance with the added tags highlighted, format, Generate with waveform + word highlight; side charts "Clips per day" and the engine's loaded lane. Voices: cards (play, use, edit, delete), Clone, Design (sample first, then save with the same seed). Build and wire the Speak and Voices tabs and their charts: clips per day by voice, the load timeline, and the result waveform. Add a "Clips per day" `[[ui.widgets]]` entry to the tts manifest, served by a small `/v1/hub/widgets/clips` route.

**Checks & deliverables — Phase 7**
- [x] From the Speech page:
  - generate with Breeze and with Kokoro
  - clone a voice from an upload
  - design a voice from a description
  - Enhance shows its diff
  - every result is on the Outputs page with its sidecar
- [x] The memory chart shows the tts load and its 180 s idle unload, and Make room works while gen3d's fake mod is loaded. *Checked:* the load and the 180 s unload of both engines; make-room against the real gen3d is checked in Phase 8.
- [x] video-maker still works against `:5040`. `localtts.service` is disabled, and `~/Projects/LocalTTS` has its `MOVED.md`.
- [x] Delivered: `services/tts` (with its git history), its manifest and page, its models in the registry, and the voices in `data/models/voices`.

*Checked (2026-10-06):* Kokoro from the page (word highlight, waveform, the clips chart updating live), Breeze through the proxy, Design → Save from the page, Clone with Whisper auto-transcription through the proxy (the test voices were deleted), Enhance (`subtle` returns tags; `expressive` sometimes gets non-JSON back from the LLM, which the page reports), and every clip on the Outputs page with its sidecar.

## Phase 8 — Move in `gen3d` (3DGenerate)

- [x] **8.1 Subtree + venv.** *As built:* same as tts (uv-managed Python 3.12, `aihub-install.sh`). `git subtree add --prefix=services/gen3d ~/Projects/3DGenerate main`, then create the venv (Python 3.12). Move pytest and httpx into a dev requirements file. Ignored state: `data/` (the database and jobs, handled in 8.4).
- [x] **8.2 Code changes.** *As built:* `gen3d/hub.py` (status: Jobs, Queue, Avg time; jobs with progress over stages, finished ones kept for 2 min with AIHub's `cancelled` spelling); `output.json` also carries `status`, `created_ts` and `error`; an upload's folder is named after its file; `GEN3D_BLENDER` expands `~`. 35 tests (25 + 10 in `tests/test_aihub.py`).
  - **`GEN3D_IDLE_UNLOAD_S=0` means never** (plan 5.6; today 0 unloads at once). The manifest sets `[memory] idle_unload_s = 600` and `idle_unload_env = "GEN3D_IDLE_UNLOAD_S"`.
  - **Declare `POST /v1/jobs`'s request body** as a pydantic model: today it reads the raw request, so its OpenAPI has no body and the API tab shows no form (found in 2.6).
  - **New env vars:**
    - `GEN3D_DB` (default `$GEN3D_DATA/gen3d.db`)
    - `GEN3D_OUTPUTS` (default `$GEN3D_DATA/jobs`)
    - `GEN3D_WEIGHTS` (default `$GEN3D_CUBEART/weights`)
  - **Worker container** (`gen3d/worker.py`):
    - pass `GEN3D_WEIGHTS` into the container
    - add `-v {weights}:{weights}:ro`
    - replace the `data` mount with the outputs mount
    - `cube_worker.py`: `W = Path(os.environ.get("GEN3D_WEIGHTS", CUBEART / "weights"))`
  - **Job folders:**
    - The `jobs` table gets a `dir` column (relative to the outputs folder). New jobs go to `{outputs}/<YYYY-MM-DD>/<job_id>-<slug(prompt)>/`, and every file route uses `job.dir`.
    - Write `output.json` when a job finishes: title = prompt, `kind: model3d`, `main` = rigged.glb, else parts.glb, else mesh.glb, `preview: preview.png`, `complete: true`, plus prompt, seed, params (preset, budgets, stages), `source.job_id` and `peak_gpu_gb`. Failed jobs get `complete: false`, so they're not indexed.
    - This also fixes the "job.json documented but missing" debt.
  - **`scripts/migrate_jobs_to_outputs.py`:** move `data/jobs/<id>` → `outputs/gen3d/<created date>/<id>-<slug>/`, set `dir`, write `output.json`, and rewrite the absolute `source_mesh` paths in `parts/manifest.json`.
  - **`GET /v1/status`:**
    - `loaded` = worker up with models loaded; `busy` = a current job; `idle_s`
    - stats: Jobs, Queue, Avg time
    - `jobs` = queued and running jobs with progress
  - **Small debts on the way:** stop calling the private `runner._publish_job`, and add `lowpoly` to the CLI presets.
  - **Tests:** extend the existing 25 (fake worker) to cover the folder layout and `output.json`.
- [x] **8.3 `services/gen3d/service.toml`.** *As built:* also `GEN3D_BLENDER = "~/.local/bin/blender"`, retry as a memory trigger, and the "Job time per stage" widget from 8.7.
  - **run:** `.venv/bin/python -m gen3d`, port 5050.
  - **env:**
    - `GEN3D_HOST`, `GEN3D_PORT`, `GEN3D_NO_SYSTEMD=1`
    - `GEN3D_DB={databases}/gen3d.db`, `GEN3D_OUTPUTS={outputs}`, `GEN3D_WEIGHTS={models}/3d`
    - `GEN3D_CUBEART=~/Models/3D/CubeArt` (until Phase 12)
    - `GEN3D_IDLE_UNLOAD_S`
  - **memory:** `estimate_gb = 52`.
    - triggers: `POST /v1/jobs`, `POST /v1/jobs/upload`, `POST /v1/load`.
    - `containers = ["gen3d-worker-*"]`.
  - **api.responses:** job files and download → `file`; events → `stream`.
  - **tools:** `make_3d`, `job_status`, `list_jobs`, `cancel_job` (confirm), `delete_job` (confirm).
  - **ui:** `native = "/ui/"`.
- [x] **8.4 Move** (old service stopped, no jobs running). *As built (2026-10-06):* also `Qwen-Image` (CubePart reads its transformer config); registered `cube3d-v0.5`, `cubepart`, `qwen3-vl-4b-instruct`, `clip-vit-large-patch14`, `qwen-image-config`. The migration also rewrites paths into *other* jobs' folders (a parts job's `manifest.json` points at its parent's mesh); all 8 `source_mesh` paths resolve.
  - `mv ~/Models/3D/CubeArt/weights/{cube3d-v0.5,cubepart,Qwen3-VL-4B-Instruct,clip-vit-large-patch14} data/models/3d/`.
  - Replace `~/Models/3D/CubeArt/weights` with a symlink to `data/models/3d`, so CubeArt's own host scripts still work. Inside the container the real path is mounted.
  - Move `data/gen3d.db` (with `-wal`/`-shm`) to `data/databases/`.
  - Run the job migration script.
  - Register the 3D models.
- [x] **8.5 Cut over.** *As built:* the fake worker is covered by the 35 mod tests instead of a config override. A real Low-poly fox (shape → parts → rig → preview) ran through the proxy: header job chip with progress, `output.json` with `complete: true` and `main: rigged.glb`, the preview on the Outputs page, a job bar in its Timeline lane, the worker container counted as gen3d's memory (28 GB peak). Make room for gen3d plans to unload tts. `~/.local/bin/gen3d` now delegates to `aihub`.
  - `systemctl --user disable --now gen3d.service`, then `aihub start gen3d`.
  - **Verify:**
    - A fake-worker job runs (config env override `GEN3D_FAKE_WORKER=1`).
    - One real low-poly job runs end to end: header job chip, output with preview, and the make-room dialog when other mods are loaded.
  - Point `3dgenerate.desktop` at `aihub open '#/s/gen3d'`.
- [x] **8.6** `MOVED.md` in `~/Projects/3DGenerate`.
- [x] **8.7 3D Generate page (Part B4).** *As built:* `services/gen3d/ui/page.js` and the shared `web/viewer3d.js`. Create: prompt, preset, stages, part template, face budgets, seed, live ETA with a per-step bar, mesh upload; charts "Job time per stage" and "Job durations · 30 days". Jobs: live list (SSE), stage Gantt (actual vs dashed ETA), viewer with file tabs and rig sliders, parts with colours and visibility, peak GPU per stage, follow-ups (split, rig, re-split, new seed), zip download, cancel, delete.
  - Build and wire the Create and Jobs tabs, with live SSE progress and the stage Gantt.
  - Hook gen3d's three.js viewer (`gen3d/web/viewer.js`, vendored under `web/vendor/three/`) into the `Viewer3D` component interface.
  - Add a "Job time per stage" widget.

**Checks & deliverables — Phase 8**
- [x] A low-poly job run from the 3D page:
  - shows progress in the header chip and on the page
  - shows the GLB in the viewer, with rig sliders
  - appears as an output with its preview
  - shows as a job bar in its Timeline lane
  *Checked (2026-10-06):* the fox job above, queued through the proxy (the page queues the same call) and viewed on the Jobs tab: rigged GLB in the viewer, rig sliders, 4 parts with visibility toggles.
- [x] The 17 migrated jobs can be browsed on the Outputs page. *Checked:* the 14 finished ones are outputs with previews; the 3 failed or cancelled ones have `complete: false` (by design, 8.2) and are browsable on the Jobs tab.
- [x] Make room unloads tts and comfy, never lcpp. *Checked:* the plan for gen3d unloads tts; comfy and lcpp aren't mods yet, so their part is checked in Phases 10 and 11.
- [x] Delivered: `services/gen3d`, the job migration, the weights in `data/models/3d`, and the page.

## Phase 9 — Move in `relay` (DashLLM) and `opencode`

- [x] **9.1 Subtree + venvs.** *As built:* `uv sync` with uv's managed Python 3.12; the built dashboard (`web/frontend/dist`) was copied from the old repo instead of rebuilt (`aihub-install.sh` builds it when it's missing).
  - `git subtree add --prefix=services/relay ~/Tools/DashLLM main`.
  - Ignored state:
    - `.env` → `services/relay/.env`
    - recreate `web/backend/.venv` with `uv sync`
    - `npm ci && npm run build` in `web/frontend` (its own UI stays the native UI until the Part B relay page exists)
- [x] **9.2 Code.** *As built:* `app/routes/admin_hub.py`; `p50 TTFT` is `null` when no streamed request had a first token (non-streamed calls have no TTFT). 173 tests (170 + 3).
  - Add `GET /admin/status`: stats = requests today, tokens today, p50 TTFT over 24 h, healthy endpoints x/y; `loaded: null`.
  - Default the bind address to `127.0.0.1`.
  - Remove `scripts/relay`, which hardcodes `$HOME/Tools/DashLLM`.
  - Its 154 tests still run from `services/relay/web/backend`.
- [x] **9.3 `services/relay/service.toml`.** *As built:* also `OPENCODE_AUTH_FILE` pointing at the opencode mod's minted credential, and the "LLM traffic" widget from 9.7.
  - **run:**
    - `command = ["web/backend/.venv/bin/uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"]`
    - `cwd = "web/backend"`, `env_file = ".env"`
    - health `/health`, status `/admin/status`, `after = ["opencode"]`
  - **env:**
    - `RELAY_DB_PATH={databases}/relay.db`
    - `RELAY_LOG_DIR={service_dir}/web/backend/logs`
    - `RELAY_HOST=127.0.0.1`, `RELAY_PORT={port}`
  - **ui:** `native = "/"`.
  - **tools:** `relay_stats` (`GET /admin/stats/summary`), `list_endpoints`.
- [x] **9.4 `services/opencode/`, a manifest-only mod.** *As built:* `health = "tcp"`: `opencode serve` answers 401 on every route, `/global/health` included. `OPENCODE_PROJECT_DIR` was empty, which meant DashLLM's folder; `.env` now says so explicitly.
  - Copy `scripts/opencode-serve.sh` and `scripts/opencode-auth.sh` from DashLLM as `run.sh` and `auth.sh`.
  - `.env` holds the `OPENCODE_*` vars, and the generated credential goes in the mod folder.
  - Manifest: `command = ["./run.sh"]`, port 4096, `health = "tcp"`. Switch to an HTTP health route if `opencode serve` turns out to have a cheap unauthenticated one; check while doing this step.
  - `OPENCODE_PROJECT_DIR` keeps its current value.
- [x] **9.5 Move and cut over.** *As built (2026-10-06):* no requests were in flight; the relay was down for about 10 s. After the cutover: both endpoints healthy (skynet and the opencode `agent`, so the Basic credential carried over), 13 models on `/v1/models`, a chat completion through `:4000/v1`, LocalTTS Enhance, the Overview tile's stats, and the native dashboard on `:4000`. lcpp had no running instances, so its registrations are checked when Phase 10 launches one. `~/.local/bin/relay` is now `services/relay/bin/relay` (start/stop/restart/status/logs through `aihub`, for relay and opencode).
  - With relay stopped, move `relay.db` with `-wal`/`-shm` to `data/databases/`.
  - `systemctl --user disable --now relay.service opencode.service`, then `aihub start opencode relay`.
  - **Verify:**
    - the old lcpp still registers its instances
    - LocalTTS Enhance works
    - an OpenAI client still works against `:4000/v1`
    - the Overview tile shows stats
    - the native dashboard works on `:4000`
  - Point `~/.local/bin/relay` at `aihub`.
- [x] **9.6** `MOVED.md` in `~/Tools/DashLLM`.
- [x] **9.7 LLM Relay page (Part B2) and widget.** *As built:* `services/relay/ui/page.js`. Dashboard: window 1h/24h/7d/30d, six KPI tiles, live in-flight count, tokens over time, requests by model, latency (TTFT p50/p95 + tok/s), tokens by hour of day. Requests: live table (3 s), error filter, pause, rows expand. Endpoints: health, share, test/activate/enable/delete; lcpp-owned ones are read-only with a link to the Launcher; add form; requests by endpoint. Tunnels: connect/disconnect and answers to ssh prompts. Connect: base URL, models, copyable SDK/curl/env/fetch snippets. The widget is `/admin/hub/widgets/traffic` (requests, tokens and p50 TTFT per hour).
  - Build and wire the Dashboard, Requests, Endpoints, Tunnels and Connect tabs. The relay's `{dimensions, source}` datasets are converted for the chart components.
  - Add an **LLM traffic** `[[ui.widgets]]` entry (`/admin/hub/widgets/traffic`: requests and tokens per hour, plus p50 TTFT). It feeds Overview widget #8.

**Checks & deliverables — Phase 9**
- [x] The Relay page's numbers match the old dashboard for the same window. *Checked:* both read the same `/admin/stats/*` routes on the same `relay.db`; the 24 h KPIs on the page equal `/admin/stats/summary`.
- [x] The traffic widget shows on the Overview dashboard (`/api/widgets/relay/traffic`, 25 hourly points for 24 h).
- [x] lcpp registrations, LocalTTS Enhance and OpenAI clients on `:4000/v1` all still work. *Checked:* Enhance and an OpenAI-style call; lcpp registration is checked in Phase 10 with a real instance.
- [x] `relay.service` and `opencode.service` are disabled.
- [x] Delivered: `services/relay`, `services/opencode`, `relay.db` in `data/databases`, and the page and widget.

## Phase 10 — Move in `lcpp` (LLMs)

- [x] **10.1 Subtree + venv.** *As built:* uv's managed Python 3.14 (the old venv used the host's `/usr/bin/python3.14`, which the toolbox lacks).
  - `git subtree add --prefix=services/lcpp ~/Models/LLMs master`.
  - Ignored state:
    - `cp -a runtime/` (llama.cpp binaries, 146 MB)
    - `data/recent.local.json`
    - `data/generated/` is regenerated automatically
  - `uv sync` (Python 3.14).
- [x] **10.2 Code.** *As built:* `src/lcpp/aihub.py` and `daemon/routes/hub.py`. Paths outside the models folder are stored absolute (or `~/`), and a legacy `models/…` path still resolves. An unreachable hub logs a warning and the launch goes ahead; `X-AIHub-Make-Room: 1` on `POST /api/instances` (the UI's "Unload & continue") becomes `make_room=1` on the acquire. lcpp's error envelope gains `data` (the plan). 90 tests (82 + 8); six existing tests were updated for models-relative paths.
  - **`LCPP_MODELS_DIR`** (default `<LCPP_HOME>/models`) in `paths.py`:
    - catalog relative paths resolve against it
    - one-time rewrite of `data/models.json` from `models/X/…` to `X/…`
    - default `scan_dirs = [models_dir]`
    - downloads land there
  - **Downloads register in the hub:** on completion, `POST {AIHUB_URL}/api/models` with `{path, kind: "llm", name, services: ["lcpp"], source: {huggingface, repo, revision}}` and the sha256 already computed. Best effort, logged on failure.
  - **Memory acquire:** before a launch, `POST {AIHUB_URL}/api/memory/acquire` with needs = the preflight estimate.
    - A 409 fails the launch with code `needs_room` and the plan in the detail.
    - It's skipped when `AIHUB_URL` is unset, so lcpp still works standalone.
  - **`GET /api/status`:**
    - `loaded` = any instance ready; `busy` = any instance starting
    - stats: Running, Catalog, On disk
    - `jobs` = starting instances and downloads with progress
  - **Relay metadata:** `manager_url` points at `http://127.0.0.1:7000/#/s/lcpp`.
  - **Tests:** the existing 81, plus models-folder resolution and acquire against a fake hub.
- [x] **10.3 `services/lcpp/service.toml`.** *As built:* the port is passed as `--port {port}`.
  - **run:** `[".venv/bin/python", "-m", "lcpp.daemon"]`, port 7710, health `/api/health`, status `/api/status`, openapi `/api/openapi.json`.
  - **env:** `LCPP_HOME={service_dir}`, `LCPP_MODELS_DIR={models}/llm`, `LCPP_BACKEND=systemd`.
  - **memory:** `extra_units = ["lcpp-*.service"]`, and no load/unload operations, since instances are managed on lcpp's own page. It's in `never_unload`.
  - **models:** `dirs = ["llm"]`.
  - **api.responses:** log stream and chat → `stream`.
  - **tools:** `list_llms`, `list_instances`, `start_llm`, `stop_llm` (confirm).
  - **ui:** `native = "/"`.
- [x] **10.4 Move models.** *As built (2026-10-06):* no instances were running. `data/models.json` was rewritten to models-relative paths on the first load. Registered `gemma-4-26b-it` and `minicpm-5-2b` with a `local` source and a note from their GGUF metadata: no Hugging Face repo was recorded for either, so it's left for the owner to fill in. `mv ~/Models/LLMs/models/* data/models/llm/`, with a symlink at `~/Models/LLMs/models`. Running instances are unaffected: open files survive a rename, and the old path still resolves. Register both models; fill in their Hugging Face sources by hand where lcpp has no download record.
- [x] **10.5 Cut over.** *As built:* no instance was running at the cutover, so survival was checked by restarting the lcpp mod with MiniCPM running: same pid, re-adopted, still registered. A launch through the proxy went through acquire (200) and registered with the relay (`owner: lcpp`, manager link to `#/s/lcpp`); the memory panel counts the `lcpp-*` unit (6.2 GB); make room for gen3d unloads tts and never lcpp. `lcpp service …` now delegates to `aihub`. Container names in `[memory] containers` may be globs (gen3d's `gen3d-worker-*` was never matched by `podman inspect`).
  - `systemctl --user disable --now lcpp.service`. Instances keep running, because they are their own units.
  - `aihub start lcpp`. It re-adopts running instances from the unchanged `$XDG_RUNTIME_DIR/lcpp` state.
  - **Verify:**
    - instances are listed
    - relay registrations are intact
    - a new launch goes through acquire
    - the memory panel counts the `lcpp-*` units
  - `uv tool install --editable services/lcpp` to point the `lcpp` CLI at the new copy.
- [x] **10.6** `MOVED.md` in `~/Models/LLMs`. Only this folder; the rest of `~/Models` is handled in Phase 11.
- [x] **10.7 LLM Launcher page (Part B1).** *As built:* `services/lcpp/ui/page.js`, a port of lcpp's views onto `mod-kit.js`/`mod-charts.js`. Instances: cards (state, URL, memory, params, relay state; stop, restart, publish, logs with live follow, chat), a Launch form with live preflight (needs vs available, warnings) that uses `callRoom` for make-room, and the Launcher's memory over 1 h. Catalog: entries with problems and capabilities, a size treemap, discovered GGUFs to add, Hugging Face downloads with progress. Playground: streaming chat (reasoning shown above the answer), tokens/s and TTFT per reply with a chart. Relay publishing: status, test, owned registrations (unregister, remove orphans), other endpoints. Launcher settings: lcpp's own `lcpp.json` (its own tab: a page module can't add to the generic Settings tab). Router launches and per-model overrides stay in lcpp's native UI (linked in the header). Port lcpp's existing views into tabs inside the shell (Instances, Catalog, Playground, Relay publishing), and add the instance-memory chart and tokens/s per reply.

**Checks & deliverables — Phase 10**
- [x] From the Launcher page:
  - launch an instance (memory acquire shows Make room when needed)
  - chat in the Playground
  - publish it to the relay
  - stop it
  *Checked (2026-10-06):* MiniCPM 5 2B launched through the proxy with relay publishing (acquire granted; the needs_room → Make room path is covered by lcpp's tests and `callRoom`'s), chatted in the Playground (77.8 tok/s), registered on the relay with its manager link, and stopped.
- [x] Instances that were running survived the cutover without a restart. *Checked:* none were running at the cutover; restarting the lcpp mod with MiniCPM running kept its pid and re-adopted it.
- [x] A Hugging Face download lands in `data/models/llm/`, is registered with its source, and appears on the Models page. *Checked:* `unsloth/SmolLM2-135M-Instruct-GGUF` (Q4_K_M, 105 MB) → `data/models/llm/SmolLM2-135M-Instruct/`, registered as `smollm2-135m-instruct` with repo, revision and sha256, and added to lcpp's catalog.
- [x] Delivered: `services/lcpp`, the GGUFs in `data/models/llm`, and the page.

# Stage C — New capabilities

## Phase 11 — New `comfy` mod (ComfyUI)

ComfyUI workflows are **packs**: one folder per workflow, built the same way as mods. Dropping a folder in adds the workflow, editing its files changes it, and deleting the folder removes it. AIHub finds a pack's inputs by itself, checks it against what is installed, runs it, and offers it to the agent as a tool for its **task**. The guide for writing packs is `docs/workflows.md` (11.11).

**A workflow pack** is `services/comfy/workflows/<id>/`, where `<id>` matches `[a-z][a-z0-9-]{1,47}`:
```
workflow.json        the ComfyUI editor file (it opens in ComfyUI as it is)
workflow.api.json    optional: the API graph, used as given instead of converting workflow.json
workflow.toml        optional: the pack's manifest. Without it the pack is a draft.
preview.webp         optional: the card image (otherwise the newest result)
assets/              optional: extra files the graph loads (LUTs, masks); copied into ComfyUI's input folder before a run
```
```toml
name = "Z-Image Turbo"
task = "text-to-image"           # from tasks.toml; "custom" when none fits
description = "Fast photoreal text-to-image"   # becomes the tool description
memory_gb = 18                   # optional: estimated from the model files, then learned from runs
[inputs.prompt]  node = "6"  field = "text"    # or title = "Positive" instead of node
[inputs.seed]    node = "3"  field = "seed"  default = -1   # -1 = random
[inputs.width]   node = "5"  field = "width"  min = 512  max = 2048
[outputs.image]  node = "9"
[presets.portrait] width = 832  height = 1216   # named input sets shown in the Run form
[set]             "66.unet_name" = "z_image_turbo_fp8_e4m3fn.safetensors"   # fixed values (added in 11.7)
```
Types, defaults and ranges come from ComfyUI's `/object_info`, so `workflow.toml` only states what differs.

**Tasks** (`services/comfy/tasks.toml`, data rather than code) define the shared input names and what a task must have. A new task is a new table in that file.

| Task | Required inputs | Output |
|---|---|---|
| `text-to-image` | `prompt` | image |
| `image-edit` | `image`, `prompt` | image |
| `image-to-video` | `image`, `prompt` | video |
| `text-to-video` | `prompt` | video |
| `upscale` | `image` | image |
| `remove-background` | `image` | image |

Shared input names: `prompt`, `negative`, `image`, `images`, `mask`, `width`, `height`, `aspect`, `megapixels`, `seed`, `steps`, `cfg`, `strength`, `frames`, `fps`, `seconds`. The adapter derives `width`/`height` from `aspect` + `megapixels`, and `frames` from `seconds` × `fps`, when a pack exposes only the underlying inputs.

**Held-out workflows: a test of how easy importing is.** Packs are built and tuned on a **development set**. A **held-out set** is not opened during the build. Step 11.12 imports it with the code frozen and scores each workflow.

| Set | Workflows | Source |
|---|---|---|
| Development | Krea2 01–03, Wan2.1 01–02, Qwen-Image 01–04, FLUX2-Klein 01 (each with a known-good `.api.json` in `~/Models/ComfyUI-next/workflows/claude/`), Z-Image (`ZIT.json`, `ZiT-Workflow.json`) | yours |
| Held out, tier 1: same style, new models | Qwen-Image-2.1 01–03 (a GGUF loader, a switch node, `SaveImageAdvanced`, multiple reference images) | yours |
| Held out, tier 2: official templates with subgraphs | Klein-9B: text-to-image, edit base, edit distilled | ComfyUI templates |
| Held out, tier 3: community, custom nodes, video | Scail2-Wan2.1 basic + gguf (WanVideoWrapper), Z-Image Turbo V7 Basic | Civitai |
| Held out, tier 4: stress | Z-Image All-in-One v1.2 (154 nodes, 5 subgraphs), Lonecat's Krea 2 Pro 6.0.4 (474 nodes, LUT files), Krea 2 Simple, Krea2 Turbo Dual Mode (Qwen-VL, SeedVR2) | Civitai |

Tiers 1–3 are expected to run. For tier 4, the expected result is a correct conversion plus a clear list of what is missing; a run is a bonus. Only the node-type list of Qwen-Image-2.1 was looked at while this plan was written.

- [x] **11.1 Scaffold** `services/comfy` from `_template`: a FastAPI adapter on port 5070 in the package `services/comfy/comfy/`, with `data/databases/comfy.db` for runs and per-workflow statistics.
  *Done when:* `aihub check comfy` passes, and the mod is listed as stopped.
- [x] **11.2 Bring the ComfyUI control script in.**
  - Move `~/.local/bin/comfyui` to `services/comfy/bin/comfyui` and change its folders:
    - `custom_nodes` → `services/comfy/custom_nodes` (moved from `~/Models/ComfyUI-next`)
    - `user` → `services/comfy/user`
    - `input` → `services/comfy/input`
    - `--output-directory {outputs}`
  - **ComfyUI's workflows folder** (`services/comfy/user/default/workflows`) is ComfyUI's view of the packs, kept by the adapter (11.5): a symlink `<id>.json` per pack to its `workflow.json`. Any other `.json` there (a workflow saved from ComfyUI under a new name) is a draft.
    - *As built:* ComfyUI's browser lists every non-hidden file in that folder, and opening an API graph there gives an empty canvas, so it can't point at the pack folders themselves (each pack's `workflow.toml`, preview and API graph would show). ComfyUI saves by writing a temporary file and renaming it over the old one, which replaces the symlink; the adapter moves that file into the pack and puts the symlink back.
    - The curated workflows from `~/Models/ComfyUI-next/user/default/workflows` start there as drafts, except the held-out Qwen-Image-2.1; the originals are kept in `~/Models/ComfyUI-next/workflows/user-original/`.
  - Add `services/comfy/extra_model_paths.yaml` with `base_path: {models}/comfyui`.
  - The adapter tails ComfyUI's log file to stdout, so it appears in the Logs tab (journald).
  - Add a `workflows` subcommand to `bin/comfyui` that runs the Python CLI from 11.5.
  *Done when:* `bin/comfyui start` serves on 8199 from the new folders, ComfyUI's browser lists the drafts, and the adapter's log tail shows ComfyUI's log in `aihub logs comfy`.
- [x] **11.3 Move models.**
  - `mv ~/Models/ComfyUI/models/* data/models/comfyui/` (114 GB, an instant rename), with a symlink at the old path for the legacy container.
  - Move `download_qwen_image_2.1.sh` into `services/comfy/scripts/`.
  - Register the models, and check the image/video classification by eye.
  *Done when:* `aihub models scan` shows no unregistered files under `comfyui/`, and ComfyUI's loaders list the same files as before.
  - *As built:* 27 files (123 GB) moved and registered; `[models] dirs = ["comfyui"]` in the manifest; Hugging Face sources set for the Qwen-Image-2.1 files (from the download script, whose target is now `$COMFY_MODELS`); SAM 3.1 marked `other`. The legacy `strix-halo-image-video` container no longer exists. **The Krea2, FLUX2-Klein and Qwen-Image-Edit-2511 model files were already gone before the move** (an `/object_info` snapshot from 2026-08-26 lists them; nothing on disk has them now), so those development workflows convert and check but can't run until re-downloaded.
- [x] **11.4 Adapter: control and status.**
  - **`/health`** (the adapter itself).
  - **`/v1/status`:**
    - `loaded` = ComfyUI answers `/system_stats`; `busy` = its queue is running
    - `jobs` from the queue, with progress
    - stats: Workflows (ready), Drafts, Queue
  - **`/v1/load`:** `bin/comfyui start`, then wait until it's ready. **`/v1/unload`:** ComfyUI's `POST /free {"unload_models": true, "free_memory": true}`. **`/v1/shutdown`:** stop the container.
  - **The node catalog** (`comfy/nodes.py`): fetch `/object_info` at every load and cache it in `services/comfy/data/object_info.json`, so packs can be checked while ComfyUI is down. It answers which node types exist, their inputs in order, their types and ranges, which nodes are output nodes, and the files each loader can see.
  - **Manifest:** `containers = ["strix-halo-comfyui"]`, `estimate_gb = 24`, `ui.native = "http://127.0.0.1:8199/"`.
  *Done when:* load, unload and status work against the live ComfyUI (`services/comfy/tests/test_control.py`, using a fake ComfyUI for CI), and the memory chart shows the drop on unload.
  - *As built:* `loaded` means the ComfyUI process is up. **Unload** calls `/free` and then stops the process (`comfyui quit`, new), so all of its memory comes back (1.8 GB idle, much more after a run); the toolbox stays up and the next load takes ~15 s. The adapter adopts a ComfyUI that's already running, unloads itself after `COMFY_IDLE_UNLOAD_S` (600) idle, and stops an idle ComfyUI when the adapter stops (`COMFY_QUIT_ON_EXIT`). `comfy/client.py` (ComfyUI's HTTP API), `comfy/control.py` (the controller and its poller, `/v1/load|unload|shutdown`), `comfy/nodes.py` (`NodeCatalog`). **Hub change:** `proc.container_members` counts a container's whole `libpod-*` cgroup, because `podman exec` processes aren't children of the container's main pid (before this, comfy read 77 MB with ComfyUI running).
- [x] **11.5 Workflow packs: load, convert, check** (`comfy/packs.py`, `comfy/convert.py`, `comfy/check.py`, `comfy/cli.py`).
  - **Loading:** scan `workflows/*/`, parse `workflow.toml` (unknown keys are errors, as in `service.toml`), and watch file modification times, so edits apply without a restart. A pack folder without `workflow.toml` is a draft, as is any loose `.json` in ComfyUI's workflows folder. A broken pack is listed with its errors and never stops the adapter.
  - **ComfyUI's view** (`sync_comfy_view()`, on every scan): create the `<id>.json` symlinks, remove ones whose pack is gone (only symlinks into `workflows/`, never regular files), and move a regular file that replaced a pack's symlink (a save from ComfyUI) into that pack as `workflow.json`.
  - **Editor → API conversion,** using the node catalog. It handles:
    - widget values in input order, including the extra `control_after_generate` value after seed inputs
    - widgets turned into inputs, and links
    - Reroute, PrimitiveNode, Note and MarkdownNote
    - muted nodes (dropped) and bypassed nodes (passed through by matching type)
    - KJNodes Set/Get, and subgraphs flattened into the graph
    Anything else fails with a `ConvertError` naming the node, its type and the reason. `workflow.api.json` skips the conversion.
  - **Check** (`check(pack) → [Issue]`), where each issue is `{level, code, node?, detail, fix?}`:
    - node types that aren't installed, named with the custom-node package when the graph records it (`cnr_id`)
    - model files that aren't present: a loader's value that isn't in its file list, with the download URL when the node records one (`properties.models`) and the registry entry when one matches
    - inputs that no longer point at a node or field
    - task inputs that are missing
  - **CLI:** `comfyui workflows list | show <id> | check <id>… | --all | new <id> --from <file> | copy <id> <new-id> | run <id> key=value…`.
  - Tests use the development set as fixtures (`services/comfy/tests/fixtures/workflows/`) and a node-catalog snapshot (`fixtures/object_info.json`, trimmed to the node types the fixtures use).
  *Done when:* every development workflow converts to its known-good `.api.json` (the same nodes, inputs and links, ignoring node order), a pack with a missing node or model reports exactly that, and editing a `workflow.toml` shows up in `/v1/workflows` within 2 s without a restart.
  - *As built:* the known-good graphs are **ComfyUI's own** (`app.graphToPrompt()` run in the browser on each development workflow, saved as `tests/fixtures/workflows/<name>.api.json`), not the older hand exports: those got a bypassed LoRA wrong and lacked inputs ComfyUI has added since. All 12 match (ignoring `filename_prefix`, which the frontend date-fills). Lessons built in: inputs added to a node after a workflow was saved take their defaults; dynamic combos (`COMFY_DYNAMICCOMBO_V3`, 161 node types, e.g. SaveVideo's `format`) bring sub-inputs named `parent.child`; control and upload values are recognised by value; subgraph values follow `properties.proxyWidgets` (`"-1"` = a subgraph input). Untitled nodes are matched by display name. Files: `comfy/convert.py`, `packs.py` (`Manifest`, `Packs`, `sync_comfy_view`), `check.py` (`Issue`; missing models name their `models/` folder and any URL the editor recorded), `schema.py`, `library.py` (cached analysis; the registry's file names from AIHub), `tasks.py` + `tasks.toml`, `api_workflows.py` (`/v1/workflows`, `/{id}`, `/{id}/check`, `/{id}/preview`, `/v1/tasks`), `cli.py`. Loose drafts get ids from their folder and file name (`krea2-01-krea2-turbo-txt2img`).
- [x] **11.6 Auto-detecting inputs** (`comfy/detect.py`): this drafts `workflow.toml` for a draft pack and fills `/v1/workflows/{id}/suggest`.
  - **Prompts:** trace text-encode nodes to the sampler's `positive` and `negative` inputs to tell `prompt` from `negative`.
  - **Sampler settings:** seed (including `RandomNoise.noise_seed`), steps and cfg on KSampler and SamplerCustom-style nodes.
  - **Size:** width and height on empty-latent nodes, and resolution nodes.
  - **Images:** `LoadImage` nodes become `image`, `image_2`, …; a mask input becomes `mask`.
  - **Video:** frame count and fps.
  - **Outputs:** every output node, with its kind (image, video, audio, mesh).
  - **The task** is guessed from the inputs and outputs it found. The guess is shown, never applied silently.
  - **Memory:** the sizes of the model files the graph loads × 1.2, until a run has measured it (11.7).
  *Done when:* for every development workflow, the suggestion matches a hand-written `expected.toml` fixture, and the score (right, wrong, missed) is printed by `pytest -k detect`.
  - *As built:* `comfy/detect.py` (`suggest`, `to_toml` with a comment naming each input's node, `memory_estimate`), `GET /v1/workflows/{id}/suggest`, and `comfyui workflows suggest <id> [--write]` / `new … --accept`. Expectations are `tests/fixtures/expected/<name>.toml` with `want` (must be found), `maybe` (either way) and `missed` (a person would want it; recorded, not failed); `tests/scoring.py` is shared with 11.12. **Score on the development set: 46 right, 0 wrong, 0 extra, 5 missed** (the inpaint workflow's mask box, 4 fields of a `CreateShapeMask`; Z-Image's LoRA strength). Rules learned on the way: a sampler is a node taking both a model and `positive` (so `WanImageToVideo` isn't one); a guider's seed and steps are on the SamplerCustom node that uses it; `strength` only when the saved denoise is below 1; the name comes from the notes' first top-level heading. Several image inputs are `image`, `image_2`, … rather than one `images` list. Nothing is written until asked: a suggestion is shown, and `--write` / PUT (11.8) saves it.
- [x] **11.7 Running** (`comfy/run.py`).
  - **Routes:**
    - `GET /v1/workflows` and `GET /v1/workflows/{id}`: each with its JSON Schema, task, check issues and presets
    - `POST /v1/run {workflow, inputs, preset?}`: returns `{job_id}`
    - `GET /v1/jobs/{id}`, with `?wait=<s>`, which waits up to that long and then returns the outputs
    - `/v1/queue`, and `/v1/queue/{id}/cancel` (`/interrupt` plus deleting it from the queue)
    - `GET/PUT /v1/defaults`: the default pack per task, stored in `comfy.db`
  - **A run, in order:**
    1. Check the pack; refuse with its issues.
    2. Resolve the inputs: preset, then defaults, then the caller's values. Make a random seed for -1. Derive `aspect` and `seconds`.
    3. Acquire memory (`memory_gb`). A `needs_room` answer is relayed so `callRoom` works.
    4. Upload input images (`/upload/image`), plus anything in `assets/`.
    5. Patch the graph: the inputs, plus `filename_prefix` on every output node set to `<YYYY-MM-DD>/<HHMMSS>-<slug>`, so files land in dated folders.
    6. `POST /prompt`, then follow progress on ComfyUI's websocket.
    7. Write a sidecar next to each result: the workflow id, resolved inputs, seed and run time.
    8. Record the run and its peak memory in `comfy.db`, read from the hub's memory API. The peak replaces the estimate in `memory_gb` when no value is given.
  *Done when:* a fake-ComfyUI test covers the patching, the dated prefix, the sidecar, cancel and `needs_room`, and a live Z-Image run from `curl` lands in `outputs/comfy/<date>/` with its sidecar.
  - *As built:* `comfy/resolve.py` (defaults < preset < caller, validation, random seeds below 2³², aspect + megapixels → width/height in multiples of 16, seconds → frames kept 4k+1 when the graph's own count is, `patch`), `comfy/run.py` (`Runner`: acquire, start ComfyUI if needed, assets, queue, websocket progress, history reconcile after gaps or restarts, sidecars, peak memory from AIHub's `/api/services/comfy`), `comfy/api_run.py` (`/v1/run`, `/v1/jobs[/{id}?wait=]`, `/v1/queue`, `/v1/queue/{id}/cancel`, `/v1/defaults`, `/v1/uploads`, `/v1/files/{path}`). File inputs take `output:<id>` (fetched from AIHub into `input/aihub/`), `upload:<name>` or a file already in ComfyUI's input folder. Memory to acquire: `memory_gb` if the pack sets it, else the last 10 runs' peak + 5%, else the model files × 1.2 (the suggested `workflow.toml` writes the estimate as a comment so it doesn't pin it). **Added:** `[set]` in `workflow.toml` (`"66.unet_name" = …`): fixed field values applied before every check and run, for adjusting a workflow without opening ComfyUI. Status gains a "Made today" stat and the runs as jobs. **Live:** the first pack, `zimage-turbo` (from `ZIT.json`, with `[set]` pointing at the fp8 model you have), ran from `curl` through the hub in 40 s including ComfyUI's start; the image and its sidecar are in `outputs/comfy/2026-10-06/` and on the Outputs page; peak 35 GB.
- [x] **11.8 Importing** (`comfy/importer.py`).
  - **`POST /v1/import`** takes a file:
    - an editor JSON or an API JSON
    - a PNG, WebP or MP4 with ComfyUI metadata: `prompt` is the exact API graph, `workflow` is the editor file
    - a zip that contains one of those, plus any extra files, which go in `assets/`
  - **`GET /v1/import/history`** lists ComfyUI's recent runs. Importing one takes its exact API graph, and its editor file when ComfyUI stored one.
  - **Every import:**
    1. Create `workflows/<id>/`, with the id from the file name.
    2. Run the check (11.5) and the detection (11.6).
    3. Return `{id, issues, suggestion}`.
    The pack stays a draft until `PUT /v1/workflows/{id}` saves its `workflow.toml`.
  - **Missing pieces:**
    - Missing model files with a known source are offered as downloads through the hub's model downloads, each needing a confirm in the UI.
    - Missing custom nodes are only reported, with the package name: installing one runs third-party code, so you install it with ComfyUI-Manager.
  *Done when:* each import source has a test that produces a draft with the expected issues, and an MP4 or PNG from `outputs/comfy` re-imports to the same API graph.
  - *As built:* `comfy/importer.py` (PNG tEXt/iTXt, WebP EXIF `prompt:`/`workflow:` tags, video container tags via ffprobe, zips with the top folder stripped and other files kept as `assets/`), `comfy/api_import.py` (`POST /v1/import` with an optional `id`, `GET /v1/import/history`, `POST /v1/import/history/{prompt_id}`, `PUT /v1/workflows/{id}` with `toml` (saved as written, comments kept) or `manifest` (written as TOML), `DELETE /v1/workflows/{id}` (moved to `workflows/.trash/`), `POST/GET /v1/downloads`), `comfy/downloads.py` (https only, into `data/models/comfyui/<folder>/` via `.part`, then registered in AIHub with a Hugging Face or URL source). An imported API graph is kept as `workflow.api.json` only when there's no editor file or it doesn't convert, since an API graph would otherwise hide later edits made in ComfyUI. Live: the fox PNG from 11.7 re-imported to its exact graph with the suggested inputs.
- [x] **11.9 Bring in the development set and cut over.**
  - Turn the development drafts (and Krea2 03 and the two Z-Image files) into packs with `comfyui workflows new`, review their `workflow.toml`, and set the default pack per task.
  - Point `~/.local/bin/comfyui` at the mod's script.
  - **Verify:**
    - an image run appears on the Outputs page with its prompt
    - a Wan 2.1 image-to-video run works
    - the make-room flow works against gen3d
  *Done when:* `comfyui workflows check --all` is clean for the development set, and the three checks pass.
  - *As built:* 12 packs made with `comfyui workflows new <id> --from <draft> --accept`: `zimage-turbo`, `zimage-intorealism`, `wan21-t2v` and `wan21-i2v` are ready; the 8 Krea2 / FLUX2-Klein / Qwen-Image-Edit packs are broken only because their model files were deleted before this phase (11.3), and `check` names each missing file, its folder and, where the workflow recorded one, its download URL. Hand edits after the suggestion: names and descriptions, presets (`portrait`, `landscape`, `short`), and a `lora_strength` input on `zimage-intorealism` (the detector's known miss). Defaults: text-to-image → `zimage-turbo`, image-to-video → `wan21-i2v`, text-to-video → `wan21-t2v`; image-edit has no ready pack. `~/.local/bin/comfyui` links to the mod's script (the old one is backed up in `~/Backups/aihub-premigration-2026-10-04/`). ComfyUI-next's 40 old outputs moved into `outputs/comfy/<date>/` with sidecars whose prompts come from each PNG's embedded graph (`scripts/migrate_old_outputs.py`); `MOVED.md` in `~/Models/ComfyUI` and `~/Models/ComfyUI-next`. **Verified:** the Z-Image run (11.7); Wan 2.1 image-to-video from that image (`output:<id>`, preset `short`, 33 frames at 512×640, 354 s, peak 60 GB); make-room: a run needing 55 GB with gen3d loaded got 409 `needs_room` with the plan "unload gen3d", and with `X-AIHub-Make-Room` gen3d was unloaded and the run finished. **Found on the way:** gen3d's idle unloader stopped its worker in the middle of a load after a long idle spell (fixed: activity is marked before the worker starts, with a test); a comfy test could run the real `bin/comfyui quit` at shutdown (fixed, and a guard fails any test that tries).
- [x] **11.10 Tools for the agent.**
  - **`GET /v1/tools`** in the comfy mod returns OpenAI-style functions:
    - one per task that has a ready pack: `generate_image`, `edit_image`, `animate_image`, `generate_video`, `upscale_image`, `remove_background`
      - each takes the task's shared inputs plus an optional `workflow` (an enum of the packs for that task)
      - its description lists those packs' descriptions
    - `list_workflows`, and `run_workflow {workflow, inputs}` for any pack
  - **Hub: tools listed by a mod at runtime.** Add to the manifest (`utils/manifest.py`, architecture §4.3) `[agent] tools_source = "GET /v1/tools"`. Add `job = true` on `ToolSpec` for tools that return a job id. Phase 13 reads both.
  - A task tool called without `workflow` uses the task's default pack (11.7), else its only ready pack.
  *Done when:* `/v1/tools` changes when a pack is added or removed, without a restart, and the manifest test covers `[agent]` and `job`.
  - *As built:* `comfy/tools.py` and `POST /v1/tools/{name}/call {arguments}` (in `api_run.py`). Each function carries `op` (its call route) and `job` (`{status: "GET /v1/jobs/{job_id}?wait=60", cancel: …}`, or null for `list_workflows`). Task tools take the task's shared inputs that its ready packs have, plus `workflow`; a call without `workflow` uses the task's default, else its only pack, else asks for a choice; arguments a pack doesn't take come back as `ignored`. Live: `generate_image` (zimage-turbo [default], zimage-intorealism), `animate_image`, `generate_video`, `list_workflows`, `run_workflow`. The manifest also lists `[tools]` for `GET /v1/workflows`, `POST /v1/run` (`job = true`), `GET /v1/jobs/{job_id}` and cancel (`confirm = true`). Hub: `ToolSpec.job`, `AgentSpec.tools_source` (`utils/manifest.py`), and `aihub check` checks the `tools_source` operation exists.
- [x] **11.11 Images & Video page (Part B5)**, as `services/comfy/ui/page.js`, plus the docs.
  - **Workflows tab:** cards grouped by task, each with its preview, check state and a default star. Drafts (including workflows saved from ComfyUI) carry a "Review" badge.
  - **Run:**
    - a `SchemaForm` built from the pack's schema, with preset chips
    - queue progress
    - results, with each result's sidecar and a "Use as input" action
  - **Import:** drop a file, or pick from ComfyUI history. A **review screen** shows:
    - the detected inputs (rename, hide, expose another node's field, set a range), the task and the issues with their fixes
    - "Open in ComfyUI"
    Saving writes `workflow.toml`.
  - **Charts:** runs per workflow, and time per run. An "Images per day" dashboard widget.
  - **Mock:** a comfy mock in `web/mock-mods.js`.
  - **Docs:**
    - `docs/workflows.md`, the pack guide: the folder, `workflow.toml`, tasks, presets, the CLI, editing in ComfyUI and saving back, common check issues and their fixes
    - a `comfy-workflow` skill that follows the guide
  *Done when:* the page works live and under `?mock` (import → review → run → result), and the guide is linked from `docs/mods.md`.
  - *As built:* `services/comfy/ui/page.js` (Workflows: cards by task with state, problems, the ★ default per task, and an "Images & videos per day" chart), `ui/run.js` (Run: workflow picker, presets, the form, the queue with live progress, results with "Use as input" and "Run again", "Time per run" and "Runs per workflow" charts), `ui/import.js` (Import: drop a file, ComfyUI's history, drafts; the review screen with detected inputs to keep, rename or add from any node's field, the task, problems with Download buttons, "Edit as TOML", Remove). New shared module `web/mod-form.js` (`schemaForm`: a form from a JSON Schema with file inputs that upload or pick a recent output), for any mod. Adapter additions: `/v1/hub/widgets/made` (the dashboard widget), `/v1/stats`, card previews from the newest image or a video frame (`data/previews/`), result paths accepted as file inputs. Mock: `web/mock-comfy.js` (comfy is a ready, unloaded process mod with its page under `?mock`; `Hub.dc.html` `pageUrl` patch row 1). Guide `docs/workflows.md`, skill `.claude/skills/comfy-workflow/`. **Hub fix:** `aihub check` counted routes hidden from the API tab (`[api] hide`) as missing, so gen3d's widget failed too. Verified live: a Z-Image IntoRealism run from the page (form → ComfyUI started → progress → result, 35 s); the review screen on `krea2-txt2img` lists its three missing models with their folders.
- [x] **11.12 Transfer test with the held-out workflows.**
  1. **Freeze:** tag the commit `comfy-transfer-freeze`.
  2. **Import every held-out workflow,** from its original file, through the page or the CLI, following only `docs/workflows.md`.
  3. **Get the ground truth:** load the editor file in ComfyUI through the browser pane, and call `app.graphToPrompt()` to get ComfyUI's own API graph without running anything.
  4. **Score each workflow** in `docs/comfy-transfer-report.md`. For each one record:
     - **Converts:** whether it equals ComfyUI's own graph
     - **Issues:** whether the reported missing nodes and models are right and complete
     - **Inputs:** right, wrong or missed, against what a person would expose
     - **Edits:** the lines of `workflow.toml` changed by hand
     - **Runs:** yes or no, with the time
     - **Code changes needed**
  5. **Fix** what the scores show in separate commits (`AIHub (11.12): …`), then re-score.
  6. **Report** the before and after scores side by side.
  7. **Keep the regression fixtures:**
     - your own workflows and the official templates go into `services/comfy/tests/fixtures/holdout/` with their ground truth
     - the Civitai workflows are read from where they are, and their tests are skipped when the files are missing, so third-party files aren't committed
  *Done when:* the report has both score tables, tiers 1–3 convert exactly and run, and every tier 4 workflow either converts or names the exact node it can't handle.
  - *As built:* see [comfy-transfer-report.md](comfy-transfer-report.md). Ground truth came from ComfyUI's own editor for 12 of 13 (it can't convert Lonecat's Krea 2 Pro itself). Over tiers 1–3: exact conversions 2 → 8 of 9 (the ninth differs only in a display value), inputs 24 right / 2 wrong / 9 missed / 3 extra → 30 / 0 / 3 / 0 (the 3 misses sit on uninstalled custom nodes), tasks and outputs 8 → 9 of 9. Fixes in three commits: converter (`189faed`: subgraph inputs by name, ComfyUI's id renumbering, string ids, bypass rules, per-format and rgthree widgets, editor-only helpers, `editor_links`), detection (`53342b3`: linked text never mapped, size traced from the latent, dead and caption-only images, remove-background, preview outputs, the `video` input, mapped `aspect`), import (`f120d4d`: CLI relative paths and media/zip files, one draft per workflow in a zip). "Tiers 1–3 run" is met where their files exist: the three Qwen-Image-2.1 packs ran (tier 1); Klein (3 model files, download URLs recorded in the templates), SCAIL 2 basic (2 model files), SCAIL 2 gguf (custom node `KikoPurgeVRAM`) and Z-Image V7 (Impact Pack, easy-use, Image Saver) are blocked only on downloads or installs that need your go-ahead, and the check names each one. `tests/transfer.py` scores any version of the code (`COMFY_CODE=`), `tests/test_holdout.py` keeps the six committed ones (yours and the official templates) as regression tests and reads the seven third-party ones from where they are; their packs stay out of git (`workflows/.gitignore`).

**Wire — Phase 11:** the Images & Video page, the "Images per day" widget, comfy's jobs in the Activity panel, and its results on the Outputs page.

**Checks & deliverables — Phase 11**
- [x] Z-Image and Wan 2.1 both run from the page. Results land in `outputs/comfy/<date>/` with sidecars and appear live. *(Z-Image IntoRealism, 35 s; Wan 2.1 text-to-video with the `short` preset, 33 frames at 832×480, 507 s, peak 68 GB; both on the Outputs page with their prompts.)*
- [x] Adding a pack folder, editing its `workflow.toml` and deleting it each show up on the page without a restart.
- [x] A workflow saved from ComfyUI under a new name appears as a draft, and the review screen turns it into a working pack. Saving a pack's workflow in ComfyUI updates the pack. *(Checked through ComfyUI's own save endpoint: "My Night Shots" became the draft `my-night-shots`; a save of `zimage-turbo.json` replaced the symlink and the edit landed in the pack.)*
- [x] Unloading comfy (ComfyUI's `/free`) shows the memory drop on the chart.
- [x] `aihub doctor` finds the ComfyUI models only in `data/models/comfyui/`, plus the legacy symlink. *(Doctor's model checks arrive in 12.4; checked by hand: `aihub models scan` finds nothing unregistered, `~/Models/ComfyUI/models` is the symlink, and no model file is left in the old folders.)*
- [x] `docs/comfy-transfer-report.md` shows the held-out scores before and after fixes.
- [x] Delivered:
  - `services/comfy`: the adapter, control script, packs, `tasks.toml`, converter, checker, detector, importer, CLI, tools route and page
  - the ComfyUI models moved
  - `docs/workflows.md` and the `comfy-workflow` skill
  - the transfer report

## Phase 12 — Runtimes moved inside the mods

- [x] **12.1 Speech engines inside the mod.** *As built (2026-10-06):* the engine installers already took `--prefix`/`--src`, so `engines/` (video-maker's synced copy) is unchanged. `services/tts/scripts/install-runtime.sh` builds `runtime/venvs/{kokoro,breeze-tts}` from `locks/*.txt` (the old venvs' exact packages, frozen so a newer ROCm nightly can't change torch), then runs both installers, which rewrote `engines.json` and the `kokoro-tts`/`breeze-tts` launchers and passed their smoke tests. The Breeze source (pinned commit + patch) was copied to `runtime/breeze-tts`. Kokoro, Breeze and `/v1/align` verified through the hub. With approval, `~/venvs/breeze-tts` and `~/venvs/kokoro` were deleted; the user chose to keep `~/venvs/breeze-next`, `~/venvs/breeze` (an early Breeze experiment) and `~/.local/share/tts-engines/breeze-tts`. video-maker no longer picks a TTS on its own: `engine/scripts/tts-location.mjs` records where the user says TTS lives (`~/.config/video-maker/tts.json`; AIHub's speech mod is `http://127.0.0.1:7000/api/s/tts`), and `voiceover.mjs` stops until it is set; Kokoro and Breeze narration verified through the hub.
  - Recreate the Breeze and Kokoro venvs in `services/tts/runtime/venvs/` with LocalTTS's engine installer (add a `--prefix` option if it has none), and the Breeze source in `services/tts/runtime/breeze-tts`. Update the manifest and verify both engines.
  - **Ask before deleting** `~/venvs/breeze-tts` and `~/venvs/kokoro` (13.5 GB). video-maker's `kokoro-tts`/`breeze-tts` commands use them, so update `engines.json` and those wrappers first.
  - **Ask before deleting** the orphan `~/venvs/breeze-next` (7 GB).
- [x] **12.2 CubeArt inside the mod.** *As built (2026-10-06):* `cube/`, `.cache/`, CubeArt's scripts, logs and outputs moved to `services/gen3d/runtime/CubeArt` (with a `weights` link to `data/models/3d`; `cube-run` now mounts the weights' real path); the venv was rebuilt inside the ROCm image by `services/gen3d/scripts/install-runtime.sh` from `locks/cubeart.txt` (the old venv's exact packages, layered on the image's torch). `GEN3D_CUBEART={service_dir}/runtime/CubeArt`, `~/.local/bin/cubeart` points there. A real Low-poly job (shape 80 s → parts 128 s → preview) ran through the hub. The old venv is still at `~/Models/3D/CubeArt/.venv` (deletion waits for approval in 12.3). Move CubeArt (code clone and caches) to `services/gen3d/runtime/CubeArt`, and recreate its venv inside the container following CubeArt's README. Set `GEN3D_CUBEART={service_dir}/runtime/CubeArt`, then verify a real job.
- [x] **12.3 Remove the transition symlinks** *As built (2026-10-06), with approval:* removed `~/models/breeze-tts-2`, `~/Models/LLMs/models`, `~/Models/ComfyUI-next/{custom_nodes,input,user}`, `~/Projects/LocalTTS/data/voices` and the legacy ComfyUI's `~/Models/ComfyUI/models` (each folder's `MOVED.md` notes it); deleted the old CubeArt venv (`~/Models/3D/CubeArt` now holds only `MOVED.md`) and the disabled pre-AIHub units `{gen3d,lcpp,localtts,relay}.service`. Kept by choice: every old repo, `~/venvs/{breeze,breeze-next}`, and the disabled `opencode.service` (not asked about). The `~/.local/bin` commands stay (allowlist). video-maker and the desktop launcher already used the new paths (12.1). All mods pass `aihub check` (relay's null TTFT stat fixed on the way). once every dependent is updated: video-maker (`engines.json`, voices), the desktop launcher, `~/.local/bin` wrappers, and the legacy ComfyUI fallback (ask). Old repos keep their `MOVED.md`; deleting them needs explicit approval.
- [x] **12.4 `aihub doctor` checks.** *As built:* the checks run in the hub (`utils/doctor.py`, `GET /api/doctor`) so the CLI and the UI share them; `aihub doctor [-v] [--json]` adds its local checks (venv, config, unit, linger, hub up) and exits 1 on any problem. Stage D notes: the journal logs, and any `$XDG_RUNTIME_DIR/<mod id>` (lcpp). On this machine: 21 ok, the two notes, and one warning: opencode's `OPENCODE_PROJECT_DIR` (its `.env`) points at the old `~/Tools/DashLLM`.
  - Every registry file exists and every manifest is valid.
  - No mod's resolved command or env points outside the project root, except the allowlist: `/usr`, `~/.config/tts-engines`, podman images, and `~/.local/bin` tools.
  - Every port is free or owned by its mod, every unit is healthy, and there's enough disk.
  - Mods running with `HF_HUB_OFFLINE` have every file they need.
- [x] **12.5 `aihub backup`.** *As built:* `aihub backup <folder>` (`utils/cli_backup.py`, standard library) writes `aihub-backup-<date>-<time>.tar.gz`, owner-only (0600: it holds the `.env` secrets), with a `backup.json` listing; each database is copied with SQLite's online backup, integrity-checked and stored as one file. Live run: 4 databases, the registry, config and 2 `.env` files, 12.6 MB. An online SQLite backup of `data/databases/*.db`, plus `registry.json`, `config.toml` and `services/*/.env`, packed into a dated archive in a folder the user chooses.

**Wire — Phase 12:** Settings → About gets a **Doctor** panel that shows `aihub doctor`'s results (`GET /api/doctor`). *Done (12.4; `web/PATCHES.md` row 6), checked live and in `?mock`.*

**Checks & deliverables — Phase 12**
- [x] Both speech engines and a real 3D job work from the runtimes inside the mod folders.
- [ ] `aihub doctor` reports nothing outside the allowlist, apart from the Stage D items (logs and lcpp's runtime state). *Open:* opencode's `OPENCODE_PROJECT_DIR` (the folder the agent works in, set in its `.env`) is `~/Tools/DashLLM`; the user decides where it should point.
- [x] The old venvs are deleted only after you approve it.
- [x] Delivered: runtimes in `services/*/runtime/`, the transition symlinks removed, `aihub doctor` and `aihub backup`.

## Phase 13 — Agent-ready API

The hub becomes one tool catalog with risk levels, approvals the hub enforces, editable parameter cards, and model facts (context window, tools, vision). Everything the chat agent (Phase 14) and outside clients (Claude Code over MCP) need. Research behind the design: [agent-architecture.md](agent-architecture.md).

- [x] **13.1 Tool catalog with metadata: `utils/tools/catalog.py`, `GET /api/tools`.** *As built:* a package `utils/tools/` (catalog, schema, hub_tools, approvals, calls, results, api). Beyond the plan: `hide`/`fixed` per tool (tts keeps `stream`, `timings` and `save_dir` from the model), `job_status`/`job_cancel` ops for `job = true`, a stopped mod's tools kept in `kv` (`available: false`, and a call starts it), `coerce()` for small slips ("16:9" → "16:9 (Widescreen)", "8" → 8), and an `unload_service` hub tool. Live: 35 tools (9 hub, 26 from the mods); `?q=turn image into video` finds `comfy_animate_image` first.
  - **Sources:** manifest `[tools]` plus their operations, and the functions from each running mod's `[agent] tools_source` route (comfy's task tools, Phase 11.10), re-read when the mod changes. Each becomes an OpenAI-style function:
    - `name`: `<mod>_<tool>`
    - `description`: from the manifest, else the OpenAPI summary; one short paragraph, written for the model
    - `parameters`: one flat JSON Schema merging the path/query params and the JSON body
  - **New manifest fields per tool** (`utils/manifest.py` `ToolSpec`, documented in architecture §4.3 and docs/mods.md):
    - `risk = "read" | "write" | "generate" | "destructive"` (default `write`): drives the default permission (13.2) and the MCP annotations (13.4)
    - `ask = ["workflow", "aspect", …]`: inputs the user chooses. They're shown on the parameter card (13.2) even when the model filled them in
    - `examples = [{…}]`: one or two example argument sets (the research found these raise accuracy on complex parameters)
    - `core = true`: always loaded in the chat (14.6); everything else is deferred
    - `tools_source` functions carry the same fields (comfy: `risk = "generate"`, `ask` from each pack's `[inputs.X] ask = true`, plus the workflow choice)
  - **File inputs** take `{"$file": "output:<id>"}`. A file input's schema gets `x-kind: image | video | audio | mesh` so the agent and the cards know what fits (image → 3D, image → video, image as a reference).
  - **Routes:** `GET /api/tools` (full schemas), `GET /api/tools/index` (name, mod, risk and a one-line summary only: the deferred list), `GET /api/tools?names=a,b`, and `GET /api/tools?q=<words>` (keyword search over names and descriptions, best 8).
  - **Hub tools** (`utils/tools/hub_tools.py`, `core`): `list_services`, `start_service`, `stop_service` (destructive), `memory_status`, `search_outputs`, `get_output`, `list_models`, `job_status`.
  *Done when:* `utils/tests/tools/test_catalog.py` builds the catalog from fake mods (manifest tools, a `tools_source`, metadata defaults, merged schemas, search); the contract test covers the new routes; brief §11.7 gains `Tool`, `ToolIndexItem`.
- [x] **13.2 Calls, permissions and approvals: `utils/tools/calls.py`, `utils/tools/approvals.py`.** *As built:* every answer is one `ToolCallResult` shape (brief §11.12); calls run as hub tasks recorded in `tool_calls` (so a dropped client doesn't stop them, `GET /api/tools/calls/{id}?wait=` picks them up, and a call following a job resumes after a hub restart); requests carry `X-AIHub-Make-Room: 1` (`agent.make_room`, default on) and go through the memory triggers; a stopped mod is started first; `hub_start_service` is allowed by default.
  - **`POST /api/tools/{name}/call {arguments, origin}`** validates against the schema; an invalid call returns `{error: {code: "invalid_arguments", detail, fix}}` naming the field and the allowed values, so the model can correct itself.
  - **Permissions** (`config.toml [agent.permissions]`, Settings → Agent): `deny`, `ask` and `allow` lists of name patterns (`comfy_*`, `hub_stop_service`), checked **deny → ask → allow**, then the default by risk: `read` allow, `generate` ask, `write` ask, `destructive` ask. A `mode` of `ask` (default), `auto` (only `destructive` asks) or `read_only` (only `read` runs) is set per call by the agent (14.5).
  - **Approvals** (migration: an `approvals` table): an `ask` call returns `{status: "needs_approval", approval_id, arguments, ask_fields, schema}` and publishes an `approval` event. **`POST /api/approvals/{id} {approve, arguments?}`** may carry **edited arguments**, which the hub validates and runs: this is the parameter card. A call that needs approval can't run without one; the hub enforces this, not the model.
  - **Results:** JSON stays JSON, capped at 8 KB with `{truncated: true, full: "<path>"}`; media becomes `{output_id, ref, url, kind, summary}` (no bytes, no base64); errors become `{error: {code, detail, fix}}`.
  - **Long-running tools** (`job = true`): the call returns when the mod's job finishes and streams its progress as `job` events (the chat shows them on the tool card). It waits up to 30 minutes, then returns `{status: "running", job_id}` for `job_status`.
  *Done when:* `utils/tests/tools/test_calls.py` covers schema errors with fixes, deny/ask/allow order and modes, an approval with edited arguments, a denied approval, a direct HTTP call that can't skip approval, result capping, and a fake mod's job followed to completion.
- [x] **13.3 Model facts from the relay: context window, tools, vision.** *As built:* `services/relay/web/backend/app/services/model_facts.py`; `meta` also carries `source` (override, props, vllm, probe); the probe streams and drops the connection on success; the override is the endpoint's `facts_override` (Endpoints page), and `GET /admin/endpoints/{id}/facts?refresh=1` re-reads. Live: `skynet` 131,072 (probe; `tools` and `reasoning` set by override), `gemma4-26B` 262,144 with tools, vision and reasoning (props). Relay suite 189 passed.
  - **The relay mod** (`services/relay/web/backend/app/…`) adds to each entry of `/v1/models` a `meta` object: `context_length`, `tools` (bool), `vision` (bool), `reasoning` (bool). Read from the upstream:
    - llama.cpp: `GET /props` (`n_ctx`; `modalities`)
    - vLLM: `max_model_len` from `/v1/models`; when another relay hides it (the `skynet` endpoint, a DashLLM relay on the GPU box behind `ssh -L 9090`), a one-time probe with an oversized `max_tokens`, whose error names the limit (checked 2026-10-06: `max_model_len=131072`)
    - an override per endpoint on the relay's Endpoints page, which wins
  - **Cached** per endpoint and refreshed when the endpoint's model changes.
  *Done when:* the relay's tests cover the three sources and the override; `curl :4000/v1/models` shows `context_length: 131072` for `skynet` and `262144` for the local Gemma 4 26B.
- [x] **13.4 MCP endpoint: `utils/tools/mcp.py`, `/mcp`.** *As built:* `utils/tools/mcp.py`, `mcp_approval.py`, `utils/routes/mcp.py`. One stateless endpoint serves both eras: 2026-07-28 requests (per-request `_meta`, the `MCP-Protocol-Version`/`Mcp-Method`/`Mcp-Name` headers checked, `server/discover`, `resultType`) and the 2025 `initialize` era (2025-03-26, 2025-06-18, 2025-11-25); JSON responses only. An `ask` call to a 2026-07-28 client that declares form elicitation answers `input_required` with the ask fields (accept = approve with the edits, decline = deny), a url-only client gets a link to AIHub, and others get an explanation plus `aihub_wait_approval`. The `mcp` SDK (2.3.0, dev dependency) lists and calls tools in both modes in the tests; live on :7000: 36 tools. The same catalog over MCP (spec 2026-07-28, streamable HTTP, stateless). Annotations from `risk` (`readOnlyHint` for read, `destructiveHint` for destructive). `ask` calls answer with MCP's `input_required` result carrying the approval, and the approval also shows in the hub's Approvals popover. Loopback only; a bad `Origin` gets 403. This is how Claude Code (or any MCP client) uses AIHub: `claude mcp add --transport http aihub http://127.0.0.1:7000/mcp`.
  *Done when:* `utils/tests/tools/test_mcp.py` lists and calls tools with the `mcp` client library; an `ask` tool can't run over MCP without an approval; Claude Code lists AIHub's tools.
- [x] **13.5 Agent evaluation: `services/agent/evals/` (go/no-go for Chat).** *As built:* dry runs (generating tools make labelled stand-ins in `outputs/eval/`) for the 3 × 30 runs, live runs for real outputs (`evals/live.py`), a vision check (both models see images). The 31B passes the gate (29/30 at pass^3 after the night's fixes); results in `docs/agent-eval.md` and the overnight report. Models on llama.cpp get every tool loaded (grammar-constrained calls can't reach deferred tools). Built before the chat: a small harness that runs the Phase 14 loop headless (it lands here first as `agent/loop.py` with a fake UI that answers questions from a script).
  - **30 tasks** from real use, each a scripted conversation with expected outcomes: single generations; chains (an image, then 3D from it; an image, then a video; describe an image, then speak the description); requests missing a required choice (the agent must ask, not guess); and refusals (a disabled tool).
  - **Graded on outcomes:** the right tool, valid arguments, outputs exist, it asked when a choice was missing, it didn't ask when everything was given, it never invented a result.
  - **Each task runs 3 times**, scored pass^3 (all three pass), on Gemma 4 31B (`skynet`, primary) and Gemma 4 26B (local), with tools deferred and with all tools loaded.
  - **Vision check:** can each endpoint take an image input (needed for 14.8's `view_output`).
  - **Results** in `docs/agent-eval.md`. **Gate:** Stage D starts when the primary model passes 80% of tasks at pass^3. If not, change prompts and tool descriptions (not the tasks) and re-run.
  *Done when:* `services/agent/tests/test_evals.py` runs the harness against the fake model server; the live result is recorded.

**Wire — Phase 13:** `tools` goes live: *Done: tool badges with risk in the API tab, the header Approvals popover, and ask tools from the API tab go through the approval card (`web/api-tool.js`).*
- the purple **tool** badges in each API tab come from the real catalog, with their risk level
- a header **Approvals** popover (with a count badge) lists pending approvals as parameter cards: the `ask` fields editable, Approve/Deny
- calling an `ask` tool from the API tab goes through the real approval flow

**Checks & deliverables — Phase 13**
- [x] An `ask` tool can't run without an approval, even when called directly over HTTP or MCP. *(Tests; live: Claude Code's `tts_speak` became a denied approval and nothing ran.)*
- [x] An approval with edited arguments runs with the edited values. *(Tests; the eval's `card_edit` 3/3.)*
- [x] Claude Code can list and call AIHub tools over MCP. *(Live: 41 tools listed, `hub_memory_status` and `hub_list_services` called.)*
- [x] The relay reports each model's context window; the eval result is recorded in `docs/agent-eval.md` and passes the gate. *(31B final: 29/30 at pass^3.)*
- [x] Delivered: `utils/tools/` (catalog, calls, approvals, MCP), the tool and approval routes, the relay's model facts, the eval harness and its result.

---

# Stage D — Chat interface (built last)

Everything here waits until Stages A–C are done and the 13.5 gate has passed. The design is in architecture §14.

## Phase 14 — Chat and the agent

A chat that works the way Claude Code does: one loop, tools that load on demand, questions back to you as cards, approvals as editable parameter cards, results you can chain, and the context window always in view. It's a mod, `services/agent`, with no agent framework: the loop is our own (about 400 lines), talking to the relay for the model and to the hub for tools.

- [x] **14.1 Chat brief for Claude Design** *As built:* built by hand in `web/chat/` (brief §11.13: card and action registries), like revision 2. (extend the brief's "Reserved: Chat" section).
  - **Thread list and thread view**, with search and rewind/branch from any earlier message.
  - **Messages:** streaming text; **thinking** folded into one line per step ("Thought for 6 s ›") that expands in place, shown only when Settings → Agent → Show thinking is on, so the layout doesn't move.
  - **Cards in the thread:**
    - **tool card:** the tool, its arguments, live job progress, Stop
    - **question card** (`ask_user`): 1–4 questions, options with descriptions, multi-select, an "Other" box; a form when the question carries a schema
    - **parameter card** (an approval): the `ask` fields editable (workflow, aspect, voice, preset…), Run / Change / Cancel
    - **result card:** reuses `OutputCard`, `AudioPlayer` and `Viewer3D`, with its reference (`#3`) and **action buttons** by kind: an image gets Animate, Make 3D, Edit, Upscale, Use as reference, Describe; audio gets Use as voice; a mesh gets Rig
    - **todo checklist** for multi-step requests, pinned at the top of the thread while it runs
  - **Composer:** model picker (from the relay, with each model's context window), **quick actions** (Image, Video, 3D, Speech, Edit image…) that open a parameter card directly, tool-group toggles, attachments from Outputs or an upload, Stop, and messages typed during a turn queued for it.
  - **Context meter** in the thread header: `41.2k / 131k`, with a breakdown popover (instructions, tools, skills and memory, messages, tool results) and a mark where the thread was compacted.
  - **Slash commands:** `/compact`, `/clear`, `/model`, `/context`, plus each skill (14.8).
  - **A placeholder Sessions panel**, filled in Phase 15.
  - **Mock:** a scripted agent that asks, shows a parameter card, streams a result and offers actions.
  *Done when:* the brief section is written and Claude Design's export (or a hand build, as in 6.5) is in `web/`, reachable in `?mock`.
- [x] **14.2 The agent mod** *As built:* port 5100; `agent/` also has `local.py` (the local tools), `knowledge.py` (AGENT.md, skills, memory) and `hubapi.py` (the hub client; `hub.py` became the status and widget routes inside `server.py`). `aihub check agent` passes. (`aihub new agent`, port from the 5100 range).
  - **Files:** `agent/llm.py` (the model client), `agent/loop.py`, `agent/store.py` (threads and events), `agent/context.py`, `agent/tools.py` (local tools + the hub catalog), `agent/prompts.py`, `agent/server.py` (`create_app`), `agent/hub.py` (status and widget). Dependencies: FastAPI, uvicorn, httpx; no agent framework.
  - **Manifest:** status (stats: threads, messages today, tokens today; jobs: running turns), a "Messages per day" widget, `[memory]` none (the model lives in the relay's endpoints).
  - **`env`:** `AGENT_DB={databases}/agent.db`, `AGENT_DATA={root}/data/agent`, `AGENT_LLM_URL=http://127.0.0.1:4000/v1`, `AGENT_MODEL=skynet` (Gemma 4 31B, 131,072 tokens), `AGENT_FALLBACK_MODEL=gemma4-26b-7071`.
  *Done when:* `aihub check agent` passes.
- [x] **14.3 The model client: `agent/llm.py`.** *As built:* `stream_options.include_usage`; leaked calls in Gemma's `<|tool_call>call:name{…}<tool_call|>` (with its `<|"|>` strings), Hermes `<tool_call>` and lone/fenced JSON naming a known tool; `<think>` blocks in content become thinking. Live: the 31B corrects a wrong argument name from the hub's `fix`.
  - Streams `/v1/chat/completions` from the relay with the tool schemas. **No `max_tokens`:** the model may use the whole window for thinking and output. *As built:* a reply that only repeats itself is cut off and asked again once (the 26B once streamed 23,762 tokens in 9 minutes).
  - **Thinking** comes from `reasoning` (vLLM) or `reasoning_content` (llama.cpp). It is stored and streamed, but not sent back to the model on later turns.
  - **Tool calls:** native `tool_calls` first. If tool-call markup leaks into `content` (a reported Gemma 4 issue on llama.cpp), it is re-parsed. Malformed JSON arguments go back to the model as an error with the schema, once. Calls run in parallel when every tool in the batch is `read`, otherwise one at a time.
  - **Usage:** `prompt_tokens` and `completion_tokens` from every response feed the context meter (14.7).
  *Done when:* `services/agent/tests/test_llm.py` covers streaming, both reasoning fields, a leaked tool call, a malformed-argument retry, and parallel vs sequential batches, against the fake model server.
- [x] **14.4 The loop and threads: `agent/loop.py`, `agent/store.py`.** *As built:* extra events `call` (the hub call id, so a restarted agent waits for a running call) and `state`; a message typed while a question or card waits dismisses it (the card is denied at the hub); a thread a crash left `running` resumes at startup; decisions made in the hub's popover reach the thread through `/api/events`. The kill -9 test runs the agent as a real process.
  - **One turn:** call the model, run its tool calls, append the results, repeat until a reply has no tool calls. **Stops:** done; `max_steps` (25, settable) with an honest "I stopped at the step limit"; error; cancelled. *As built:* a repeated identical call is refused from the third time, and after the second refusal the turn ends with a tools-off model call (`tool_choice: "none"`), found when the 26B called `load_tools` 28 times on a turned-off group.
  - **Pauses:** an `ask_user` call or an approval ends the request in a `waiting` state. The answer (`POST /v1/threads/{id}/answer` or `/approval`) appends it and continues the same turn.
  - **Interruptions:** Stop cancels the running model call or tool (a running job is cancelled through its mod). A message sent during a turn is queued and read after the current tool calls, as Claude Code does.
  - **Store:** `agent.db` tables `threads` (id, title, model, created, updated, archived, parent_id, fork_seq) and `events` (thread_id, seq, type, payload, tokens). An **append-only event log**: user messages, assistant text, thinking, tool calls, results, questions, answers, approvals, compaction marks. The model's messages are rebuilt from it.
  - **Fork** copies a thread's events up to a `seq` into a new thread: rewind and branch.
  - **Routes:**
    - `GET/POST /v1/threads`, `GET/PATCH/DELETE /v1/threads/{id}`
    - `POST /v1/threads/{id}/messages` (SSE)
    - `GET /v1/threads/{id}/events?after=` (replay, so a reloaded page or a dropped stream catches up)
    - `POST /v1/threads/{id}/answer`, `/approval`, `/action`, `/fork {seq}`, `/cancel`
  - Titles are generated after the first reply.
  *Done when:* `services/agent/tests/test_loop.py` covers a multi-step turn, the step cap, a pause for a question answered after **killing and restarting the agent process**, a queued message, cancel, and a fork from an earlier `seq` that leaves the original unchanged.
- [x] **14.5 Asking and approving: `ask_user`, parameter cards, actions.** *As built:* actions run with mode `auto` (the UI shows its own card first); a question may carry a `schema` (a form).
  - **`ask_user` tool** (local, `core`): 1–4 questions, each with a header, 2–4 options with descriptions, `multi_select`, and an optional `schema` (a form). "Other" is always allowed. The answers come back as the tool result.
  - **Parameter cards:** an `ask` or `generate` tool call becomes a hub approval (13.2). The card shows the model's arguments with the `ask` fields editable. The user's edits are what runs. This makes "which model, which size" a fixed step rather than the model's choice. In a live test on 2026-10-06, the 31B model picked an aspect ratio itself instead of asking.
  - **Ask mode** (thread setting, default **Ask about choices**):
    - **Ask about choices:** parameter cards for `generate`/`write`
    - **Use defaults:** only `destructive` asks
    - **Read only**
  - **Prompt rules** (`agent/prompts.py`): ask with `ask_user` when the request leaves an open choice that no tool default covers; after a result, offer the likely next steps as options.
  - **Buttons are actions:** a result card's button or a quick action posts `/v1/threads/{id}/action {tool, arguments}`. That appends a user-initiated tool call (with its parameter card) to the thread, with no model call first. The model sees it in the history and carries on from there, so clicking and typing lead to the same thread.
  *Done when:* `services/agent/tests/test_asking.py` covers a question answered with an option, with "Other" and with a form; a parameter card edited then run; a denied card; an action button that runs without a model call; and each ask mode.
- [x] **14.6 Tools on demand: `agent/tools.py`.** *As built:* a call to a deferred tool loads it automatically; a disabled group's call is refused by the agent with `disabled` and never reaches the hub (global denies stay in `[agent.permissions]`); `load_tools` and `find_tools` say a group is turned off instead of listing its tools as unknown.
  - **Always loaded:** the `core` tools: `ask_user`, `update_todos`, `find_tools`, `load_tools`, `read_skill`, `view_output`, `read_result`, `remember`, and the hub's `core` tools.
  - **Deferred:** the rest are listed in the system prompt by group (one line per mod: what it does and its tool names) from `GET /api/tools/index`. `find_tools(query)` and `load_tools(names | group)` add full schemas to the thread, and they stay loaded across compaction.
  - **The toggles** in the composer pin a group (always loaded) or turn it off. The hub also refuses a disabled tool when it's called: two gates.
  *Done when:* `services/agent/tests/test_tools.py` covers the index in the prompt, find → load → call, pinned and disabled groups, and a refused disabled call.
- [x] **14.7 Context: `agent/context.py`.** *As built:* the breakdown is estimated at 4 characters per token (a `view_output` picture counts as a fixed 1,100 tokens, not its base64: two pictures used to fill an 84k window; fixed 2026-10-10, plan chat-uploads U.6) and scaled to the model's reported total; the 70%/85% checks use the estimate of the rebuilt prompt, so a compaction counts at once.
  - **Window** from the relay's `meta.context_length` (13.3), else a per-model setting.
  - **Used:** the last response's `prompt_tokens + completion_tokens`, plus an estimate for anything added since. Sent to the UI after every step as `{used, window, breakdown}`. The breakdown is estimated per section with the endpoint's `/tokenize` when it has one, else 4 characters per token.
  - **Tool results:** capped at 4,000 tokens in the history. The rest is kept in the event, and `read_result(event, offset)` pages through it.
  - **Compaction:**
    - at **70%**, older tool results are cleared to a one-line stub
    - at **85%**, older turns are summarized by the model into a `compact` event: decisions, output references, open questions, the todo list, loaded tools
    - `/compact` runs it by hand
    - if a compaction can't bring usage under 70% (one huge item), it stops and says so instead of looping
  - **System prompt order:** base prompt, `AGENT.md`, the memory index, the skill list, the deferred tool index, the environment (date, running and loaded mods, free memory), the thread's outputs table.
  *Done when:* `services/agent/tests/test_context.py` covers the window from `meta` and from the setting, the meter values, result capping and `read_result`, both compaction stages, the thrash guard, and the prompt order.
- [x] **14.8 Chaining outputs: references and `view_output`.** *As built:* gen3d is text-only (Cube3D), so image → 3D goes through `view_output` (the model looks at the image) and a 3D prompt; both models see images (13.5's vision check).
  - **References:** every result in a thread gets a short reference (`#1`, `#2`…). A small **outputs table** in the system prompt lists them: ref, kind, tool, a short summary and `output:<id>`. "Make that fox into a 3D model" resolves to `{"$file": "output:<id>"}`.
  - **File inputs** offer the thread's outputs of a matching kind (`x-kind`) on parameter cards. Result-card buttons fill them in.
  - **`view_output(ref)`** sends an image (or a video's poster frame) to the model when its endpoint has `vision` (13.3), so it can describe an image, write from it, or check a result. Otherwise it returns the output's sidecar (prompt, settings).
  *Done when:* `services/agent/tests/test_chaining.py` covers an image → 3D chain by reference, an image used as a reference input, a description written via `view_output`, and the non-vision fallback.
- [x] **14.9 Instructions, skills and memory.** *As built:* hub routes in `utils/routes/skills.py`; first skills `comfy/choosing-a-workflow`, `tts/voices`, `gen3d/making-3d`; `data/agent/` is gitignored (personal).
  - **`AGENT.md`** (`data/agent/AGENT.md`, edited in Settings → Agent): standing instructions, under 200 lines, re-read every turn.
  - **Skills, loaded only when needed:**
    - a mod ships `services/<id>/skills/<name>/SKILL.md` (frontmatter `name`, `description`), declared as `[agent] skills = "skills"`; the hub serves `GET /api/skills` and `GET /api/skills/{mod}/{name}`
    - your own skills live in `data/agent/skills/`
    - the prompt lists names and descriptions; `read_skill` loads the body; each skill is also a slash command
    - first skills: comfy (choosing a workflow and its settings per task), tts (voices and direction), gen3d (presets, parts and rigs)
  - **Memory:** `data/agent/memory/MEMORY.md` (an index of up to 200 lines, in every prompt) plus topic files read on demand. `remember(text, topic)` writes them and shows a small card in the thread. Settings → Agent lists and edits memories, e.g. "likes 16:9", "my voice is Brendon".
  *Done when:* `utils/tests/tools/test_skills.py` (hub routes) and `services/agent/tests/test_memory.py` cover skills listed then read, a slash command, and memory written, shown in the prompt and edited.
- [x] **14.10 Multi-step requests: todos.** *As built:* as planned; the checklist is a `todos` event (the UI pins the latest).
  - **`update_todos(items)`:** for requests with three or more steps ("an image, then animate it, then narrate it"), the agent writes a checklist (pending → in progress → done), shown pinned in the thread.
  - **Steps run in order**, each with its own parameter card unless the thread is in Use defaults.
  - **A failed step** is marked failed with its error, and the agent asks whether to retry, change it, or skip.
  *Done when:* `services/agent/tests/test_todos.py` covers a three-step chain with its checklist states and a failed step's question.
- [x] **14.11 Tests with a scripted model.** *As built:* plus `tests/fakehub.py`, a stand-in for the hub's tools API; 52 tests, about 20 s. A fake OpenAI-compatible server returns scripted streams: text, thinking, tool calls and leaked tool calls (`services/agent/tests/fakemodel.py`, Mango-Tree's scenario-harness idea rebuilt small). It runs the 14.3–14.10 tests and the 13.5 harness offline.
  *Done when:* `.venv/bin/python -m pytest` in `services/agent` passes with no model running.
- [x] **14.12 Live smoke test.** *As built:* `evals/live.py` on both models, plus the restart, compaction, meter and session checks; results in `docs/agent-eval.md` and the overnight report. 10 real conversations on `skynet` (Gemma 4 31B), recorded in `docs/agent-eval.md`:
  - "make me an image of a fox": it asks or shows a parameter card, generates, then offers next steps
  - that image to 3D, and that image to video
  - "describe this image, then say it in Brendon's voice"
  - a quick-action button and a result-card button
  - a thread compacted by hand and continued
  - a fork from an earlier message
  - the same thread on the local Gemma 4 26B
  *Done when:* the transcript notes and pass/fail per task are in `docs/agent-eval.md`.

**Wire — Phase 14:** `chat` goes live: *Done: the Chat page (`web/chat/`), Settings → Agent; approvals shared with the header popover.*
- the Chat nav item is enabled
- the thread list, threads, streaming and thinking, all the cards, quick actions, the context meter, rewind/branch
- approvals shared with the header popover from Phase 13
- Settings → Agent: `AGENT.md`, memory, permissions, ask mode, Show thinking, models

**Checks & deliverables — Phase 14**
- [x] "Make me an image of a fox, then turn it into a 3D model": it asks or shows the parameter cards, both outputs appear in the thread and on the Outputs page, the 3D job used the fox image, and the Relay page shows the agent's traffic. *(Live L2 with a robot: image → `view_output` → a 3D prompt describing it → GLB; the eval's `img_to_3d` and `one_shot_chain`; gen3d is text-only, so "used the image" means it was described.)*
- [x] A pending question and a pending approval both survive restarts of the hub and the agent. *(Live `evals/restart_live.py`; a graceful agent restart also resumes a running turn.)*
- [x] The context meter matches the relay's reported usage, and compaction keeps the thread working past 85%. *(Live: within 1.1% of the 31B's prompt tokens; `evals/compact_live.py`: 5 clears and a summary, the first turn still answered.)*
- [x] A fork from an earlier message creates a separate thread, and the original is unchanged. *(Tests; the eval's `fork` 3/3 checks the original byte for byte.)*
- [x] Delivered: `services/agent`, `agent.db`, `data/agent/` (AGENT.md, skills, memory), the Chat page, Settings → Agent, the scripted-model test suite and `docs/agent-eval.md`.

## Phase 15 — Save states: sessions

- [x] **15.1 Snapshots.** *As built:* `utils/sessions.py`; the snapshot keeps lcpp's launch spec from `GET /api/instances` (kind, model, port, params, relay alias) and each instance's memory; ComfyUI and gen3d are covered by their mods' load state.
  - **What's recorded:** which mods are running and loaded, lcpp's instances with their full LaunchSpec (from `GET /api/s/lcpp/api/instances`), and the ComfyUI and gen3d worker load states.
  - **Where:** a `sessions` table in `hub.db` (id, name, created, auto, snapshot JSON).
- [x] **15.2 Session routes.** *As built:* `utils/routes/sessions.py`; `restore` runs stop LLMs → unload → start → launch LLMs → load (loads through the memory manager with make-room; LLM launches ask AIHub for memory themselves); mods that run but aren't in the session keep running; `GET /api/sessions/state` reports an unclean last shutdown (a `kv` flag) for the "Restore last session?" toast; the auto session is "Last session".
  - `GET/POST /api/sessions` and `PUT/DELETE /api/sessions/{id}`.
  - `POST /api/sessions/{id}/restore?dry_run=1` returns the steps and a memory plan. A real restore runs them in order through the memory manager.
  - **Auto-save:** an `auto` session is saved every 5 min and on clean shutdown.
  - **Restore at boot:** `[sessions] restore_on_boot = false` in `config.toml`. *As built after the first real reboot (2026-10-07):* each start copies the previous "Last session" to "Before restart" (never auto-saved over); restore at boot and `GET /api/sessions/state`'s `last_auto` use it.
- [x] **15.3 Session tools for the agent:** *As built:* `hub_save_session`, `hub_list_sessions`, `hub_restore_session` (risk `write`: a card asks first; `dry_run` shows the steps). `save_session`, `list_sessions`, `restore_session` (confirm).

**Wire — Phase 15:** `sessions` goes live: *Done: the Sessions panel (Chat and Settings → Sessions), the command-palette actions, the restore prompt after an unclean shutdown (`web/sessions.js`).*
- the Sessions panel, in Chat and in Settings → Sessions
- the command-palette actions "Save session…" and "Switch to session…"
- a "Restore last session?" toast after an unclean shutdown

**Checks & deliverables — Phase 15**
- [x] Save "LLM work" (Gemma loaded, tts loaded), switch to "3D work" (gen3d loaded), then switch back. Each switch shows its plan, and memory never goes over the limit. *(Live: five switches, peak 46 GB of a 118 GB limit; the 26B relaunched with its settings and re-registered with the relay.)*
- [ ] With `restore_on_boot = true`, a reboot brings back the same lcpp instance and the same loaded mods. *(Tested across hub restarts in `test_sessions.py`; not tried with a real reboot.)*
- [x] Delivered: session snapshots, routes, tools and UI.

## Phase 16 — Everything inside the folder

- [x] **16.1 Logs in `data/logs/`.** *As built:* `utils/logfiles.py`: one shipper per mod follows the backend (`journalctl -f` per unit, or the child's pipes) into `data/logs/<id>.log` (`<iso time> out|err <text>`); the Logs tab reads the file once it has lines; `aihub logs [id] [-f]` tails the file (`--journal` for the journal); the hub's log is `data/logs/aihub.log`. A log shipper in the hub follows each mod's journal and appends to `data/logs/<id>.log` (rotated at 10 MB, 5 files kept). The hub's own log goes to `data/logs/aihub.log`. The Logs tab and `aihub logs` read these files, and journald stays as a second copy.
- [x] **16.2 Runtime state in `data/state/`.** *As built:* `LCPP_STATE_DIR={root}/data/state/lcpp` (the running 26B's record was copied over and lcpp kept managing it); the reconcile forgets records that started before the last boot (`/proc/stat` btime). ComfyUI's pidfile already lives in the mod (`services/comfy/data/`), inside the project. The old `/run/user/1000/lcpp` copy stays until the next reboot (tmpfs).
  - lcpp gets `LCPP_STATE_DIR={root}/data/state/lcpp`.
  - Its reconcile treats records whose units are gone (after a reboot) as gone, and session restore relaunches them.
  - The comfy pidfile and the hub's own lock files move here too.
- [x] **16.3 `aihub doctor --inventory`.** *As built:* `utils/inventory.py`, `GET /api/doctor/inventory`, `aihub doctor --inventory`. Live: 14 allowlisted, 1 runtime leftover (the old lcpp tmpfs folder), 2 outside: lcpp's CLI installed as a uv tool (`~/.local/share/uv/tools/lcpp`) and opencode's `OPENCODE_PROJECT_DIR` (both need the user's decision). Lists every path outside the project that anything uses, each with its reason. The allowlist is now final: the systemd unit file, podman images, system tools, and the `~/.local/bin` wrappers.
- [x] **16.4 Final docs pass.** *As built:* architecture §14 and CLAUDE.md describe the finished system; this plan is checked off except the items marked open. `architecture.md` and CLAUDE.md describe the finished system, and this plan is fully checked off.

**Wire — Phase 16:** the Logs tab reads `data/logs/`, and Settings → Paths shows `data/logs` and `data/state` with their sizes. *Done: the Logs tab reads the files; Settings → Paths shows both folders.*

**Checks & deliverables — Phase 16**
- [ ] `aihub doctor --inventory` lists only the allowlist. *(Two items wait on the user: opencode's `OPENCODE_PROJECT_DIR` and lcpp's CLI installed as a uv tool.)*
- [x] Run on a fresh copy of the folder, `aihub doctor --inventory` names only allowlisted prerequisites. *(A fresh clone: only the machine's uv-tool lcpp CLI, which the folder doesn't need, and a tmpfs leftover.)*
- [ ] Delivered: a self-contained AIHub.

---

# Stage E — Image to 3D

## Phase 17 — Image to 3D in `gen3d`

Four image engines join Cube3D in the 3D Generate mod, all producing untextured meshes (texturing and retopology happen outside AIHub). Measured on this machine on 2026-10-10 (lab: `services/gen3d/runtime/lab/`, write-up `lab/report/index.html`): **Hunyuan3D 2.1** runs from Tencent's code (shape only, pure PyTorch), **TRELLIS.2** and **SAM 3D Body** run as ComfyUI 0.37 native nodes, and **SAM 3D Objects** runs from Meta's code with a pure-PyTorch `spconv` replacement (real weights, samurai and vase: 49–77 s per image). Every engine gets a **base** and a **fast** preset with every model parameter exposed. Touches architecture §10 (the gen3d row), §4.7 (outputs), brief §5 (the page), and plan Phases 8 and 11.

**Settled (user, 2026-10-11):**
- **TRELLIS.2 and SAM 3D Body are delegated to the `comfy` mod** through the hub (`POST {AIHUB_URL}/api/s/comfy/v1/run` with `X-AIHub-Make-Room: 1`), so the ComfyUI install and its memory accounting stay in one place; gen3d still owns the job, queue, ETA and viewer. Their packs carry `agent = false`: the agent reaches them only through gen3d's `make_3d`.
- Every engine defaults to its **fast** preset; base stays one click away. Every engine but SAM 3D Body gets a **`target_faces`** option (0 = keep the raw mesh). Evidence: `lab/RESULTS.md` §5–6 and the report's "Why the vase takes longer" and "Lower polygon counts".

**Design (as planned 2026-10-11):**
- **Image engines run the `shape` stage.** It reads the job's image instead of a prompt and writes `mesh.glb` (plus `mesh_raw.glb` when `target_faces` reduced it), so `parts`, `rig`, `preview`, the viewer, follow-ups and `output.json` work unchanged.
- **Image input:** `image` in the request is an AIHub `output:<id>` (gen3d fetches `GET {AIHUB_URL}/api/outputs/<id>/file`), or a file sent to `POST /v1/jobs/image` (multipart `image` + `job` JSON, like `/v1/jobs/upload`). gen3d writes `input.png` and `input_rgba.png` into the job folder: alpha from the image, else everything that isn't near-white.
- **Delegated stages stop gen3d's own worker first**, so the hub doesn't count gen3d's memory while comfy needs it. Known cost: a gen3d job still passes gen3d's `[memory]` trigger, which reserves gen3d's estimate when gen3d is unloaded.

**Simple gaps (assumed):**
- **Licences:** Hunyuan3D 2.1's licence excludes the EU, UK and South Korea; SAM 3D's are the SAM Licence; TRELLIS.2 is MIT. *Assumption:* recorded in the registry entries' `license` field and shown on the engine picker; nothing is enforced.

- [x] **17.1 Runtimes: `services/gen3d/scripts/install-runtime.sh`.**
  - **Hunyuan3D:** clone `Tencent-Hunyuan/Hunyuan3D-2.1` at `82920d6` into `runtime/hunyuan3d-2.1/`; venv `runtime/img3d/.venv` layered on CubeArt's venv and the image's `/opt/venv` (a `_layers.pth`), plus `timm` and `fast-simplification` (locks in `services/gen3d/locks/img3d.txt`).
  - **SAM 3D Objects:** clone `facebookresearch/sam-3d-objects` at `f91db41` into `runtime/sam3d-objects/`; venv `runtime/sam3do/.venv` layered on img3d, with the lab's packages (`locks/sam3do.txt`: hydra-core, loguru, lightning, optree, roma, pymeshfix, igraph, xatlas, pyvista, fvcore, utils3d @3913c65, MoGe, pytorch3d 0.7.8 built CPU-only).
  - **Shims become tracked code:** `services/gen3d/workers/shims/` (`spconv/pytorch`, `gsplat`, `kaolin`, `open3d`) with `tests/test_spconv_shim.py` (dense-Conv3d equivalence, from `runtime/shims/test_spconv_shim.py`).
  - **Doctor:** `gen3d/doctor.py` reports each engine's runtime as ready or missing.
  *Done when:* a fresh `install-runtime.sh` builds all three venvs and `gen3d doctor` lists cube3d, hunyuan21 and sam3d-objects as ready; `pytest tests/test_spconv_shim.py` passes.
  - *As built:* the engine list is `gen3d/engines.py` (local or delegated, weights, code, venv, licence); the doctor reads it. The shim test needs torch, so it skips in the server venv and runs in the image (3 passed); `install-runtime.sh` ends by importing each runtime.
- [x] **17.2 Weights in the registry.** `aihub models scan --add` for `data/models/3d/Hunyuan3D-2.1` (dit only), `data/models/3d/sam-3d-objects`, `data/models/3d/moge-vitl`, and the comfy files: `comfyui/diffusion_models/trellis_2_bf16.safetensors`, `comfyui/vae/trellis_2_shape_vae_bf16.safetensors`, `comfyui/clip_vision/dino_v3_vit_l.safetensors`, `comfyui/detection/sam_3d_body_dinov3_bf16.safetensors`, `comfyui/geometry_estimation/moge_2_vitl_normal_fp16.safetensors`. Each entry carries `source` (HF repo + file) and `license`. Remove the unused `trellis_2_int8_convrot.safetensors` (5.25 GB; no faster, less faithful) with the user's approval.
  *Done when:* `aihub models verify` passes for each, and `service.toml` `[models] dirs` covers them.
  - *As built:* eight entries registered through `POST /api/models` with their Hugging Face source; `services` is `gen3d` or `comfy`, and the licence is in `notes` (the registry has no licence field). All verify. The int8 file is not registered; deleting it waits for the user.
- [x] **17.3 Options: `gen3d/options.py`.**
  - `JobRequest.engine`: `cube3d` (text, today's behavior) | `hunyuan21` | `trellis2` | `sam3d_objects` | `sam3d_body`; `image` required for every engine but cube3d.
  - One options model per engine with every parameter, defaults and ranges from the lab (`lab/RESULTS.md`, report "Every setting"): Hunyuan3D (steps, guidance, octree, num_chunks, box_v, mc_level, flashvdm, topk, seed, floater/degenerate removal, max_faces); TRELLIS.2 (resolution 512/1024/1536, per-stage steps, cfg, rescale, interval, shift, seed, decimate target, remesh on/off); SAM 3D Objects (ss/slat steps, cfg strengths, rescale_t, intervals, seed, distillation); SAM 3D Body (hand refinement, fov or MoGe, export style glb/bvh, bone visuals).
  - Presets per engine, **fast is the default**: Hunyuan3D fast (30 steps, FlashVDM, num_chunks 200 k); TRELLIS.2 fast (shape 12, **refine 6**: same look as refine 8, 24 % less on round objects) plus `draft` (512 only: 54 s on the vase, softer, more pinholes); SAM 3D Objects fast (distillation; F 0.879 on characters, so the page notes "objects"); SAM 3D Body fast (hand refinement off). `GET /v1/options` and `GET /v1/presets` list them per engine.
  - `target_faces` (int, 0 = raw; default 0, page shortcuts 200 k / 100 k / 50 k): Hunyuan3D and SAM 3D Objects decimate in their worker with `fast-simplification` (0.2–0.7 s; Hunyuan3D 50 k mean error 0.007 % of the diagonal); TRELLIS.2 runs its built-in `RemeshMesh` (512, udf, drop inner shell) + `DecimateMesh` (10–24 s, clean to 50 k); the raw mesh is kept next to the reduced one. Hunyuan3D's `octree` 256 also halves faces at the source. SAM 3D Body has none (fixed rigged mesh).
  *Done when:* `tests/test_options.py` covers each engine's validation, presets and the catalogue shape; old requests without `engine` still parse as cube3d.
  - *As built:* the engine models and presets are `gen3d/image_options.py` (field defaults = fast; `base` and TRELLIS.2's `draft` list only what differs); `JobRequest` gains `engine`, `image` (`output:<id>` or `upload`) and one options group per engine; `GET /v1/options` adds `engines` (label, input, licence, runs in gen3d or comfy, what's missing, presets, settings). The SAM 3D Body fields are hand refinement and field of view; its mesh style stays the rigged body.
- [x] **17.4 Workers: `gen3d/worker.py` runs one engine container at a time.**
  - `Worker` takes an engine spec (venv, script, PYTHONPATH, mounts); switching engines stops the running container first (that is how memory is freed).
  - `workers/hunyuan_worker.py`: the JSON-lines protocol of `cube_worker.py` (`load`, `run`, progress per diffusion step via the pipeline callback, subs `conditioning` / `diffusion` / `volume_decode` / `marching_cubes`); FlashVDM switched on through `vae.enable_flashvdm_decoder` (the pipeline's `enable_flashvdm` fails on 2.1); `HY3DGEN_MODELS` and `TMPDIR` inside the project.
  - `gen3d/worker_fake.py` simulates every engine.
  *Done when:* `tests/test_api.py` runs a fake hunyuan job end to end; a real job on `results/samurai_front_rgba.png` with the fast preset finishes in ≤ 120 s cold and writes `mesh.glb` + `output.json`.
  - *As built:* `WorkerPool` holds one `CubeWorker(family)` per family (`cube`, `img3d`, `sam3do`; `worker.specs()`), and a run in another family stops the running container first. Workers share `workers/proto.py` (protocol, substages, `fast-simplification`). The picture is prepared at queue time (`gen3d/images.py`: `input.png` + the cut-out `input_rgba.png`) from `POST /v1/jobs/image` or an `output:<id>` fetched from the hub; retries and follow-ups read it from the parent job. Image-engine ETAs are seeded in `eta.py` now (17.7 checks them). Tests: `tests/test_images.py`. Real: samurai, fast, cold through the hub: 110 s wall (ETA said 111 s), 474,658 faces (lab 474,660), peak 12.3 GB.
- [x] **17.5 Comfy side: packs and fixes (`services/comfy/`).**
  - Commit the lab's two fixes: `extra_model_paths.yaml` gains `detection` and `geometry_estimation`; `nodes/aihub_nodes/__init__.py` gains `patch_sam3d_body` (hand-refinement dtype fix). Update docs/workflows.md §9.
  - Packs from the lab graphs (`workflow.api.json`, imported with `comfyui workflows new`), all `agent = false`, task `image-to-3d`, inputs `image` (an RGBA cut-out; the mask is its alpha) and every parameter in 17.3:
    - `trellis2-shape`: the cascade at 1024, raw mesh; `[presets.base]` (shape 20, refine 12) and `[presets.fast]` (shape 12, refine 6).
    - `trellis2-lowpoly`: the same plus `RemeshMesh` (512, udf, inner shell dropped) → `DecimateMesh` (`target_faces`), saving both meshes (`lab/graphs/trellis2_builtin_lowpoly.api.json`); never `DecimateMesh` on the raw mesh (it breaks thin parts).
    - `trellis2-draft`: 512 only (no cascade).
    - `sam3d-body`: the body mesh as a rigged GLB; `[presets.fast]` turns hand refinement off.
  - `tasks.toml` gains `image-to-3d` (needs `image`, makes a mesh, no agent tool); `service.toml` `[outputs] kinds` adds `model3d`.
  *Done when:* `comfyui workflows check` is clean for the four packs, and each runs from the Images & Video page into `outputs/comfy/`.
  - *As built:* one picture per pack: `LoadImage` of the RGBA cut-out, and `InvertMask` of its mask (LoadImage's mask is 1 − alpha) for the crop. `seed` and `guidance` reach every sampler (`also`). The packs don't label their outputs, and comfy renames save prefixes, so gen3d tells the reduced mesh from the raw one by size. Live on the samurai through `/v1/run`: sam3d-body 8.1 s (36,874 faces), trellis2-draft 49.6 s, trellis2-lowpoly 95.9 s (raw 5.7 M + reduced 49,364 faces), trellis2-shape 89.1 s.
- [x] **17.6 Delegated engines: `gen3d/comfy_engine.py`.**
  - For `trellis2` and `sam3d_body`, the runner uploads `input_rgba.png` (`POST /api/s/comfy/v1/uploads`), posts the pack run to the hub, polls `GET /api/s/comfy/v1/jobs/<id>?wait=…`, maps comfy's 0–1 progress to the stage's `step`/`total`, and downloads the result (`GET /api/s/comfy/v1/files/<path>`) into the job folder. TRELLIS.2 picks `trellis2-lowpoly` when `target_faces` > 0, `trellis2-draft` for the draft preset (its reduction falls back to `fast-simplification` in gen3d, which stops near 130 k faces on TRELLIS meshes).
  - Cancel forwards to comfy; a comfy error becomes the stage's error.
  *Done when:* tests with a fake hub (respx) cover success, progress, cancel and failure; a real TRELLIS.2 fast job on the vase finishes and shows in the gen3d viewer.
  - *As built:* the tests use `httpx.MockTransport`, not respx (`tests/test_comfy_engine.py`), and the fake mode has `FakeComfyEngine`. The runner stops gen3d's worker before a delegated stage. comfy's copies of the meshes go to the hub's trash in the background, retried while the hub indexes them, so the Outputs page lists the job once. The draft's `target_faces` runs a `reduce` task in the img3d worker. Real: TRELLIS.2 fast on the vase 235 s shape stage (13.2 M faces, peak 28.7 GB); SAM 3D Body 10 s.
- [x] **17.7 Memory and ETA.**
  - `[memory] estimate_gb` stays the largest local engine (Cube3D quality 52); each job acquires its engine's amount (`hunyuan21` 12, `sam3d_objects` 25, from the lab peaks + margin). Delegated engines don't acquire in gen3d; comfy does.
  - `gen3d/eta.py` seeds per-engine stage times from the lab (Hunyuan3D fast: 73 s diffusion + 9–14 s decode; TRELLIS.2 fast: 73 s samurai, 220 s vase; SAM 3D Body 1 s), refined by finished jobs. TRELLIS.2's refine time follows its token count (≈ 5 s/step at 7.7 k tokens, 26 s/step at 23 k; attention grows with the square), known once the shape stage finishes, so its ETA is recomputed then.
  *Done when:* `tests/test_eta.py` covers the new engines; the Memory page shows the right amount during a hunyuan job.
  - *As built:* `Engine.memory_gb` (hunyuan21 14, sam3d_objects 22) is acquired with `make_room=1` through `gen3d/hubclient.py` before the local stage; a 409 becomes the stage's error. The delegated stage is a single substage driven by comfy's percent, so its live ETA follows the run's real pace (no separate token-count step). Learned times key on the settings, not on the object, so a round object still starts from the character-based seed. Real: after a Hunyuan3D job the Memory page counts gen3d at 16.5 GB (its `gen3d-worker-img3d-*` container).
- [x] **17.8 SAM 3D Objects worker: `workers/sam3do_worker.py`.** Port `lab/sam3do_run.py`, which works with the real weights: the pipeline built from the checkpoint's yamls (patched copies), DINOv2 code from a local clone with `pretrained=false`, MoGe v1 from `data/models/3d/moge-vitl/model.pt`, the 4-Gaussian decoder off, `compile_model=false`, MIOpen off, mesh post-processing off. Needs a mask (from the image's alpha). Presets: base (Meta's config) and fast (`distill`, objects only: F 0.986 on the vase, 0.879 on the character).
  *Done when:* a real job on the vase writes `mesh.glb` in ≤ 80 s warm, and the result matches the lab mesh (F-score ≥ 0.99 at the same seed).
  - *As built:* stage 1 and stage 2 guidance and time rescale are set per job through the pipeline's `override_*_generator_cfg_config`. The pipeline's own methods are wrapped to announce `sam3do.pointmap/stage1/stage2/decode`. The mesh is geometry only (the model's vertex colours are dropped). Real, fast, vase: 79.3 s cold, 49.4 s warm (lab 50.8 s), 876 k faces, peak 19.3 GB, F 0.997 against the lab mesh.
- [x] **17.9 The page: `services/gen3d/ui/page.js`** (brief §5).
  - Engine picker in the composer (text engines vs image engines, with each engine's licence note); an image drop zone / Upload button and "Use as input" from Outputs; the settings menu shows the chosen engine's options from `/v1/options`; preset buttons base / fast.
  - Job cards show the input image next to the result; SAM 3D Body results get the rig viewer.
  *Done when:* in the browser, an image job runs from the page for each ready engine, and switching engines changes the settings shown.
  - *As built:* `ui/image.js` builds the engine's panel from `/v1/options` (presets, settings, face-budget shortcuts, licence, where it runs) with the shared `schemaForm`. The picture is an AIHub output: an upload goes through `POST /api/outputs/upload` first, so jobs always send `output:<id>`, and the job's title is that output's title. The engine is a dropdown (five labels don't fit a segmented control). An engine's first use starts with mesh + preview. The Jobs tab shows the engine, faces (and raw faces), the picture, and `mesh_raw.glb` as a second viewer tab. Checked in the browser: Hunyuan3D (82 s) and SAM 3D Body (19 s with ComfyUI's start) run from the page; TRELLIS.2 and SAM 3D Objects ran through the same `POST /v1/jobs` from the API. SAM 3D Body's armature isn't posed in the viewer (it shows the mesh).
- [x] **17.10 Agent and docs.**
  - `service.toml` `make_3d`: `engine`, `image` and `preset` arguments, description naming when to pick which engine (characters: Hunyuan3D; detailed objects: TRELLIS.2; pose/body: SAM 3D Body; objects in a scene photo: SAM 3D Objects); `skills/making-3d/SKILL.md` gets the same guidance.
  - Docs: architecture §10 (gen3d row), `services/gen3d/README.md` (engines, presets, timings), `docs/structure.md` (new files), brief §5 (the page).
  *Done when:* the agent eval has a case that makes a mesh from an uploaded image with the right engine; the contract test passes.
  - *As built:* the agent eval has two cases, `picture_object_to_3d` (TRELLIS.2) and `picture_character_to_3d` (Hunyuan3D), each 2/3 in dry runs with the 31B (docs/agent-eval.md). `make_3d` asks for `engine`, `preset` and `stages`, and its `image` is an AIHub file. gen3d also accepts a picture without an engine (TRELLIS.2) and a bare output id. The making-3d skill prefers an image engine when there is a picture.

**Wire — Phase 17:** the 3D Generate page gains the engine picker, image input and per-engine settings; image jobs show progress, ETA and the 3D viewer like Cube3D jobs; Outputs lists their meshes.

**Checks & deliverables — Phase 17**
- [ ] The same two lab images through every ready engine from the page, base and fast, within 15 % of the lab timings.
- [ ] Cube3D jobs, presets and follow-ups (parts, rig) work unchanged; `pytest` in `services/gen3d` and the hub suite pass.
- [ ] `aihub check gen3d` and `aihub check comfy` pass; memory accounting is right for local and delegated engines.
- [ ] Delivered: `gen3d/options.py` engines, `gen3d/comfy_engine.py`, `workers/hunyuan_worker.py`, `workers/sam3do_worker.py`, `workers/shims/`, the `trellis2-shape` and `sam3d-body` packs, the updated page, tests.

| Deliverable | Description | Location |
| --- | --- | --- |
| Engine options | per-engine parameters, base/fast presets | `services/gen3d/gen3d/options.py` |
| Engine workers | Hunyuan3D and SAM 3D Objects in their own containers | `services/gen3d/workers/hunyuan_worker.py`, `sam3do_worker.py` |
| Shims | pure-PyTorch spconv, import stand-ins | `services/gen3d/workers/shims/` |
| Delegation | TRELLIS.2 and SAM 3D Body through the comfy mod | `services/gen3d/gen3d/comfy_engine.py` |
| Packs | TRELLIS.2 shape, SAM 3D Body | `services/comfy/workflows/trellis2-shape/`, `sam3d-body/` |
| Tests | options, fake engines, delegation (fake hub), spconv equivalence | `services/gen3d/tests/test_*.py` |

---

# Stage F — vLLM

## Phase 18 — New `vllm` mod (vLLM)

vLLM serves Hugging Face models (safetensors, AWQ) with batching, prefix caching and native tool-call and reasoning parsers; llama.cpp (lcpp) stays the GGUF engine. Upstream vLLM doesn't support gfx1151, so the mod runs **kyuz0's patched image** `docker.io/kyuz0/vllm-therock-gfx1151` (ROCm from TheRock, vLLM `0.31.0+strix`), the same author as the ComfyUI image. The mod is a small FastAPI adapter that starts one vLLM container at a time, asks the hub for its memory first, downloads and registers models, and publishes the running model to the relay so Chat and the agent can use it. It follows the comfy and gen3d patterns (adapter + container, `containers` for memory) and lcpp's relay publishing. Touches architecture §2 (ports, mod ids), §10 (a new row), §7 (a new acquirer), and nothing in the hub's code.

**Smoke test (2026-10-15, by hand, before planning):** image `sha256:8002236ea752…` (built 2026-10-04, 12.4 GB), `podman run --device /dev/kfd --device /dev/dri --group-add keep-groups --security-opt seccomp=unconfined --ipc=host`, `VLLM_ROCM_USE_AITER=0`, `--attention-backend TRITON_ATTN`, `Qwen/Qwen3-0.6B`, `--gpu-memory-utilization 0.1 --max-model-len 8192 --max-num-seqs 4`: healthy after 130 s cold (torch.compile 16 s, CUDA graphs 3 s, the rest imports and the download), 134 tok/s single stream, 13.8 GB GTT used. `0.1` of the GPU meant 12.06 GiB (KV 10.81 + weights 1.12 + graphs 0.13), so vLLM's total is the GTT size (`amdgpu.gttsize=131072`, 121.5 GiB). Host prerequisites are already in place: that kernel parameter, `ttm.pages_limit`, and the user in `video` and `render`.

**Simple gaps (assumed):**
- **One model at a time.** *Assumption:* the mod runs at most one vLLM container; loading another profile unloads the current one first. Several at once can come later (memory makes it rare).
- **Image version.** *Assumption:* pinned by digest in `service.toml` (`VLLM_IMAGE`); `:latest` moves, and its README warns the `dev` tag regresses. Updating is a manual edit plus the 18.7 checks. The image is outside the project, which the Phase 12.4 allowlist already covers (podman images).
- **Ports.** *Assumption:* the adapter on **5101** (5100 is `agent`), the vLLM server on **7801** (`VLLM_ENGINE_PORT`), outside the new-mod range so `aihub new` never picks it. The container uses `--network host` and vLLM binds `127.0.0.1`, so nothing is exposed and there's no port mapping (the smoke test's mapped port saw requests from the host's public address).
- **Model files.** *Assumption:* vLLM's native Hugging Face cache, `HF_HOME={hf_home}` (`data/models/hf-cache`), registered like Kokoro and Whisper: `format: hf-dir`, `kind: llm`, `services: ["vllm"]`, with the repo and revision as `source`. Not `[models] dirs`, which would claim every model in the shared cache.
- **Caches.** *Assumption:* Triton and vLLM's torch.compile caches go in `data/state/vllm/cache/` (runtime state, plan 16), so the second start of a profile skips compiling. Not in backups.
- **Stopping.** *Assumption:* stopping the mod (SIGTERM) stops the engine, since stopping is how memory is freed; an adapter crash leaves the container running, and the next start adopts it by label.
- **Never unloaded automatically.** *Assumption:* `vllm` joins `config.toml [memory] never_unload`, like lcpp: a reload takes minutes, and a chat between requests looks idle. Unload is by hand (page, agent tool, Stop).
- **When unloaded,** the relay registration is removed, so the model leaves `/v1/models`; a client that calls it gets the relay's unknown-model error. Loading on demand from the relay is out of scope.
- **Downloads.** The user approved Qwen3-0.6B (done) and Qwen3.6-35B-A3B AWQ 4-bit (~20 GB) for this phase on 2026-10-15. Any other model is downloaded only when the user loads its profile.

- [x] **18.1 Scaffold and profiles: `services/vllm/`.**
  - `aihub new vllm --port 5101 --name "vLLM"`, then the package `vllm_mod/` (`settings.py`, `profiles.py`, `server.py`); `aihub-install.sh` makes the adapter venv (fastapi, uvicorn, httpx, pydantic, huggingface_hub) and runs `podman pull` of the pinned digest when it's missing.
  - **`service.toml`:** `[run] command = [".venv/bin/python", "-m", "vllm_mod", "--port", "{port}"]`, `health = "/health"`, `status = "/v1/status"`, `after = ["relay"]`, `stop_timeout_s = 60`; `[run.env]` `VLLM_IMAGE` (the digest), `VLLM_ENGINE_PORT = "7801"`, `VLLM_STATE_DIR = "{root}/data/state/vllm"`, `HF_HOME = "{hf_home}"`; `[memory]` `load = "POST /v1/load"`, `unload = "POST /v1/unload"`, `containers = ["aihub-vllm-*"]`, `estimate_gb` = the default profile's, `idle_unload_s = 0`.
  - **Profiles** are TOML files in `services/vllm/profiles/<id>.toml`, like workflow packs: `name`, `model` (HF repo), `revision`, `served_name`, `alias` (the relay alias), `memory_gb`, `max_model_len`, `max_num_seqs`, `attention_backend`, `enforce_eager`, `trust_remote_code`, `tool_parser`, `reasoning_parser`, `env = {…}`, `extra_args = […]`. Unknown keys are errors. `Profile` (pydantic) in `profiles.py`; `load_profiles(dir)` returns profiles plus per-file problems.
  - **Seed profiles** from kyuz0's `models.py` in the pinned image: `qwen3-0.6b` (the smoke settings) and `qwen3.6-35b-a3b-awq` (`cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`: `enforce_eager`, `trust_remote_code`, `--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3`, `max_model_len` 65536, `max_num_seqs` 4; `memory_gb` measured in 18.7).
  - **`engine_command(profile, settings, gtt_total_bytes)`** builds the `podman run -d` line: name `aihub-vllm-<profile id>`, labels `aihub.mod=vllm` and `aihub.profile=<id>`, the smoke test's device, group and security flags, `--network host --ipc host`, mounts for `HF_HOME` and the cache dir, `VLLM_ROCM_USE_AITER=0`, `VLLM_ROCM_USE_AITER_LINEAR=0`, `TRITON_CACHE_DIR`, `VLLM_CACHE_ROOT`, the profile's `env`, then `vllm serve <model> --host 127.0.0.1 --port <engine port> --served-model-name <served_name> --gpu-memory-utilization <memory_gb × 10⁹ / gtt_total>` and the profile's flags. `gtt_total` comes from `/sys/class/drm/card*/device/mem_info_gtt_total`.
  - Routes: `GET /health`, `GET /v1/profiles` (with which are downloaded), `GET /v1/status` (unloaded).
  *Done when:* `services/vllm/tests/test_profiles.py` covers parsing, unknown keys, the seed profiles, and `engine_command` (utilization math, no port mapping, labels, mounts, flags); `aihub check vllm` passes.
  - *As built:* the installer is `install.sh` (the template's name), and `[memory]` and the page wait for 18.2 and 18.6, whose routes they name. The image is mounted with `label=disable` and same-path mounts, like gen3d's workers. `--revision` and `--served-model-name` are always passed. Seed `memory_gb`: 12 for the 0.6B (the smoke test) and 40 for the AWQ until 18.7 measures it. `aihub check vllm`: all checks passed; 5 tests.
- [x] **18.2 Engine lifecycle: `vllm_mod/engine.py`.**
  - `Engine.load(profile_id=None)` (default: the last loaded, kept in `data/state/vllm/last.json`, so a session restore's plain load brings it back): unload anything else, ensure the model is downloaded (18.3), `POST {AIHUB_URL}/api/memory/acquire?make_room=1` for `memory_gb` + the process overhead measured in 18.7 (a `409` fails the load with the hub's message), `podman run -d`, then poll the engine's `/health` with `stages` read from its log (`downloading`, `loading weights`, `compiling`, `capturing graphs`, `ready`); the timeout is 20 min (a first compile).
  - `Engine.unload()`: `podman stop -t 30`, then `podman rm -f`. SIGTERM to the adapter does the same before it exits.
  - **Adoption:** on start, `podman ps --filter label=aihub.mod=vllm` adopts a running container (state from its `/health`) and removes exited ones.
  - **Logs:** a follower runs `podman logs -f` on the container and writes its lines to the adapter's stdout with an `engine:` prefix, so they reach `data/logs/vllm.log` and the Logs tab. `GET /v1/engine/logs?tail=` returns the last lines.
  - **Crashes:** a container that exits on its own sets `failed` with its last 30 log lines in `status.last_error`, and is removed.
  - **Fake engine:** `VLLM_FAKE=1` runs `vllm_mod/fake_engine.py` (health, `/v1/models`, `/metrics`, a streaming `/v1/chat/completions`) as a subprocess instead of podman, for tests and `--demo-mods`.
  - Routes: `POST /v1/load` (`{"profile": "<id>"}`, optional), `POST /v1/unload`.
  *Done when:* `tests/test_engine.py` (fake engine, the hub faked with `httpx.MockTransport`) covers load, unload, switching profiles, adoption after an adapter restart, a crash, `409 needs_room`, and the startup timeout; the Load and Unload buttons on the generic page work against the fake.
  - *As built:* `vllm_mod/containers.py` holds `Podman` and `FakeContainers` (the fake engine as a detached process with its pid and log in `data/state/vllm/fake/`, so it can be adopted too). **podman runs in its own transient scope** (`systemd-run --user --scope`, unit `aihub-vllm-<profile>-<ts>.scope`): otherwise conmon stays in the adapter's unit, is killed with it, and the engine's output lands in the mod's journal twice. The load route takes `wait` (default true: the hub's own load waits for ready) and `make_room` (or the `X-AIHub-Make-Room` header the page's `callRoom` sends); a `needs_room` from the hub is passed on unchanged. Stages: starting container, initializing, loading weights, compiling, capturing graphs, allocating KV cache, warming up, starting server. Also `GET /v1/engine`. Real, through the hub's own Load with the 0.6B: 108 s cold (vLLM's compile cache empty), **57 s warm**; the hub measured 16.2 GB for `memory_gb` 12, so the default overhead stays 4 GB. `kill -9` of the adapter: systemd restarted it, the engine kept serving, and the new adapter adopted it (ready, chat answered, logs followed). 12 tests.
- [x] **18.3 Downloads and the registry: `vllm_mod/downloads.py`.**
  - Before a load, a model missing from the HF cache is fetched in the adapter with `huggingface_hub.snapshot_download` (only `*.safetensors`, `*.json`, tokenizer and template files), so download time never holds a memory grant. Progress (bytes done of the repo's total) is a status job; `POST /v1/downloads` (`{"profile"}`) starts one without loading.
  - When it finishes, the adapter registers the model: `POST {AIHUB_URL}/api/models` with `path: "hf-cache/hub/models--<org>--<name>"`, `kind: "llm"`, `format: "hf-dir"`, `services: ["vllm"]`, `source: {type: "huggingface", repo, revision}` (the resolved commit). `409 model_exists` counts as done.
  - The engine starts with `HF_HUB_OFFLINE=1` once the files are local, so a start never downloads inside the container.
  *Done when:* `tests/test_downloads.py` (a patched `snapshot_download`, the fake hub) covers progress, registration, the already-registered case, and a failed download failing the load; the 0.6B from the smoke test is registered and shows "used by vllm" on the Models page.
  - *As built:* a finished download is recorded in `data/state/vllm/downloads.json` (`repo@revision` → commit) and counts as local while that snapshot folder exists; progress is the repo's blob folder against the allowed files' total from `model_info`. The entry lists the snapshot's files (roles weights, config, tokenizer, other) and is named `<repo> (vLLM)`. `GET /v1/downloads` and each profile's `downloaded`, `local_bytes` and `download` in `/v1/profiles`; the engine's stage is `downloading` meanwhile, and a failed download fails the load before any memory is asked for. Live: the smoke test's 0.6B was checked and registered in 0.5 s (`qwen-qwen3-0.6b-vllm`, 1.52 GB, used by vllm); the AWQ profile's repo is 25.0 GB. 20 tests.
- [x] **18.4 Publishing to the relay: `vllm_mod/relay.py`.**
  - When the engine is ready: `PUT {relay}/admin/registrations/vllm:<engine port>` with `name` (profile id), `host`, `port`, `alias`, `available_models: [served_name]`, `server_type: "vllm"`, `owner: "vllm"`, `meta.manager_url` (`http://127.0.0.1:7000/#/s/vllm`). `DELETE` when an unload starts and again when the engine is gone; on adapter start, reconcile with `GET /admin/registrations?owner=vllm`. A relay that is down leaves the registration pending, with one retry loop and capped backoff (lcpp's design in `services/lcpp/src/lcpp/relay.py`, written again here: mods don't import each other).
  - The relay's model facts (plan 13.3) read vLLM's `max_model_len` from `/v1/models` directly; check that `meta` shows the profile's context, tools and reasoning, and add a `facts_override` only if it doesn't.
  *Done when:* `tests/test_relay.py` (a fake relay) covers register, unregister, relay down then back, and reconcile; with the 0.6B loaded, the relay's `/v1/models` lists it with `context_length` 8192, and a chat through `:4000` answers.
  - *As built:* the endpoint is named `vllm-<profile>` with `server_type: "vLLM"` (the relay's spelling). vLLM's `/v1/models` gives the context but not tools or thinking, so after each registration the adapter sets the endpoint's `facts_override` (`PATCH /admin/endpoints/{id}`) from the profile's parsers, only when it changed. `VLLM_RELAY_URL=""` turns publishing off (the tests' default, so they never touch the live relay). `/v1/engine` carries the registration's state. Live: `Qwen3-0.6B-vLLM` and `qwen3-0.6b` in the relay's `/v1/models` with `context_length` 8192, `tools` and `reasoning` true (source `vllm`); a chat through `:4000` answered with the thinking split into `reasoning`.
- [x] **18.5 Status, stats and tools.**
  - `GET /v1/status` (architecture §4.6): `loaded` (the engine is ready), `busy` (vLLM's `num_requests_running` > 0), `idle_s`, `memory_estimate_gb` (the current or default profile), `stats` (Model, Tokens/s from the generation-token counter's rate, Requests, KV cache %), and `jobs` for downloads and starts (with stages).
  - `vllm_mod/metrics.py` parses vLLM's Prometheus `/metrics`; the fixture is captured from the pinned image (`tests/fixtures/metrics-0.31.txt`).
  - `[tools]`: `list_profiles` (read), `load_llm` (`POST /v1/load`, write, `ask = ["profile"]`), `unload_llm` (`POST /v1/unload`, `confirm = true`).
  *Done when:* `tests/test_status.py` covers each state and the metrics parsing against the fixture; `aihub check vllm` validates the status shape and the tools; the tile shows tokens/s while a request runs.
  - *As built:* `vllm_mod/metrics.py` (`parse`, `summary`, `Sampler`: every 2 s while ready, tokens/s over the last 10 s, idle since the last token or queued request). Stats: Model (the served name, or "none"), Tokens/s, Requests (hint: waiting), KV cache %. Jobs: each download and each start (its stage as progress), kept 10 min after they finish. A fourth tool, `engine_status`; `load_llm` is sent with `wait=false` (a start takes minutes) and `make_room` hidden. The profile routes for 18.6 (`GET /v1/profiles/schema`, `PUT`/`DELETE /v1/profiles/{id}`, `vllm_mod/api_profiles.py`, saved with tomlkit so comments stay) landed here too. Fixture: the pinned image's `/metrics` after three requests (`vllm:` lines only). `aihub check vllm`: 12 operations, 4 stats, all checks passed. 29 tests.
- [ ] **18.6 The page: `services/vllm/ui/page.js`** (brief §5; `/mod-kit.js`, `/mod-form.js`, `/mod-charts.js`).
  - **Profiles tab:** a card per profile (model, downloaded or its size, memory, context, parsers) with Load / Unload / Download; the loaded one shows its stages while starting, then its endpoint, served name and relay alias. Editing a profile is a `schemaForm` from `GET /v1/profiles/schema`, saved with `PUT /v1/profiles/{id}` (`DELETE` to remove a profile; never its downloaded files, which stay on the Models page).
  - **Engine tab:** the running command line, a live log tail (`GET /v1/engine/logs`, polled), and charts of tokens/s and KV cache % from the stat series.
  *Done when:* in the browser, the 0.6B loads from the page with its stages, a profile edit round-trips to its TOML file, and the engine log streams.
- [ ] **18.7 Live check and docs.**
  - Load `qwen3.6-35b-a3b-awq` from the page (the ~20 GB download the user approved): record the cold start (download, compile) and the warm start (cached compile), single-stream tokens/s, 4 concurrent requests, and the hub's measured memory against `memory_gb`. Set the profile's `memory_gb` and the overhead in 18.2 from the measurement.
  - Chat with it on the Chat page through the relay: an answer with thinking split out (`reasoning`), and a tool call (generate an image) parsed natively.
  - Restart the adapter (`aihub restart vllm`: the engine stops, which is expected) and the hub (`aihub restart`: the engine keeps running and is still published); save a session with the model loaded, unload it, and restore the session.
  - **Docs:** architecture §2 (mod ids and ports: `vllm` 5101, engine 7801) and §10 (a `vllm` row), `services/vllm/README.md` (profiles, the image, timings), `docs/structure.md`, `CLAUDE.md` status, the `aihub` skill's port list, `config.toml` (`never_unload`, `[services] order`).
  *Done when:* each check above is done and its numbers are in the README; `uv run pytest` and `pytest` in `services/vllm` pass.

**Wire — Phase 18:** the vLLM page (Profiles and Engine tabs) and its tile (model, tokens/s, KV cache); its model in the relay's endpoints and in Chat's model list while loaded; its memory on the Memory page; its downloads on the Models page.

**Checks & deliverables — Phase 18**
- [ ] `aihub check vllm` passes, and the generic tabs (API, Logs, Settings) work.
- [ ] Loading vLLM when memory is short shows the Make-room plan; it is never unloaded automatically.
- [ ] Deleting `services/vllm/` and running `aihub rescan` removes the mod; its registered models stay (with `services` pointing at a missing mod, like any orphan).
- [ ] Delivered: `services/vllm/` (adapter, profiles, page, tests, README), the two seed profiles, the docs updates.

| Deliverable | Description | Location |
| --- | --- | --- |
| Adapter | profiles, the engine container, downloads, relay publishing, status | `services/vllm/vllm_mod/` |
| Profiles | one TOML per model setup | `services/vllm/profiles/*.toml` |
| Page | Profiles and Engine tabs | `services/vllm/ui/page.js` |
| Fake engine | vLLM's routes for tests and `--demo-mods` | `services/vllm/vllm_mod/fake_engine.py` |
| Tests | profiles, engine lifecycle, downloads, relay, status (fake engine, fake hub, fake relay) | `services/vllm/tests/test_*.py` |

---

# Stage G — Chat activity

## Phase 19 — Chat activity: steps, not cards

Today the Chat page draws every agent event as its own card at the same level: thinking, each tool call, each result, notes. A five-step turn is 10–20 stacked cards, nothing shows while the model thinks (with Show thinking off), and the agent's own lookups look like real work. This phase redraws a turn the way Claude, ChatGPT and Gemini do: **one fold per turn** whose header always says what's happening now, a list of plain-language steps inside it, and the work's results, the answer, and anything that needs you outside it.

The look was chosen on 2026-10-19 from a design study: `web/design/chat-activity.html` on the hub, built from the real chat kit and a real event log. Its **Your mix** section is the target. The picks:

| Part | Pick | What it means |
| --- | --- | --- |
| 1. Activity block | **A, closed to start** | One fold per turn, **closed by default, including while it runs**. Its header is the live status ("Generating an image… 42% · 0:17"), then the summary ("Ran 2 tools · 2m 58s"). Opened, it lists the steps: thinking, the agent's short updates, tool calls. |
| 2. Opening a step | **2b, one sentence** | "Generated with **Z-Image Turbo**, square, seed 81723, from this prompt:", the prompt quoted, the result as `#n` chips, then "Raw call" for the JSON. |
| 3. Thinking | **3a + 3c** | A spinner (not the bulb), "Thinking…", the seconds counting up, and the last two lines of thought peeking under it. Afterwards: "Thought for 4s ›", which opens to the text. |
| 4. Outputs | **4c, strip + one big** | A strip of `#n` thumbnails when a turn made more than one output; the picked one (by default the newest) as the result card, its preview **capped at about 300 px**. |
| 5. Lookups, retries, notes | **5b, muted, in plain words** | Every step is a row; lookups are grey; an error is a sentence ("Couldn't make the 3D model: Cube3D can't use a picture"), with the code under Raw; the agent's notes are muted rows. |
| 6. Approvals | **6c, docked on the composer** | A pending approval waits above the message box, like Claude Code's permission prompt; the fold's header says "Waiting for you to approve below". |

All of it lives in `web/chat/`. The agent's events (`services/agent/agent/store.py`) already carry what's needed (a `step` id on thinking, text and tool calls; the call id on results; `ts` on every stored event), so nothing changes in the agent or the hub. Touches brief §11.13 and `web/PATCHES.md`; architecture §14 is unchanged.

**Simple gaps (assumed):**
- **Closed while running.** *Assumption:* the fold starts closed for every turn, the running one included; the header carries the live status and the thinking peek. What you open stays open for that turn until the page reloads (not saved).
- **Show thinking.** *Assumption:* the setting is retired. Thinking is always one row in the steps (closed), and the peek shows only while it streams. Settings → Agent loses the toggle; `aihub.chat.showThinking` is ignored.
- **Questions** (`ask_user`) dock above the composer like approvals, and so do parameter cards opened by a button or a quick action. Everything that waits for you sits in one place.
- **Tool words** (running and done labels, the detail, the sentence) come from a UI registry with built-ins for the tools that exist today, and a generic fallback built from the catalog (the tool's title and its schema's property titles). A field in a mod's manifest for these words would touch the tool catalog, which the capability work (the other session: engine and workflow capabilities in tool schemas) owns. *Assumption:* not in this phase. Engine and workflow ids show as names through a small built-in map until the schemas carry labels; then the registry reads those labels.
- **The design study** stays in `web/design/` while this phase is built (as the reference), and is removed in 19.7 once screenshots of the built page replace it. It imports the chat modules, so it would break as they change.
- **Phase number.** *Assumption:* 19. If the capability work adds a phase first, renumber this one.

**Out of scope (the capability session's work):** which engine or workflow the agent picks, tool schemas, the agent's prompt. Turning the image result's "Make 3D" from a prompt into a tool action (it was a prompt because gen3d was text-only) waits for that work's schema.

- [x] **19.1 The design study and the mock turn.** *As built:* the mock catalog's `gen3d_make_3d` takes `image` and `engine` like the real one; the mock agent's chain turn starts on a message naming 3D with "then" or "into".
  - **Commit the study:** `web/design/chat-activity.html` with `activity-model.js`, `activity-kit.js`, `activity-options.js`, `activity-parts.js`, `activity-mix.js`, `chat-activity.js` (a page served by the hub, linked from nowhere). Add a `docs/structure.md` row.
  - **The scripted mock agent** (`web/chat/chat-mock.js`) plays the study's sample turn on `?mock`: "Make me a samurai character, then turn it into a 3D model". It streams thinking deltas, calls `find_tools` and `load_tools`, streams a short update, generates an image with progress, asks for an approval for `gen3d_make_3d`, runs it with progress, streams the answer. Every state in the study is then reachable in the real page. Keep the existing scripted flows (question, parameter card, fork) for their tests.
  - **Fix:** the live `thread` event carries the thread object itself as its payload (`loop.py`), but `chat.js` reads `e.payload?.thread`, which only the mock sends. Read both, so a model-made title shows as soon as it's made.
  *Done when:* `/design/chat-activity.html` loads with no console errors; `utils/tests/web/chat.test.mjs` covers the new mock turn (its event types, in order, with a pause at the approval) and the title fix; `uv run pytest` passes.
- [x] **19.2 Turns and steps: `web/chat/chat-turn.js`** (pure, like `chat-thread.js`). *As built:* `buildView` keeps `resultTs`, `decisionTs` and `answerTs` for the durations; a tool call's time counts from its approval; agent errors are kept per turn (`errors`) to draw outside the fold; the sample log is a test fixture (`utils/tests/web/chat-sample.mjs`).
  - **`groupTurns(view, { running, now })`** takes `buildView`'s items (tool calls with their approval, decision, result and progress already folded in) and returns turns: `{ key, user, steps: [{ id, thinking, narration, rows }], answer, outputs, pending, status, summary, elapsed }`.
  - **Turn boundaries:** a `user` item starts a turn, and so does a tool call `by: "user"` (a result button or quick action: "You ran Upscale image"). A queued message starts the next turn. Compaction marks and errors outside a turn stay items of their own.
  - **Steps** group by the `step` id on thinking, assistant and tool-call payloads. Rows are thinking, the agent's update text, tool calls, notes, `remember` ("Remembered: …"), `update_todos` ("Updated the plan"; the Plan bar stays) and questions.
  - **The answer** is the last step's text when that step called no tools; text in a step with tools is an **update** row. Streaming deltas fill either one, as now.
  - **Status** while running, in order: waiting for you (an approval or question) → the running tool that isn't a lookup (its label, percent, note) → a running lookup → writing the answer → thinking (from the thinking delta's `t0`, so the seconds count from when it started) → "Working" before anything has arrived.
  - **Summary** when done: "Ran N tools" counting only tools that aren't lookups ("Looked something up", "Thought it through" otherwise), and the turn's time from the user event's `ts` to the last event's.
  - **Lookups:** `find_tools`, `load_tools`, `read_skill`, `view_output`, `read_result`, `comfy_list_workflows`, and `hub_*` tools whose risk is `read`.
  *Done when:* a new `utils/tests/web/chat-turn.test.mjs` (run from pytest like `chat.test.mjs`) covers the sample turn at each of the study's seven stages (status text, percent, summary, answer vs update), a button-started turn, a queued message, the retry turn from the study (error, note, retry), and a replay giving the same turns.
- [ ] **19.3 Step words: `web/chat/chat-steps.js`.**
  - **Registry:** `registerStep(toolName, { running, done, icon, detail(args, ctx), sentence(args, ctx), lookup })`. For example `comfy_generate_image` → "Generating an image" / "Generated an image", detail "Z-Image Turbo · 1:1", sentence as in Part 2.
  - **Built-ins** for today's tools: the comfy tasks (generate, edit, animate, video, remove background, upscale, `run_workflow`), `gen3d_make_3d` ("Made from #1 with TRELLIS.2, balanced preset (shape, texture)."), tts speak, lcpp / vllm load and unload, the agent's lookups, `hub_*`.
  - **Fallback for any other tool:** "Running <title>" / "Ran <title>", and a sentence from the schema's property titles, with `output:<id>` values shown as `#n` chips.
  - **Errors in plain words:** the result's `error.detail` is the row's sentence and `fix` is under it. The code and the raw call are under "Raw call".
  - Exported from `chat.js` next to the other registries (the modularity contract).
  *Done when:* `chat-turn.test.mjs` also covers the built-in words for the sample turn, the fallback for a tool with no entry (from a catalog schema), a registered override, and an error row's sentence.
- [ ] **19.4 The activity fold: `web/chat/chat-activity.js`.**
  - **`ActivityFold({ turn, ctx })`:** the header button (spinner, the shimmering status, percent, elapsed counting up each second, chevron; then the tool icon, summary and time once done), closed by default; while thinking and closed, the two-line peek under the header.
  - **Opened:** the step list with a left rule. Thinking rows (spinner, "Thinking…", live seconds and the peek while streaming; "Thought for 4s ›" after, opening to its Markdown, muted). Update rows (Markdown). Tool rows (status mark, label, grey detail, percent or time, "needs you" while waiting, chevron), lookups and notes grey. A running tool shows its progress bar under its row.
  - **A tool row opens to its sentence (2b)** from 19.3, with the `#n` chips and "Raw call" (the arguments and the result envelope as JSON).
  - **`registerCard('step:<tool>')`** replaces one tool's opened detail (the brief's card lookup, extended).
  - **The thread** (`chat.js`) draws per turn: the user card, the fold, the output strip (19.5), the answer. The per-card Stop buttons go; Stop is the composer's.
  - The "working" dots go: the header always says something while a turn runs.
  - `ToolCard` and `ThinkingCard` leave `chat-cards.js`, and the Show thinking toggle leaves `chat-settings.js`.
  - Keep files under ~500 lines: rows and the detail can live in `chat-steps.js`, and the fold in `chat-activity.js`.
  *Done when:* in `?mock`, the sample turn plays through every state with the fold closed and the header correct at each, opening it shows the steps, and a step opens to its sentence; a reloaded finished chat shows each turn folded with its summary; `chat.test.mjs`'s card-registry test is updated for `step:<tool>`; `uv run pytest` passes.
- [ ] **19.5 The output strip: `web/chat/chat-results.js`.**
  - **`OutputStrip({ outputs, ctx })`** under the fold: 56 px `#n` thumbnails when the turn made more than one output, the selected one (by default the newest) as the existing result card.
  - Its preview is capped at 300 px tall (a `maxHeight` option on the previews, default unchanged elsewhere). The 3D viewer opens at its own height.
  - Previews, actions and `registerPreview` are unchanged.
  *Done when:* in `?mock` the sample turn shows the strip (#1, #2) with #2 large and capped, clicking #1 swaps them, and the actions still open their parameter cards; a turn with one output shows no strip; a Node test covers the default selection.
- [ ] **19.6 The dock: pending cards above the composer** (`web/chat/chat-composer.js`, a `dock` slot; `chat.js`).
  - **What docks:** pending approvals (the real `ParamCard`), questions and button-opened parameter cards sit in the dock, newest first, with "1 of 2" when there are several. The dock is at most half the page tall and scrolls.
  - **In the thread:** the fold's header says "Waiting for you to approve below" (or "…to answer below"). The step row shows "needs you", then "Approved by you" / "Cancelled by you" in its sentence once decided.
  - Ctrl+Enter still runs. Deciding in the header's Approvals popover clears the dock too, since both read the same events.
  - On narrow pages the dock goes full width above the box.
  *Done when:* in `?mock`, the 3D approval docks, Run continues the turn and the card leaves the dock; a reload while it waits brings the docked card back; a question docks and its answer lands as a step row; deciding from the header popover clears the dock.
- [ ] **19.7 Live check, docs and the reference.**
  - **Live:** on the real agent, "make a samurai character, then turn it into a 3D model". Check every state against the study's Your mix, in both themes and at phone width (375 px). Also a turn with a failed call and a retry, and a turn started from a result button.
  - **Screenshots** of the built page (each state, dark and light) in `docs/reference/chat-activity-2026-10/`, replacing the study. Then delete `web/design/`.
  - **Docs:**
    - brief §11.13 rewritten as built: the fold, step words and `registerStep`, the strip, the dock, Show thinking retired, `step:<tool>` in the card lookup;
    - a `web/PATCHES.md` entry;
    - `docs/structure.md` (the new `chat-turn.js`, `chat-steps.js`, `chat-activity.js`; `web/design/` removed; the reference folder);
    - the `CLAUDE.md` status.
  *Done when:* each live check passes and the screenshots are in; `uv run pytest` passes.

**Wire — Phase 19:** the Chat page's thread view on the live agent: one fold per turn with a live header, plain step rows that open to a sentence, the output strip, and the dock above the composer. The Settings → Agent page without Show thinking.

**Checks & deliverables — Phase 19**
- [ ] While a turn runs, the header is never blank: from the moment you send to the answer, it names what's happening and counts the time.
- [ ] A finished turn is one line ("Ran 2 tools · 2m 58s") plus its outputs and the answer; nothing about the work shows unless you open it.
- [ ] Every step a turn took is reachable in two clicks (open the fold, open the step), and its raw call in three.
- [ ] Old chats (made before this phase) draw correctly from their stored events.
- [ ] Delivered: `web/chat/chat-turn.js`, `chat-steps.js`, `chat-activity.js`, the strip and the dock, the mock turn, `utils/tests/web/chat-turn.test.mjs`, the reference screenshots, the docs updates.

| Deliverable | Description | Location |
| --- | --- | --- |
| Turn model | `buildView` items → turns, steps, status, summary (pure) | `web/chat/chat-turn.js` |
| Step words | the `registerStep` registry, built-ins and fallback; rows and sentences | `web/chat/chat-steps.js` |
| Activity fold | the per-turn fold and its step list | `web/chat/chat-activity.js` |
| Strip and dock | the output strip; pending cards above the composer | `web/chat/chat-results.js`, `chat-composer.js` |
| Mock turn | the study's sample turn on `?mock` | `web/chat/chat-mock.js` |
| Tests | the turn model at every stage, step words, the mock turn, the registries | `utils/tests/web/chat-turn.test.mjs`, `chat.test.mjs` |
| Reference | screenshots of the built page | `docs/reference/chat-activity-2026-10/` |

---

## Testing approach

- **Unit tests** for each `utils/` module, run against a temporary project root.
- **Fake mods** (Phase 1.7) cover everything, run under the subprocess backend. Tests that need systemd are marked, and skipped where systemd isn't available.
- **Real OpenAPI fixtures** from the four apps (Phase 0.5) keep the operations converter honest.
- **The contract test** (6.6) keeps the backend and `web/api.js` in step. `api.js` has its own Node unit tests (1.9).
- **The browser checks** in each phase's "Checks & deliverables" are run against the live backend, with `AIHUB_LIVE_AREAS` covering every area wired so far.
- **The agent** (Stage D) is tested against a scripted OpenAI-compatible fake model, including a process kill and resume, plus a recorded live smoke run.
- **Each moved app keeps its own test suite**, run from its folder: relay 154, lcpp 82, gen3d 25, and the new tts tests.
- **A smoke check** (`aihub doctor --e2e`):
  1. start `_template` as a temporary mod
  2. call it through the proxy
  3. write an output and see it indexed
  4. load and unload a `fake-mem` mod
  5. tear everything down

## Definition of done

**Stages A–C (the hub and the apps):**
1. Every route in brief §6 and §11.7 is implemented with matching shapes, and the contract test passes.
2. The whole Part A UI (revision 2: compact, graphical, four Overview views) runs live, and each mod's Part B page is live.
3. `relay`, `opencode`, `lcpp`, `tts`, `gen3d` and `comfy` all run as mods under `aihub.service`, and the old systemd units are disabled.
4. All models live under `data/models/` and are in the registry; all databases are under `data/databases/`; new outputs from every mod land in `outputs/` and appear on the Outputs page.
5. Loading something that doesn't fit triggers a make-room plan instead of an out-of-memory error.
6. `aihub new <id>` creates a working mod, with a page, a tile and charts of its numeric stats, with no change to AIHub's own code.

**Stage D (chat):**

7. Chat works with our own agent through the relay: it asks for choices, shows parameter cards, chains outputs, keeps the context window in view, and its threads, questions and approvals survive restarts, with rewind/branch.
8. Sessions can be saved, switched and restored (optionally at boot) through the memory manager.
9. Logs and runtime state live in `data/`, and `aihub doctor --inventory` lists only the allowlist.
