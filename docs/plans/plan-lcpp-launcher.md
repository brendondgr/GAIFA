# Plan: lcpp Launcher + DashLLM Relay Integration

## 1. Introduction

This repository runs llama.cpp as one systemd router (`llamacpp-router.service`, port 7070), configured by `llamacpp.json` and driven by `scripts/llamacpp.py` through six symlinked `llamacpp-*` commands. That setup allows one server with one fixed port. It gives no way to run several models on ports you choose. It also has no UI, and nothing connects it to the DashLLM relay (`~/Tools/DashLLM`, port 4000), which has a hand-added `llama.cpp · local` endpoint pointing at `:7070`. This plan replaces all of that with **lcpp**, a small background service. You can start, stop and inspect llama.cpp servers on any port, through either a unified `lcpp` CLI or a web UI. Each running server can register itself with the relay and remove itself again.

The approach has three parts. First, this repo is restructured (`models/`, `data/`, `web/`) and the existing config logic is moved into a tested Python package. Second, a lightweight FastAPI daemon (`lcppd`, bound to `127.0.0.1:7700`) supervises llama-server instances as **transient systemd user units**. The daemon starts at boot, loads no models, and sits idle until it is asked to do something. The `lcpp` CLI is a thin, stdlib-only client of the daemon's API, so it starts almost instantly. Third, DashLLM gets an idempotent, owner-scoped **registration API** that lcpp calls when an instance becomes ready and when it stops. The UI is designed with Claude Design (`/design`) and implemented as a no-build static site in `web/`. Every step finishes with validation and a push to GitHub.

### Architecture at a glance

```
             ┌──────────── lcpp (this repo) ────────────┐         ┌──── DashLLM relay (:4000) ────┐
  lcpp CLI ─▶│ lcppd  FastAPI  127.0.0.1:7700           │  PUT/   │ /admin/registrations/{key}    │
  browser  ─▶│  ├─ /api/*   (instances, models, relay)  │─DELETE─▶│ endpoints table (owner=lcpp)  │
             │  ├─ /        (static web/)               │         │ /v1  ──proxy──┐               │
             │  └─ supervisor ─ systemd-run --user ─┐   │         └───────────────┼───────────────┘
             └──────────────────────────────────────┼───┘                         │
                          lcpp-<name>.service  ◀────┘  llama-server :<port>  ◀─────┘
```

### Key design decisions (with rationale)

| Decision | Choice | Why |
| --- | --- | --- |
| Service framework | FastAPI + uvicorn (no `[standard]` extras) | This matches your recommendation and DashLLM's stack. Idle cost is one Python process at about 40–60 MB RSS and 0% CPU. |
| How instances run | Transient systemd user units (`systemd-run --user --unit lcpp-<name>`) | Instances survive daemon restarts and upgrades, log to journald, and are killed cleanly by cgroup. They never outlive a reboot, so no model loads at boot. |
| Runtime state | `$XDG_RUNTIME_DIR/lcpp/instances/*.json` (tmpfs) | This state is cleared automatically on reboot, which matches the rule that nothing runs at boot. The daemon rebuilds its view from these files plus `systemctl --user list-units 'lcpp-*'`. |
| CLI | stdlib-only (`argparse` + `urllib`), lazy imports | `lcpp status` should return in under about 150 ms. It never imports FastAPI. |
| Frontend | No-build static HTML/CSS/ES modules in `web/`, served by the daemon | There is no Node toolchain to run and nothing to build. The UI polls only while its tab is visible, so the daemon sees no load when nobody is looking. |
| Instance kinds | `single` (one model, `-m`) and `router` (preset + `--models-max`) | `single` covers "any model on any port". `router` keeps the current `:7070` behavior available as a normal instance. |
| Relay coupling | lcpp calls relay; relay never calls lcpp | Each service stays usable without the other. Relay already persists endpoints in SQLite, so only lcpp needs to retry. |

---

## 2. Gaps & Unanswered Questions

