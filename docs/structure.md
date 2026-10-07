# AIHub — Repository structure

What is in the repo **today**, and where each planned piece goes. The full target layout and the reasons behind it are in [architecture.md §3](architecture.md#3-directory-layout). Update this file in the same commit whenever a file or folder is added, moved or removed.

**Status key:** ✅ exists · 🧱 placeholder folder (empty, `.gitkeep`) · ⏳ planned (with the plan step that creates it)

## Top level

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `CLAUDE.md` | ✅ | Short rules for agents, true today |
| `.claude/skills/aihub/` | ✅ | Project skill: how to work on AIHub (doc map, invariants, step workflow) |
| `.claude/skills/plan/` | ✅ | Project skill: how to write and amend plans in this repo's format |
| `.claude/skills/aihub-mod/` | ✅ | Project skill: building or porting a mod (points at `docs/mods.md`, requires `aihub check` to pass) |
| `.gitignore` | ✅ | Keeps models, databases, outputs and venvs out of git |
| `pyproject.toml` | ✅ | Hub dependencies (uv) |
| `uv.lock` | ✅ | Locked hub dependencies; `uv sync` builds `.venv/` (ignored) from it |
| `app.py` | ✅ | `python app.py [--port N] [--dev] [--no-autostart] [--demo-mods]` starts the hub on 127.0.0.1 and [::1] |
| `config.toml` | ✅ | User settings (architecture §9); a missing file means defaults |
| `bin/` | ✅ | `aihub` (bash wrapper → `utils/cli.py` with the hub venv) and `aihub.service.in` (unit template; `aihub install` fills in `@ROOT@`) |
| `docs/` | ✅ | Design, plan, UI brief, this file, `reference/` UI exports |
| `utils/` | ✅ | The hub's Python package (below) |
| `services/` | ✅ | One folder per mod. `_template/` is the mod `aihub new` copies: `service.toml`, `server.py` (FastAPI: health, status, hello, echo, note → outputs, a widget route), `requirements.txt`, `install.sh`, `README.md` (the contract on one page), `ui/page.js` |
| `data/` | ✅ | Models, databases (below); `logs/` and `state/` arrive in Stage D |
| `outputs/` | 🧱 | `<mod>/<YYYY-MM-DD>/…` (+ `.trash/`), ignored by git; indexed into `hub.db` |
| `web/` | ✅ | The UI (below) |

## `services/` (the mods)

The existing apps come in with `git subtree add` (their history is kept), so most of each folder is the app's own code. These are the parts added for AIHub; `comfy` is new:

| Mod | From | Added for AIHub |
| :--- | :--- | :--- |
| `tts` | `~/Projects/LocalTTS` (plan Phase 7) | `service.toml`, `aihub-install.sh` (venv only), `localtts/outputs.py` (dated outputs + sidecars), `localtts/hub.py` (`/v1/status`, the "Clips per day" widget), `ui/page.js` (the Speech page: Speak and Voices tabs), `tests/` (`.venv/bin/python -m pytest` in the mod folder), `requirements-dev.txt`, `pytest.ini`; `bin/localtts` delegates to `aihub`; `scripts/install-runtime.sh` + `locks/` (the engine venvs in `runtime/venvs/` and the Breeze source in `runtime/breeze-tts/`, plan 12.1) |
| `relay` | `~/Tools/DashLLM` (plan Phase 9) | `service.toml`, `aihub-install.sh` (`uv sync` in `web/backend`; npm for the dashboard), `web/backend/app/routes/admin_hub.py` (`/admin/status`, the "LLM traffic" widget), `web/backend/app/services/model_facts.py` (each model's context window, tools, vision and reasoning for `/v1/models` `meta`, plan 13.3) and `catalog.py` (the synthesized `/v1/models`, moved out of `proxy.py`), `tests/backend/test_model_facts.py`, `tests/backend/test_aihub.py`, `ui/page.js` (the LLM Relay page: Dashboard, Requests, Endpoints, Tunnels, Connect), `bin/relay` (delegates to `aihub`); default bind 127.0.0.1; `scripts/relay` removed |
| `opencode` | DashLLM's `opencode.service` (plan 9.4) | Manifest-only: `service.toml`, `run.sh` and `auth.sh` (from DashLLM's `scripts/opencode-serve.sh` / `opencode-auth.sh`), `.env` and `opencode-auth.env` (both gitignored), `README.md` |
| `lcpp` | `~/Models/LLMs` (plan Phase 10) | `service.toml`, `aihub-install.sh` (`uv sync`, Python 3.14), `src/lcpp/aihub.py` (memory acquire before a launch, downloads registered in AIHub, the page URL for the relay), `src/lcpp/daemon/routes/hub.py` (`/api/status`), `LCPP_MODELS_DIR` in `paths.py` (catalog paths are models-relative), `src/tests/test_aihub.py`, `ui/page.js` (the LLM Launcher page: Instances, Catalog, Playground, Relay publishing, Launcher settings); `lcpp service …` delegates to `aihub`; `runtime/` (llama.cpp, gitignored) copied over |
| `gen3d` | `~/Projects/3DGenerate` (plan Phase 8) | `service.toml`, `aihub-install.sh`, `gen3d/hub.py` (`/v1/status`, the "Job time per stage" widget), `store.py`'s dated job folders (`dir` column) and `output.json`, `scripts/migrate_jobs_to_outputs.py`, `tests/test_aihub.py`, `requirements-dev.txt` (pytest moved out of `requirements.txt`), `ui/page.js` (the 3D Generate page: Create and Jobs tabs), `desktop/3dgenerate-aihub.desktop`; `bin/gen3d` delegates to `aihub`; `scripts/install-runtime.sh` + `locks/cubeart.txt` (CubeArt in `runtime/CubeArt/`: the cube clone, caches and the container venv, plan 12.2) |
| `comfy` | new (plan Phase 11); ComfyUI itself runs in the `strix-halo-comfyui` toolbox on 8199 | The adapter package `comfy/`: `config.py` (`COMFY_*` settings), `db.py` (`comfy.db`: runs, per-task defaults), `server.py` (`create_app`), `hub.py` (`/v1/status`), `client.py` (ComfyUI's HTTP API), `control.py` (load = start ComfyUI, unload = `/free` + stop it, idle unload, the queue poller), `nodes.py` (`NodeCatalog`: `/object_info` cached in `data/object_info.json`), `convert.py` (editor workflow → API graph), `packs.py` (workflow packs, drafts, ComfyUI's view), `check.py` (missing nodes/models, mapping and task checks), `schema.py` (a pack's inputs as JSON Schema), `detect.py` (drafts a pack's `workflow.toml` from its graph), `resolve.py` (inputs → patched graph), `run.py` (`Runner`: queue, progress, results, sidecars), `api_run.py` (`/v1/run`, `/v1/jobs`, `/v1/queue`, `/v1/defaults`, `/v1/uploads`, `/v1/files`), `importer.py` (files, media metadata, zips and ComfyUI history → draft packs), `api_import.py` (`/v1/import`, saving and removing packs, `/v1/downloads`), `downloads.py` (missing model files, registered in AIHub), `tools.py` (agent tools: one per task, `list_workflows`, `run_workflow`; `/v1/tools`), `ui/page.js` + `ui/run.js` + `ui/import.js` (the Images & Video page: Workflows, Run, Import), `library.py` (cached analysis per pack), `tasks.py` + `tasks.toml` (tasks and shared input names), `api_workflows.py` (`/v1/workflows`, `/v1/tasks`), `cli.py` (`comfyui workflows …`), `logtail.py` (ComfyUI's log copied to the adapter's stdout); `bin/comfyui` (start/stop/status/logs/update ComfyUI in the toolbox; moved from `~/.local/bin/comfyui`), `extra_model_paths.yaml` (models from `$COMFY_MODELS`, custom nodes from the mod); `workflows/` (the packs: the development set, the held-out Qwen-Image-2.1 and Klein templates; third-party packs are kept out of git by `workflows/.gitignore`), `scripts/download_qwen_image_2.1.sh`, `scripts/migrate_old_outputs.py`; gitignored: `custom_nodes/`, `user/` (ComfyUI's settings, database and its workflows folder) and `input/` (moved from `~/Models/ComfyUI-next`, symlinks left there), `data/`; `service.toml`, `install.sh`, `tests/` (`.venv/bin/python -m pytest` in the mod folder; `fakecomfy.py` is a fake ComfyUI; `fixtures/` holds the development workflows with ComfyUI's own API graphs and a trimmed `object_info.json`, plus `expected/` (hand-written input expectations scored by `scoring.py`), `holdout/` and `holdout-expected/` (plan 11.12); `transfer.py` scores the held-out set, `test_holdout.py` keeps it as regression tests) |

## `docs/`

| File | Purpose |
| :--- | :--- |
| `architecture.md` | The agreed design: decisions, layout, mod contract, runtime, API, memory, registry, config, metrics, Stage D |
| `workflows.md` | ComfyUI workflow packs: the folder, `workflow.toml`, tasks, editing, the CLI, problems and fixes (plan 11.11) |
| `comfy-transfer-report.md` | Plan 11.12: the held-out ComfyUI workflows scored before and after fixes, what they found, and what's still a limit |
| `agent-architecture.md` | The chat agent's design and the research behind it: Claude Code's structure, the literature, frameworks considered, and facts checked on this machine (plan Phases 13–14) |
| `test-plan.md` | The checks and edge cases for Phases 13–16, written before building them; results go in the overnight report |
| `backend-plan.md` | The build plan: Phases 0–16 with steps, checks and deliverables; steps are ticked as they land |
| `design-brief-ui.md` | UI brief for Claude Design; §6 and §11.7 are the UI-facing API contract |
| `mods.md` | Writing a mod: the contract, the new → check → restart loop, the four UI levels, outputs/memory/tools, porting an app, fixing `aihub check` failures |
| `structure.md` | This file |
| `reference/ui-export-2026-10-04/` | Claude Design's Part A v1 export, the UI baseline (read-only reference) |

## `utils/` — the hub package

Small subsystems are single files directly in `utils/`; anything that grows into several modules gets its own sub-package with an `__init__.py` (as `backends/` and `routes/` already do).

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `__init__.py` | ✅ | Package marker; nothing runs at import time |
| `paths.py` | ✅ | `Paths` (root, configurable dirs kept inside the root), `write_atomic()` |
| `config.py` | ✅ | `Config` (pydantic, §9), `load()`, `save()` via tomlkit, `service_override()`, loopback check |
| `db.py` | ✅ | `Database`: `hub.db` (WAL), migrations by `user_version` (001 activity/peaks/kv, 002 outputs, 003 metrics), one writer thread, locked per-thread readers, async helpers |
| `events.py` | ✅ | `EventBus` (per-subscriber queue, overflow → resync), `ActivityLog`, `Alerts`, `sse_stream()` |
| `server.py` | ✅ | `create_app()`, `Hub` (app state, live-area registry), lifespan, `HubError` + error envelope, static `web/` |
| `cli.py` | ✅ | Standard-library CLI behind `bin/aihub`: serve, install, start/stop/restart, status, logs, load/unload, open, url, doctor (local checks + the hub's `/api/doctor`) |
| `doctor.py` | ✅ | `GET /api/doctor` (plan 12.4): models on disk, manifests, paths outside the project and the allowlist, Stage D notes, ports, units, disk, offline mods |
| `cli_models.py` | ✅ | `aihub models list \| show \| scan [--add] \| verify` (standard library only, loaded on demand by `cli.py`) |
| `cli_backup.py` | ✅ | `aihub backup <folder>` (plan 12.5): online SQLite copies of every database, the registry, `config.toml` and `services/*/.env` in a dated owner-only archive (standard library only) |
| `cli_mods.py` | ✅ | `aihub new`, `aihub check`, `aihub install <id>`, `aihub rescan` (standard library only, loaded on demand by `cli.py`) |
| `manifest.py` | ✅ | `service.toml` schema (pydantic), `discover()` with collected errors, `effective()` config overrides, `launch_spec()` (placeholders + env), `start_order()` |
| `backends/` | ✅ | `base.py` (`Backend` protocol incl. `pids()`, `UnitState`, `LogLine`), `systemd.py` (`aihub-<id>.service` via `systemd-run`, journal logs), `subprocess.py` (child processes + log ring; tests and `--dev`) |
| `services/` | ✅ pkg | Running mods. `manager.py` (`ServiceManager`: start/stop/restart, logs), `discovery.py` (boot, adoption, autostart in `after` order, rescan), `health.py` (readiness, monitor, restart on failure, external mods), `status.py` (status polling, `validate()` for the §4.6 shape, job events), `loading.py` (load/unload via `[memory]`; Phase 5 adds make-room), `views.py` (`ServiceSummary` / `ServiceDetail` JSON), `check.py` (`aihub check`: the mod self-test), `model.py` (`Service`, `Timing`, `ServiceError`) |
| `proxy.py` | ✅ | `ANY /api/s/<id>/*`: streaming passthrough, hop-by-hop headers dropped, redirects kept inside the proxy |
| `operations.py` | ✅ | Mod OpenAPI → `Operation[]` (refs inlined, file fields, response kinds, hide globs, tools), cached per process start |
| `registry/` | ✅ pkg | Models registry (architecture §8): `model.py` (stored shape, validation, `RegistryError`), `store.py` (`Registry`: load/save `registry.json`, computed status, totals, filters, edit, delete with the in-use rule), `scan.py` (the scanner's grouping rules), `adding.py` (`POST /api/models/scan` filtering, `POST /api/models`), `verify.py` (`Verifier`: the one-at-a-time checksum queue), `alerts.py` (registry alerts and the once-a-minute watcher) |
| `outputs/` | ✅ pkg | Outputs index (architecture §4.7): `entries.py` (which files and folders are outputs, `scope_for`), `describe.py` (an output → its `outputs` row: sidecar, title, kind, main file, times), `media.py` (durations, sizes, previews via `wave`/Pillow/ffmpeg), `index.py` (`Outputs`: sync, reconcile, list/get, delete, files, previews), `watch.py` (`watchfiles` watcher, startup rescan, trash purge), `trash.py` (`outputs/.trash/<date>/`, purged after 30 days), `announce.py` (batched activity items) |
| `proc.py` | ✅ | /proc and /sys facts: `meminfo`, `gpu`, process trees, PSS + DRM memory (`footprint`; RSS when `smaps_rollup` is unreadable), unit cgroups, unit globs, container pids, `port_listening`, `port_owner` |
| `memory/` | ✅ pkg | Memory manager (architecture §7): `source.py` (`ProcSource`: each mod's pids and footprint), `planner.py` (the load rule, `make_plan`), `manager.py` (`MemoryManager`: sampling, events, peaks, the `memory-high` alert, `ensure_room`, make-room, reservations), `triggers.py` (the proxy hook) |
| `metrics/` | ✅ pkg | Metrics (architecture §13): `store.py` (`Store`: series, samples on the 10 s grid, rollups with watermarks, retention, queries on an even `t` axis with gaps), `recorder.py` (`Recorder`: 10 s ticks from the memory snapshot and status stats, service/load/job history from events, closing rows at downtime, hourly rollup, the low-disk alert)) |
| `settings.py` | ✅ | The Settings page: `view()` (config.toml as the brief's `Settings`) and `save()` (partial saves, only changed values written, applied live; the port at the next start) |
| `widgets.py` | ✅ | `Widgets`: running mods' `[[ui.widgets]]`, their data fetched from each `source`, validated against `WidgetData` and cached for 30 s |
| `tools/` | ✅ pkg | Agent tools (plan Phase 13): `catalog.py` (`Catalog`, `ToolDef`: manifest tools, `tools_source` functions and hub tools, kept per mod in `kv` so a stopped mod's tools stay listed; search), `schema.py` (one flat schema per operation, `x-kind` file inputs, validation with fixes, `coerce`), `hub_tools.py` (the `hub_*` tools), `approvals.py` (permissions deny → ask → allow, modes, the `approvals` table), `calls.py` (`Calls`: run, follow jobs, cancel, resume after a restart), `results.py` (output references from paths and binary responses, the 8 KB cap), `api.py` (response models) |
| `routes/` | ✅ pkg | One FastAPI router per area, added with each area: `system.py` (`/api/system`, `/api/doctor`, `/config.js`), `events.py` (`/api/events`), `web.py` (`/`, `*.dc.html`), `services.py` (`/api/services/...`), `models.py` (`/api/models/...`), `outputs.py` (`/api/outputs/...`, file serving with Range), `memory.py` (`/api/memory`, `/plan`, `/acquire`), `metrics.py` (`/api/metrics`, `/series`, `/api/timeline`, `/api/outputs/stats`, `/api/activity/stats`, `/api/jobs/stats`), `widgets.py` (`/api/widgets/...`), `overview.py` (`/api/overview`), `settings.py` (`/api/settings`), `tools.py` (`/api/tools...`, `/api/approvals...`) |
| `tests/` | ✅ | pytest suite (below) |

## `utils/tests/`

Tests stay inside the hub package, as the plan specifies. Group them by area as they grow, so no folder becomes a flat dump:

```text
utils/tests/
├── conftest.py                 ✅     root, make_app/app/client (ASGI), fake_mod, hub_process, services_dir
├── fixtures/
│   ├── mods/                   ✅     _fakemod.py (stdlib server) + fake-ok (with a `requests` widget), fake-slow, fake-crash, fake-mem, fake-tools (agent tools of every kind: a job, file inputs, binary results, a tools_source)
│   └── openapi/                ✅     real OpenAPI captures from Phase 0.5: tts, gen3d, lcpp, relay; snapshots/ = their converted Operation[]
├── core/test_<behavior>.py     ✅     paths, config, db, events, server, cli, doctor, backup
├── web/*.test.mjs + test_api_js.py ✅  Node unit tests (web/api.js; mod-ui.js + the template page.js on a fake DOM; the chart helpers and dashboard layout; the mock history), run from pytest; test_contract.py: api.js routes ↔ hub routes, brief types ↔ response models, every route documented
├── services/test_<behavior>.py ✅     fake mods (manifest, backends, state machine, proxy, operations follow)
├── models/test_<behavior>.py   ✅     registry storage and status, routes, safe deletes, the scanner on a tree covering every rule, verify, used-by, alerts, the CLI (conftest: a fake data/models/)
├── outputs/test_<behavior>.py  ✅     what counts as an output, rows, the watcher, previews, routes (paging, Range, traversal), delete to trash, activity (conftest: a fake outputs/ tree; the host's ffmpeg inside a toolbox)
├── memory/test_<behavior>.py   ✅     proc facts on fake /proc and /sys, the planner, the sampler, make-room end to end with two fake-mem mods, triggers, idle unload (conftest: a fake memory source)
├── settings/test_<behavior>.py ✅     GET/PUT /api/settings and GET /api/overview against fake-ok
├── tools/test_<behavior>.py    ✅     the catalog (manifest + tools_source + hub tools, search, a stopped mod), calls (validation, permissions, approvals with edits, no bypass, capping, media, jobs, cancel, restart) against fake-tools
├── metrics/test_<behavior>.py  ✅     rollups, retention, gaps, the recorder on fake services, the chart routes and widgets against fake-ok (conftest: an open hub.db, a fake clock)
└── <area>/test_<behavior>.py          …
```

## `web/` — the UI

| File | Purpose |
| :--- | :--- |
| `Hub.dc.html`, `OutputCard.dc.html`, `JsonView.dc.html` | The shell and every core page; shared components. Claude Design's v1 export, with revision 2 (brief §11) built here in plan 6.5 |
| `chart-kit.js`, `charts.js` | Ours: the chart components of brief §11.6 (plain SVG on the page's React) and their shared frame, formatting and scales |
| `views.js` | Ours: the widget card and data hook, the Overview Table and Timeline views, and the charts on the other pages (memory, storage, outputs histogram, a mod's stat charts) |
| `dashboard.js` | Ours: the Overview Dashboard (KPI strip, widgets, Customize; brief §11.5) |
| `mock.js` | `createMockApi()`: the brief §6 contract on simulated data |
| `mock-history.js` | Ours: 7 days of seeded mock history for the chart methods (brief §11.9), with the Empty and Gaps scenarios |
| `api.js` | Ours, not the export: `createApi({base, liveAreas, mock})` routes each method to HTTP or the mock by area; `createHttpApi()` |
| `ModPage.dc.html` | Ours: the host that loads a mod's `ui/page.js` and calls `mount(el, ctx)` (brief §5) |
| `mod-ui.js` | Ours: `ctx.ui`, themed DOM helpers for page modules |
| `mod-kit.js` | Ours: shared pieces for the built-in mods' pages (Part B): `requireRunning`, `callRoom` (answers `needs_room` with a confirm, then retries with make-room), `segmented`, `panel`, `header`, `columns`, `stat`, `store`, formatting |
| `mod-form.js` | Ours: `schemaForm(ctx, schema, o)`: a form built from a JSON Schema (text, numbers with ranges, enums, booleans, files that upload or pick a recent output), for any mod page (plan 11.11) |
| `mock-comfy.js` | Ours: the comfy mod's API on the mock (packs, runs, imports, review, downloads, charts) |
| `viewer3d.js` | Ours: `mountViewer(el, {files, url, rig})`, the Viewer3D (orbit, file tabs, wireframe, part visibility, rig sliders), adapted from gen3d's viewer; three.js r16x is vendored in `vendor/three/` (its addons import it relatively, so no import map) |
| `mock-mods.js` | Ours: the built-in mods' native APIs on the mock (`createModMocks(m)`, moved out of `mock.js`): tts, gen3d (jobs with stages, live events, box GLBs), relay (DashLLM's `{dimensions, source}` stats, endpoints, tunnels), lcpp (instances, catalog, preflight, chat stream, downloads, relay, settings), comfy, transcribe |
| `mod-charts.js` | Ours: the §11.6 charts inside page modules: `chartCard` (a widget card with ranges, "View as table" and the data hook), `chart`, `rh` (createElement), `mountReact`, `waveform`, `wavSamples` |
| `support.js` | Claude Design's runtime. Generated: **never edit** |
| `vendor/` | three.js (`three/`, MIT, from 3DGenerate), React and ReactDOM 18.3.1 (UMD), `fonts.css` + `fonts/` (IBM Plex Sans, JetBrains Mono, OFL) |
| `PATCHES.md` | The UI's history (v1 export → revision 2 built here), hand edits since, and the mock-only states |

`GET /` serves `Hub.dc.html` with the vendor scripts and `/config.js` added before `support.js` (a page load gets an empty `<x-dc>`; the runtime fetches the template itself); see `utils/routes/web.py`. `/ui/services/<id>/…` serves a mod's `ui/` folder, and `/Mod_<id>.dc.html` its `ui/Page.dc.html`.

## `data/`

| Path | Tracked | Purpose |
| :--- | :--- | :--- |
| `data/models/registry.json` | yes | The models registry (architecture §8) |
| `data/models/<kind>/…` | no | Model weights (~190 GB once moved in) |
| `data/databases/` | no | `hub.db`, `relay.db`, `gen3d.db`, later `agent.db` |

## Conventions

- **File length:** aim for under 500 lines; split any file that passes 800.
- **Packages:** `uv` only (`uv add`, `uv sync`, `uv run`).
- **No `libs/`:** shared code lives in `utils/`, and mods share nothing with the hub except HTTP.
- **Mods** follow their own internal layout; the agent mod (Stage D) follows the layout in architecture §14.1 (`llm.py`, `loop.py`, `store.py`, `context.py`, `tools.py`, `prompts.py`, `server.py`).