- **Claude Design / `/design` availability**: No `/design` skill is loaded in this session. Claude Design runs as an interactive, canvas-based design flow, so Step 10 needs you to run `/design` (or approve using the Artifact "design" type) and pick a direction. *Human intervention is needed to answer this question.*
- **Network exposure of the lcpp UI/API**: *Resolved (user)*: this machine only. The daemon always binds `127.0.0.1:7700`, and instances always bind `127.0.0.1`. There is no host option in the CLI, the UI or `data/lcpp.json`.
- **UI-driven API additions** (from [design-brief-lcpp-ui.md](design-brief-lcpp-ui.md) §6): `GET /api/overview`, `POST /api/instances/preflight`, router `models/{id}/load|unload`, `POST /api/chat` (streaming playground proxy, direct or via relay), `GET/PUT /api/settings`, `GET /api/recent`, `POST /api/models/validate`, `PUT /api/models/defaults`, `POST /api/relay/test|cleanup`, and `DELETE /api/relay/registrations/{key}`. Steps 4 and 9 implement these. The contract will be reconciled against the returned HTML before Step 4 begins.
- **"Endpoints added based on the localhost port the relay runs on"**: This requirement can be read two ways. *Assumption*: the registration API accepts a `port` (with optional `host`, default `127.0.0.1`), and relay builds `http://127.0.0.1:<port>/v1` from it. lcpp finds relay through `relay.url` in `data/lcpp.json` (default `http://127.0.0.1:4000`). A full `base_url` is also accepted, for non-local servers.
- **Meaning of "stop the server"**: *Assumption*: the CLI has three stop levels. `lcpp stop <name|port>` stops one instance. `lcpp stop all` stops every instance. `lcpp service stop` stops the daemon itself. The UI offers "Stop" per instance and "Stop all". It does not offer daemon shutdown, because that would take the UI down with it.
- **Daemon port**: *Assumption*: `7700`, which is free on this machine. The ports in use are 4000 (relay), 4096 (opencode) and 7070 (current router). New instances get the first free port from `7071` upward unless you give one.
- **Instance bind address**: `127.0.0.1` only (see above). Relay reaches the instances locally.
- **Models stored outside this repo**: `nemotron-3-super` lives in `~/Models/Nemotron3Super/`, and there are loose GGUFs in `~/Models/`. *Assumption*: leave them in place, since absolute paths are still supported. Discovery scans `models/` by default, and `scan_dirs` in `data/lcpp.json` can add more locations.
- **Where the llama.cpp binaries go**: `LlamaCPP/` is neither a model nor config. *Assumption*: move it to `runtime/llama.cpp/{bin,vendor}` (gitignored, like today). The `binary` setting points at `runtime/llama.cpp/bin/current/llama-server`.
- **The existing `llama.cpp · local` relay endpoint**: Its 24h traffic share and telemetry history hang off its endpoint `id`. *Assumption*: a registration whose `base_url` matches an existing endpoint with no owner **adopts** that endpoint and keeps its `id`, instead of creating a duplicate. This keeps dashboard history continuous.
- **Running several models at once**: This machine has unified memory, so two large models can exhaust it. *Assumption*: no hard limit. The launch API returns a soft warning when the model file sizes plus the running instances' RSS exceed available memory (read from `/proc/meminfo` and the GPU's `mem_info_vram_*` in sysfs where present).
- **Git branch strategy**: The plan says "push to GitHub" after every step. *Assumption*: work on `feature/lcpp` in this repo and `feature/lcpp-registrations` in DashLLM (whose default branch is `main`), push the branch after each step, and merge to `master`/`main` in Step 12. This keeps each default branch working throughout.
- **Registration auth**: DashLLM's `CLAUDE.md` forbids adding auth. *Assumption*: the registration routes are as open as the rest of `/admin`.
- **Relay registration default**: *Assumption*: `relay.auto_register: true` in `data/lcpp.json`, so every new instance publishes itself unless you pass `--no-relay` or untick the option in the UI.

---

## 3. Hierarchical Step-by-Step Instructions

**Plan name for commit messages**: `lcpp Launcher`. **Total steps**: 12.

### Step 1: Restructure the repository (no behavior change)

- **Locations**:
  - New directories: `models/`, `data/`, `web/`, `runtime/`, `docs/plans/`, `deploy/systemd/`, `src/`, `utils/`.
  - Moves (btrfs, same filesystem, so they are instant renames): `Gemma4-19B/`, `Gemma4-26B/`, `Gemma4-E4B/`, `MiniCPM5-2B/`, `Ornith1-35B/` go to `models/<same name>/`. `LlamaCPP/` goes to `runtime/llama.cpp/`.
  - `llamacpp.json` is split into `data/lcpp.json` (daemon settings, `server` defaults, `environment`, relay settings) and `data/models.json` (`model_defaults` + `models` catalog). Model paths are rewritten relative to `models/`. `ornith1-35B`'s absolute in-repo path becomes relative.
  - `scripts/llamacpp.py`: update `DEFAULT_CONFIG`, the default `binary` and `preset` paths, and `load_config` so they read the two new files. This is temporary and is deleted in Step 6.
  - `.gitignore`: add `runtime/`, `models/**/*.gguf`, `data/generated/`, `data/*.local.json`, and `.pytest_cache/`.
  - Re-run `install-user-service` so `llamacpp-router.service` points at the new config.
- **Rationale**: Every later step builds on the final layout. Moving files first, while the old tooling still works, separates path breakage from new-feature bugs and keeps the current router and relay endpoint running during the migration.
- **Validation**: `python scripts/llamacpp.py render` resolves every model, mmproj and draft path. `python scripts/llamacpp.py print-command` shows the new paths. `systemctl --user restart llamacpp-router`, then load `minicpm-5-2B` through `:7070` and get a completion. The relay's `llama.cpp · local` endpoint is `healthy` again. `git status` shows no `.gguf` or `runtime/` files.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (1 / 12) Complete: Restructured the repo into models/, data/, runtime/ and web/, and pointed the existing router at the new paths.

### Step 2: Package scaffold and configuration/catalog layer

- **Locations**:
  - `pyproject.toml`: rename the project to `lcpp` and use a `src/` layout. Runtime deps are `fastapi` and `uvicorn`. The dev group adds `pytest` and `httpx`. `[project.scripts] lcpp = "lcpp.cli:main"`.
  - `src/lcpp/paths.py`: `REPO_ROOT`, `DATA_DIR`, `MODELS_DIR`, `RUNTIME_DIR`, `STATE_DIR` (`$XDG_RUNTIME_DIR/lcpp`), and `resolve_path()`.
  - `src/lcpp/settings.py`: Pydantic `Settings` model plus a loader for `data/lcpp.json` (fields `daemon.host/port`, `llama.binary`, `llama.environment`, `llama.server_params`, `relay.url/auto_register/owner`, `ports.range`, `scan_dirs`). Unknown keys are rejected with a clear message.
  - `src/lcpp/catalog.py`: `ModelSpec` and `Catalog` classes, ported from `scripts/llamacpp.py`. This covers `model_names`, `resolve_model` (exact match, then partial nickname match), `validate_model_file` (split-GGUF checks), `discover_unconfigured()` (GGUFs under `scan_dirs` that are not yet in the catalog, skipping `mmproj-*` and `mtp-*` sidecar files), and atomic `save()` (temp file + rename).
  - `src/lcpp/cmdline.py`: `params_to_args`, `build_single_argv(model, port, host, overrides)`, and `render_router_preset()` (ported `render_models_ini`, writing to `data/generated/models.ini`). Path-type params (`mmproj`, `model-draft`) are resolved.
  - Tests: `src/tests/conftest.py` (a temporary `data/` with fixture JSON and dummy `.gguf` files), `src/tests/test_settings.py`, `src/tests/test_catalog.py`, `src/tests/test_cmdline.py`.
- **Rationale**: The daemon, CLI and relay client all depend on one correct model of the configuration. Porting the proven logic behind tests first means Step 3 onward never re-derives paths or flags.
- **Validation**: `uv sync && uv run pytest src/tests` passes. A golden test asserts that `build_single_argv` for `gemma-4-26B-it` produces the same effective flags as the current `models.ini` section (ctx 262144, q8_0 caches, mmproj, `draft-mtp`). `uv run python -m lcpp.catalog` lists the six models and flags any missing files. That includes `nemotron-3-super` if its split files are absent.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (2 / 12) Complete: Added the lcpp package with tested settings, model catalog and llama-server command builders.

### Step 3: Instance supervisor (process lifecycle)

- **Locations**:
  - `src/lcpp/instances.py`: `InstanceSpec` (name, kind `single|router`, model id, host, port, param overrides, relay prefs), `InstanceState` (`starting|ready|stopping|stopped|failed`, pid, started_ts, last_error), and `InstanceStore`, which persists JSON under `STATE_DIR/instances/`.
  - `src/lcpp/backends/base.py`: the `Backend` protocol, with methods `launch`, `stop`, `is_active`, `pid`, and `logs(lines, follow)`.
  - `src/lcpp/backends/systemd.py`: `SystemdBackend` uses `systemd-run --user --unit=lcpp-<name> --collect --property=KillMode=control-group --setenv=…` with the settings' environment (`AMD_VULKAN_ICD`, `GPU_MAX_HW_QUEUES`) and `LD_LIBRARY_PATH` for the binary directory. Stopping uses `systemctl --user stop`, and logs come from `journalctl --user -u`.
  - `src/lcpp/backends/subprocess.py`: `SubprocessBackend`, for tests and for foreground `lcpp daemon --dev` runs.
  - `src/lcpp/supervisor.py`: `Supervisor` with `start(spec)`, `stop(name)`, `stop_all()`, `restart(name)`, `reconcile()` (adopts running `lcpp-*` units after a daemon restart and drops stale state files), `wait_ready()` (async polling of `GET /health` with a timeout, only while an instance is starting), and a port guard (rejects ports in use, the daemon's own port, and the relay port, and `suggest_port()` scans `ports.range`).
  - Tests: `src/tests/fakes/fake_llama_server.py`, a tiny stdlib HTTP server that accepts llama-server-style argv and answers `/health` and `/v1/models`. Also `src/tests/test_supervisor.py` (lifecycle, port conflicts, reconcile, failed-start reporting) and `utils/smoke_supervisor.py` (a live script against the real binary).
- **Rationale**: The supervisor is the core of the product. It must be correct before any API or UI sits on top. Transient units give crash-safe cleanup and journald logs without the daemon keeping pipes or threads open, which is also what keeps the daemon lightweight.
- **Validation**: `uv run pytest src/tests` passes. Live: `uv run python utils/smoke_supervisor.py minicpm-5-2B 7071` starts the unit, `curl :7071/v1/models` lists the model, and a stop removes the unit (`systemctl --user list-units 'lcpp-*'` is empty) and frees the memory. The old router on `:7070` is untouched throughout.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (3 / 12) Complete: Added the instance supervisor that runs llama-server as transient systemd units with readiness checks, port guards and reconcile.

### Step 4: lcppd — the FastAPI daemon and HTTP API

- **Locations**:
  - `src/lcpp/daemon/app.py`: `create_app()` with a lifespan hook that loads settings and catalog, builds the `Supervisor`, and runs `reconcile()`. Background tasks exist only while an instance is starting. `StaticFiles` for `web/` is mounted last.
  - `src/lcpp/daemon/schemas.py`: the API contract.
  - `src/lcpp/daemon/routes/instances.py`: `GET /api/instances`, `POST /api/instances`, `GET/DELETE /api/instances/{name}`, `POST /api/instances/{name}/restart`, `POST /api/instances/stop-all`, `GET /api/instances/{name}/logs` (tail), and `GET /api/instances/{name}/logs/stream` (SSE, open only while a client watches). Targets may be given as a name or a port.
  - `src/lcpp/daemon/routes/models.py`: `GET /api/models` (catalog + file status + sizes), `GET /api/models/discovered`, `PUT /api/models/{id}`, and `DELETE /api/models/{id}`, all with atomic writes to `data/models.json`.
  - `src/lcpp/daemon/routes/system.py`: `GET /api/health`, `GET /api/system` (memory and VRAM usage, llama.cpp build, daemon RSS and uptime), and `GET /api/ports/suggest`.
  - `src/lcpp/daemon/__main__.py`: `python -m lcpp.daemon` runs uvicorn with one worker, no reload, `log_level=warning`, and `access_log=False`.
  - `web/index.html`: a placeholder page, so the static mount exists.
  - `docs/api.md`: the lcpp API contract.
  - Tests: `src/tests/test_api.py` (TestClient + SubprocessBackend + fake server) and `utils/measure_idle.sh` (startup time, RSS, and CPU over 60 s).
- **Rationale**: One HTTP API behind both the CLI and the UI means one implementation of every action. Idle budgets are measured here, before the UI can hide regressions.
- **Validation**: pytest passes. Run `uv run python -m lcpp.daemon` in the foreground and `curl` each route. `POST` a MiniCPM instance on 7071 and poll it to `ready`, then `DELETE` it. `utils/measure_idle.sh` shows under 1.5 s to the first `/api/health` response, under 60 MB RSS, and about 0% CPU over 60 s with no instances running.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (4 / 12) Complete: Added the lcppd FastAPI daemon exposing instance, model, log and system APIs within the idle resource budget.

### Step 5: The unified `lcpp` CLI

- **Locations**:
  - `src/lcpp/cli.py`: stdlib only. `main()` uses argparse subcommands and exits non-zero with a readable message when the daemon is down, including the hint `lcpp service start`.
    - `lcpp status [--json]`: daemon state plus an instances table (name, model, port, state, relay status, uptime).
    - `lcpp models [--discovered]`.
    - `lcpp start <model> [--port N] [--name X] [--ctx N] [--set key=value …] [--relay/--no-relay] [--alias A] [--wait/--no-wait]`.
    - `lcpp start --router [--port 7070] [--models-max N]`.
    - `lcpp stop <name|port|all>` and `lcpp restart <name|port>`.
    - `lcpp logs <name|port> [-f] [-n N]`.
    - `lcpp relay status|add <target>|remove <target>`. The parser is wired here and becomes functional in Step 9.
    - `lcpp service install|uninstall|start|stop|restart|status|logs`. Wired here; implemented in Step 6.
    - `lcpp ui` opens `http://127.0.0.1:7700`. `lcpp doctor` checks the binary, model files, ports and relay reachability.
    - The global flag `--daemon URL` (or env `LCPP_URL`) targets a different lcppd.
  - `src/lcpp/client.py`: a small `urllib` JSON client shared by the CLI.
  - Install: `uv tool install --editable .`, which puts `lcpp` in `~/.local/bin`.
  - Tests: `src/tests/test_cli.py` (argument parsing, plus end-to-end against a uvicorn instance in a thread on a random port with the fake backend) and `src/tests/test_cli_startup.py` (asserts `fastapi` is not in `sys.modules` after importing `lcpp.cli`).
- **Rationale**: `lcpp` replaces the six `llamacpp-*` symlinks with one discoverable command. Targeting by name or port answers the requirement to specify which server to act on. Keeping the CLI free of FastAPI keeps it fast.
- **Validation**: pytest passes. `time lcpp status` takes under about 150 ms. Against the foreground daemon: `lcpp start minicpm --port 7071`, `lcpp status`, `lcpp logs 7071 -n 20`, and `lcpp stop 7071` behave as documented. `lcpp --help` and each subcommand's `--help` read cleanly.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (5 / 12) Complete: Added the unified lcpp CLI for starting, stopping, restarting, inspecting and logging llama.cpp instances.

### Step 6: Boot service and cutover from the legacy commands

- **Locations**:
  - `deploy/systemd/lcpp.service`: a template using `@REPO_ROOT@`, following DashLLM's convention. `ExecStart=@REPO_ROOT@/.venv/bin/python -m lcpp.daemon` calls the venv Python directly, not `uv run`, because `uv run` adds startup latency. It also sets `Restart=on-failure` and `WantedBy=default.target`. It uses `KillMode=process`, so that stopping the daemon never kills transient instance units. Linger is already enabled for `bdgr`.
  - `scripts/install.sh`: idempotent. It renders and installs the unit, runs `daemon-reload` and `enable --now lcpp.service`, runs `uv tool install --editable .`, and then removes the legacy pieces: the `~/.local/bin/llamacpp-*` symlinks, and `llamacpp-router.service` (`disable --now`, then delete the unit file).
  - `src/lcpp/service.py`: the `lcpp service …` implementation (systemctl/journalctl wrappers).
  - Delete `scripts/llamacpp.py` and `scripts/__pycache__/`. Rewrite `Makefile` as developer shortcuts: `make test`, `make install`, `make dev`, `make idle-check`.
- **Rationale**: This step is where the new system becomes the real one. Removing the old commands in the same step avoids having two competing ways to start a server on `:7070`.
- **Validation**:
  1. `scripts/install.sh` runs cleanly, then runs a second time without changing anything.
  2. `systemctl --user is-enabled lcpp` prints `enabled`. `lcpp status` works. `which llamacpp-start` finds nothing.
  3. Reboot, or log out and back in. `lcpp status` answers with zero instances, `pgrep llama-server` is empty, and `systemd-analyze --user blame | grep lcpp` shows startup well under 1 s.
  4. `lcpp start --router --port 7070` restores the old router behavior, and the relay's `local` endpoint turns healthy again. That endpoint is left alone until Step 9.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (6 / 12) Complete: Installed lcppd as an at-boot user service that loads no models, and retired the llamacpp-* commands and router unit.

### Step 7: DashLLM — dynamic registration API (backend)

*Repository: `~/Tools/DashLLM`, branch `feature/lcpp-registrations`.*

- **Locations**:
  - `web/backend/app/db.py`, `_migrate()`: additive `ALTER TABLE endpoints ADD COLUMN owner TEXT` and `ADD COLUMN external_key TEXT`, plus a unique index on `external_key`.
  - `web/backend/app/services/router.py`: carry `owner` and `external_key` through `create` (keeping the positional `INSERT` column order in step with the `row` dict keys, as `CLAUDE.md` warns), `patch`, `_load`, and `out`. Add `find_by_key()` and `find_unowned_by_url()`.
  - `web/backend/app/services/registrations.py`: `upsert(key, spec)`, which matches by `external_key`, then adopts an unowned endpoint with the same base URL, then creates a new one. It builds `base_url` from `port`/`host` when no URL is given, and runs an immediate probe. `remove(key)` is idempotent. `list(owner)` filters by owner.
  - `web/backend/app/routes/admin_registrations.py`: `PUT /admin/registrations/{key}`, `DELETE /admin/registrations/{key}` (returns 204 even when the key is missing), and `GET /admin/registrations?owner=`. An alias collision returns 409.
  - `web/backend/app/main.py`: `include_router` placed **before** the static catch-all mount.
  - The contract is written in three places, as `CLAUDE.md` requires: `web/backend/app/schemas/__init__.py` (`RegistrationUpsert` with `name`, `port | base_url`, `host`, `alias`, `available_models`, `server_type`, `owner`, `meta`; plus `owner` and `external_key` on `EndpointOut`), `web/frontend/src/lib/types.ts`, and `docs/api-contract.md`. Also update `docs/routes.md`.
  - `deploy/systemd/relay.service`: replace `After=llamacpp-router.service` with `After=lcpp.service` and update the ordering comment.
  - Tests: `tests/backend/test_registrations.py` covers these cases: idempotent upsert, port-to-`base_url` construction, adoption keeping the endpoint `id` and its telemetry, owner filter, idempotent delete, alias conflict 409, a model allowlist published to `/v1/models`, and the survival of registrations across an app restart.
- **Rationale**: The existing `POST /admin/endpoints` is not idempotent and has no concept of an owner. lcpp needs to say "make it so for key `lcpp:7071`" safely on every start, reconcile, or retry. It also needs to find and remove only its own entries without touching skynet, opencode, or manually added endpoints.
- **Validation**: `cd web/backend && uv run pytest` passes, covering all 163 existing tests plus the new ones. `cd web/frontend && npm run check && npm run build` passes. Then `relay restart`, `curl -X PUT :4000/admin/registrations/test:7071 -d '{"name":"t","port":7071}'`, confirm the endpoint appears in `GET /admin/endpoints`, `DELETE` it, and confirm it is gone. The `skynet` and `opencode` endpoints are unchanged.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (7 / 12) Complete: Added an idempotent, owner-scoped endpoint registration API to the DashLLM relay.

### Step 8: DashLLM — show managed endpoints in the dashboard

- **Locations**:
  - `web/frontend/src/components/screens/Endpoints.tsx`: a "managed by lcpp" badge on endpoints with `owner === "lcpp"`, plus a link to the manager UI taken from registration `meta.manager_url`. Deleting a managed endpoint asks for confirmation, with a note that lcpp re-registers it while the instance runs.
  - `web/frontend/src/components/screens/EndpointForm.tsx`: owner shown read-only.
  - `web/frontend/src/lib/api.ts`: add `registrations` calls if the screen needs them.
  - `docs/frontend.md` and `docs/deployment.md`: add an "lcpp integration" section.
- **Rationale**: Dynamically added endpoints must be recognizable as automatic, or someone will edit or delete them by hand and be surprised when they come back.
- **Validation**: `npm run check && npm run build`, then `relay restart`. In the in-app browser, register a test key through `curl` and confirm the badge, the link and the delete confirmation appear. Take screenshots at desktop and mobile width. `uv run pytest` still passes.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (8 / 12) Complete: Surfaced lcpp-managed endpoints in the relay dashboard with badges, manager links and guarded deletion.

### Step 9: lcpp ↔ relay integration

*Repository: this one; DashLLM only if contract fixes turn up.*

- **Locations**:
  - `src/lcpp/relay.py`: `RelayClient` with `register(instance)`, `unregister(instance)`, `list_owned()`, and `reconcile(running)`. Keys are `lcpp:<port>`. Registrations send `available_models` (the model id plus its nicknames for `single`, or all catalog ids for `router`) and `meta.manager_url`. Calls run off the event loop. When relay is unreachable, registration is marked `pending` and retried with capped backoff. The retry loop exists only while something is pending.
  - `src/lcpp/supervisor.py` hooks: register once `wait_ready()` succeeds, and unregister before `stop()`. At daemon startup `reconcile()` also reconciles relay: it deletes owned registrations that have no running instance and re-registers the running ones.
  - `src/lcpp/daemon/routes/relay.py`: `GET /api/relay` (reachability plus owned registrations), and `POST`/`DELETE /api/instances/{name}/relay` (manual publish and unpublish, with an optional alias).
  - `src/lcpp/cli.py`: make `lcpp relay status|add|remove` and `lcpp start --relay/--no-relay --alias` functional.
  - A one-time migration in `scripts/install.sh` (or `lcpp doctor --fix`) makes sure the first `lcpp:7070` registration **adopts** the legacy `llama.cpp · local` endpoint, so no duplicate is created.
  - Tests: `src/tests/fakes/fake_relay.py` (a minimal ASGI app implementing the Step 7 contract) and `src/tests/test_relay.py` (register on ready, unregister on stop, pending and retry when relay is down, reconcile removing orphans, and `--no-relay`).
- **Rationale**: This step connects the two services. Relay stays authoritative for routing and telemetry, lcpp stays authoritative for which processes exist, and either one can restart without leaving the other wrong.
- **Validation**: pytest passes. Live:
  1. `lcpp start minicpm --port 7071` makes the endpoint appear in relay with the managed badge and `healthy` status.
  2. `curl :4000/v1/chat/completions -d '{"model":"minicpm-5-2B",…}'` is answered through relay, and the request shows up on the relay dashboard.
  3. `lcpp stop 7071` makes the endpoint disappear.
  4. Stop relay, start an instance, and start relay again: the registration lands within the backoff window.
  5. `systemctl --user restart lcpp` with an instance running leaves the instance alive and its registration intact.
  6. `lcpp start --router --port 7070` adopts the legacy endpoint, so its `id` is unchanged and its history is continuous.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (9 / 12) Complete: Wired lcpp instances to register and unregister with the DashLLM relay automatically, with retry and reconcile.

### Step 10: Front-end design with Claude Design (`/design`)

- **Locations**:
  - The design runs through `/design`, with this brief:
    - **Instances dashboard**: cards or rows showing state, model, port, host, uptime, memory, relay status, and actions (stop, restart, logs, publish/unpublish).
    - **Launch panel**: model picker with nicknames, file size and a missing-file warning; port field with a suggested port and a live conflict check; name; ctx size; advanced param overrides; router toggle; relay toggle and alias.
    - **Models catalog**: configured models with file status, plus discovered unconfigured GGUFs with an "add to catalog" action.
    - **Logs drawer**: a live tail.
    - **Relay panel**: reachability, owned registrations, and a link to the relay dashboard.
    - **Header**: memory and VRAM use, daemon status, and "Stop all".
    - Empty, loading and error states, and the response to a daemon that is down.
    - Light and dark themes, usable at phone width.
  - Handoff saved to `web/design/`: exported mockups, the tokens and component notes, plus `web/design/README.md` linking the Claude Design artifact.
- **Rationale**: The UI has to be fully interactive for experimenting, launching and publishing. Agreeing on the design before writing it avoids reworking the implementation. The API from Steps 4 and 9 is already fixed, so the design can bind to real fields.
- **Validation**: You review the design and approve one direction. Every API action (Steps 4, 5 and 9) maps to a control in the design, checked against a table in `web/design/README.md`.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (10 / 12) Complete: Produced and approved the lcpp UI design with Claude Design and saved the handoff to web/design/.

### Step 11: Implement the web front end

- **Locations**:
  - `web/index.html`, `web/assets/styles.css` (design tokens on `:root`, with dark mode), `web/assets/api.js` (fetch wrapper matching `docs/api.md`), and `web/assets/app.js` (state and render loop).
  - `web/assets/components/*.js`: `instances.js`, `launch.js`, `models.js`, `logs.js`, `relay.js`, and `system.js`.
  - `web/assets/icons.svg` and `web/favicon.svg`.
  - Behavior:
    - Polling runs only while `document.visibilityState === "visible"`, with a 2 s interval while any instance is `starting` and 10 s otherwise.
    - Logs arrive over SSE and the connection closes when the drawer closes.
    - Launch requests are optimistic: the new card appears in `starting` state and updates in place.
    - Destructive actions ask for confirmation, and all controls are keyboard-accessible.
  - `src/lcpp/daemon/app.py`: add cache headers for `/assets`.
  - Tests: `src/tests/test_web.py` (index and assets are served, and every `api.js` path exists in the FastAPI route table) and `utils/ui_smoke.md` (a manual click-through checklist).
- **Rationale**: This delivers the interactive UI. It has no build step and ships as static files, so it adds no resident cost to the daemon.
- **Validation**:
  - pytest passes.
  - In the in-app browser at `http://127.0.0.1:7700`: launch MiniCPM on a custom port, watch it move from `starting` to `ready`, open the live logs, publish it to relay and confirm it on `:4000`, unpublish it, stop it, and use "Stop all". Try a port conflict and a missing model file, and confirm both show clear errors.
  - Check mobile width, and light and dark themes.
  - With the UI tab closed, `utils/measure_idle.sh` still meets the Step 4 budget.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (11 / 12) Complete: Implemented the interactive lcpp web UI for launching, monitoring, logging and relay-publishing llama.cpp instances.

### Step 12: Documentation, end-to-end check, and merge

- **Locations**:
  - `README.md`: rewrite covering the layout, install, `lcpp` usage, UI, relay integration, and troubleshooting.
  - `CLAUDE.md`: new, recording the pitfalls, for example that instances are transient units, that the daemon uses `KillMode=process`, that the CLI must stay stdlib-only, and that `data/` writes are atomic.
  - `docs/api.md`: finalized.
  - `utils/e2e_live.sh`: the full scenario against the real services. That is daemon health, start two instances on custom ports, relay routing for both, restart the daemon mid-run, stop all, and confirm relay is clean.
  - DashLLM: `README.md` "lcpp integration" paragraph and `CLAUDE.md` notes on registrations (owner-scoped, adoption, idempotent delete).
  - Merge `feature/lcpp` into `master` here and `feature/lcpp-registrations` into `main` in DashLLM. Re-run both installers from the merged branches.
- **Rationale**: This leaves both repos documented, in a consistent state, and running on their default branches, with a repeatable end-to-end check for future changes.
- **Validation**: `uv run pytest src/tests` passes here and `uv run pytest` passes in DashLLM. `utils/e2e_live.sh` exits 0. A final reboot shows lcpp and relay up, no models loaded, and no stale lcpp registrations. `git status` is clean in both repos.
- **Action**: Undergo the verification/tests/validation process for this phase. Once validated, push changes to GitHub stating: lcpp Launcher (12 / 12) Complete: Documented lcpp and the relay integration, passed the end-to-end check, and merged both repos to their default branches.

---

## 4. Deliverables Table

| Deliverable | Description | Location (File/Path) |
| --- | --- | --- |
| Restructured layout | Model folders, config, web, runtime binaries separated | `models/`, `data/`, `web/`, `runtime/llama.cpp/` |
| Split configuration | Daemon/relay settings and model catalog | `data/lcpp.json`, `data/models.json` |
| Settings & catalog layer | Config loading, model resolution, GGUF validation, discovery | `src/lcpp/settings.py`, `src/lcpp/catalog.py`, `src/lcpp/paths.py` |
| Command builders | llama-server argv (single) and router preset rendering | `src/lcpp/cmdline.py` |
| Instance supervisor | Transient-unit lifecycle, readiness, port guard, reconcile | `src/lcpp/supervisor.py`, `src/lcpp/instances.py`, `src/lcpp/backends/` |
| lcppd daemon | FastAPI app, API routes, static UI mount | `src/lcpp/daemon/` |
| API contract | lcpp HTTP API reference | `docs/api.md` |
| `lcpp` CLI | Unified stdlib-only command replacing `llamacpp-*` | `src/lcpp/cli.py`, `src/lcpp/client.py`, `src/lcpp/service.py` |
| Boot service | At-boot user unit (no models loaded) + idempotent installer | `deploy/systemd/lcpp.service`, `scripts/install.sh` |
| Relay client | Register/unregister/reconcile/retry against DashLLM | `src/lcpp/relay.py`, `src/lcpp/daemon/routes/relay.py` |
| DashLLM registration API | Idempotent owner-scoped endpoint upsert/delete/list + migration | `~/Tools/DashLLM/web/backend/app/routes/admin_registrations.py`, `.../services/registrations.py`, `.../db.py`, `.../services/router.py`, `.../schemas/__init__.py` |
| DashLLM dashboard updates | Managed badge, manager link, guarded delete | `~/Tools/DashLLM/web/frontend/src/components/screens/Endpoints.tsx`, `EndpointForm.tsx`, `src/lib/types.ts` |
| UI design handoff | Claude Design output and API-to-control map | `web/design/` |
| Web front end | No-build interactive UI | `web/index.html`, `web/assets/` |
| Unit tests — config/catalog/cmdline | Small fixture-based tests (dummy GGUFs, temp `data/`) | `src/tests/test_settings.py`, `src/tests/test_catalog.py`, `src/tests/test_cmdline.py` |
| Unit tests — supervisor | Lifecycle with a fake llama-server | `src/tests/test_supervisor.py`, `src/tests/fakes/fake_llama_server.py` |
| Unit tests — API & CLI | TestClient API tests, CLI end-to-end, CLI import-weight guard | `src/tests/test_api.py`, `src/tests/test_cli.py`, `src/tests/test_cli_startup.py` |
| Unit tests — relay integration | Against a fake relay implementing the contract | `src/tests/test_relay.py`, `src/tests/fakes/fake_relay.py` |
| Unit tests — web | Static serving and UI↔API route consistency | `src/tests/test_web.py` |
| DashLLM tests | Registration API behaviors incl. adoption and conflicts | `~/Tools/DashLLM/tests/backend/test_registrations.py` |
| Live utilities | Supervisor smoke, idle budget, full end-to-end, UI checklist | `utils/smoke_supervisor.py`, `utils/measure_idle.sh`, `utils/e2e_live.sh`, `utils/ui_smoke.md` |
| Documentation | README, agent notes, relay integration docs | `README.md`, `CLAUDE.md`, `~/Tools/DashLLM/docs/*.md` |
