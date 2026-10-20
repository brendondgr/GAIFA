# AIHub — Repository structure

What is in the repo **today**, and where each planned piece goes. The full target layout and the reasons behind it are in [architecture.md §3](architecture.md#3-directory-layout). Update this file in the same commit whenever a file or folder is added, moved or removed.

**Status key:** ✅ exists · 🧱 placeholder folder (empty, `.gitkeep`) · ⏳ planned (with the plan step that creates it)

## Top level

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `README.md` | ✅ | The front page: what AIHub is, requirements, quickstart, commands, configuration, adding a mod |
| `docs/assets/` | ✅ | Images for the README (Overview page, a chat that makes an image and then a 3D model) |
| `CLAUDE.md` | ✅ | Short rules for agents, true today |
| `.claude/skills/aihub/` | ✅ | Project skill: how to work on AIHub (doc map, invariants, step workflow) |
| `.claude/skills/plan/` | ✅ | Project skill: how to write and amend plans in this repo's format |
| `.claude/skills/aihub-mod/` | ✅ | Project skill: building or porting a mod (points at `docs/mods.md`, requires `aihub check` to pass) |
| `.claude/skills/comfy-workflow/` | ✅ | Project skill: making and fixing ComfyUI workflow packs (points at `docs/workflows.md`) |
| `AGENTS.md`, `.agents/skills/` | ✅ | The same rules and skills for Codex and other agents that read `AGENTS.md`: copies of `CLAUDE.md` and `.claude/skills/` (refresh them when those change) |
| `.gitignore` | ✅ | Keeps models, databases, outputs and venvs out of git |
| `pyproject.toml` | ✅ | Hub dependencies (uv) |
| `uv.lock` | ✅ | Locked hub dependencies; `uv sync` builds `.venv/` (ignored) from it |
| `app.py` | ✅ | `python app.py [--port N] [--dev] [--no-autostart] [--demo-mods]` starts the hub on 127.0.0.1 and [::1] |
| `config.toml` | ✅ | User settings (architecture §9); a missing file means defaults |
| `bin/` | ✅ | `aihub` (bash wrapper → `utils/cli.py` with the hub venv) and `aihub.service.in` (unit template; `aihub install` fills in `@ROOT@`) |
| `docs/` | ✅ | Design, plan, UI brief, this file, `reference/` UI exports |
| `utils/` | ✅ | The hub's Python package (below) |
| `services/` | ✅ | One folder per mod. `_template/` is the mod `aihub new` copies: `service.toml`, `server.py` (FastAPI: health, status, hello, echo, note → outputs, a widget route), `requirements.txt`, `install.sh`, `README.md` (the contract on one page), `ui/page.js` |
| `data/` | ✅ | Models, databases, logs, runtime state and the agent's files (below) |
| `outputs/` | 🧱 | `<mod>/<YYYY-MM-DD>/…` (+ `.trash/`), ignored by git; indexed into `hub.db` |
| `web/` | ✅ | The UI (below) |

## `services/` (the mods)

The existing apps come in with `git subtree add` (their history is kept), so most of each folder is the app's own code. These are the parts added for AIHub; `comfy`, `agent` and `vllm` are new:

| Mod | From | Added for AIHub |
| :--- | :--- | :--- |
| `tts` | `~/Projects/LocalTTS` (plan Phase 7) | `service.toml`, `aihub-install.sh` (venv only), `localtts/outputs.py` (dated outputs + sidecars), `localtts/hub.py` (`/v1/status`, the "Clips per day" widget), `ui/page.js` (the Speech page: Speak and Voices tabs), `tests/` (`.venv/bin/python -m pytest` in the mod folder), `requirements-dev.txt`, `pytest.ini`; `bin/localtts` delegates to `aihub`; `scripts/install-runtime.sh` + `locks/` (the engine venvs in `runtime/venvs/` and the Breeze source in `runtime/breeze-tts/`, plan 12.1); `skills/voices/SKILL.md` (the agent's skill, plan 14.9) |
| `relay` | `~/Tools/DashLLM` (plan Phase 9) | `service.toml`, `aihub-install.sh` (`uv sync` in `web/backend`; npm for the dashboard), `web/backend/app/routes/admin_hub.py` (`/admin/status`, the "LLM traffic" widget), `web/backend/app/services/model_facts.py` (each model's context window, tools, vision and reasoning for `/v1/models` `meta`, plan 13.3) and `catalog.py` (the synthesized `/v1/models`, moved out of `proxy.py`), `tests/backend/test_model_facts.py`, `tests/backend/test_aihub.py`, `ui/page.js` (the LLM Relay page: Dashboard, Requests, Endpoints, Tunnels, Connect), `bin/relay` (delegates to `aihub`); default bind 127.0.0.1; `scripts/relay` removed |
| `opencode` | DashLLM's `opencode.service` (plan 9.4) | Manifest-only: `service.toml`, `run.sh` and `auth.sh` (from DashLLM's `scripts/opencode-serve.sh` / `opencode-auth.sh`), `.env` and `opencode-auth.env` (both gitignored), `README.md` |
| `lcpp` | `~/Models/LLMs` (plan Phase 10) | `service.toml`, `aihub-install.sh` (`uv sync`, Python 3.14), `src/lcpp/aihub.py` (memory acquire before a launch, downloads registered in AIHub, the page URL for the relay), `src/lcpp/daemon/routes/hub.py` (`/api/status`), `LCPP_MODELS_DIR` in `paths.py` (catalog paths are models-relative), `src/tests/test_aihub.py`, `ui/page.js` (the LLM Launcher page: Instances, Catalog, Playground, Relay publishing, Launcher settings); `lcpp service …` delegates to `aihub`; `runtime/` (llama.cpp, gitignored) copied over |
| `gen3d` | `~/Projects/3DGenerate` (plan Phase 8) | `service.toml`, `aihub-install.sh`, `gen3d/hub.py` (`/v1/status`, the "Job time per stage" widget), `store.py`'s dated job folders (`dir` column) and `output.json`, `scripts/migrate_jobs_to_outputs.py`, `tests/test_aihub.py`, `requirements-dev.txt` (pytest moved out of `requirements.txt`), `ui/page.js` (the 3D Generate page: Create and Jobs tabs), `desktop/3dgenerate-aihub.desktop`; `bin/gen3d` delegates to `aihub`; `scripts/install-runtime.sh` + `locks/cubeart.txt` (CubeArt in `runtime/CubeArt/`: the cube clone, caches and the container venv, plan 12.2); `skills/making-3d/SKILL.md` (plan 14.9); image engines (plan 17): `gen3d/engines.py` (Cube3D, Hunyuan3D 2.1, TRELLIS.2, SAM 3D Objects, SAM 3D Body: local or delegated to comfy), `gen3d/image_options.py` (their settings and presets), `gen3d/images.py` (the picture: fetch an output, `input.png` + the cut-out `input_rgba.png`), `gen3d/worker.py`'s `WorkerPool` (one container per engine family), `gen3d/comfy_engine.py` (TRELLIS.2 and SAM 3D Body as comfy packs through the hub), `gen3d/hubclient.py` (memory acquire per engine), `workers/proto.py` (the image workers' JSON-lines protocol, substages, fast-simplification), `workers/hunyuan_worker.py`, `workers/sam3do_worker.py`, `ui/image.js` (the image engine panel on the Create tab), tests `test_images.py`, `test_comfy_engine.py`, `locks/img3d.txt` + `locks/sam3do.txt` (their venvs, built by `install-runtime.sh` with the Hunyuan3D 2.1, SAM 3D Objects and DINOv2 clones in `runtime/`), `workers/shims/` (pure-PyTorch `spconv`, import stand-ins for gsplat, kaolin and open3d) with `tests/test_spconv_shim.py`; the lab that measured them is `runtime/lab/` (gitignored) |
| `agent` | new (plan Phases 13.5 and 14) | The chat agent, our own Claude-Code-style loop (`README.md`): `agent/` (`llm.py` the model client, `loop.py` turns, pauses, actions, fallback and compaction, `store.py` threads and the event log in `agent.db`, `context.py` messages, meter and compaction helpers, `tools.py` + `local.py` tools on demand and the local tools, `knowledge.py` AGENT.md, skills, memory in `data/agent/` and the user's preferences from the hub (plan 21.4), `records.py` turn records (`turns` in agent.db), `learn/mine.py` the miner (preferences inferred from card edits, answers and thumbs), `prompts.py`, `hubapi.py` AIHub over HTTP, `server.py` the API), `evals/` (the 41-task eval: `harness.py`, `tasks.py`, `run.py`; `vision.py` the vision check; `live.py` the live smoke test with real outputs; `sessions_live.py` the Phase 15 check on real mods; `meter_check.py` the context meter against reported usage), `tests/` (`fakemodel.py` a scripted model, `fakehub.py` a stand-in hub), `service.toml`, `install.sh`, `requirements*.txt` |
| `comfy` | new (plan Phase 11); ComfyUI itself runs in the `strix-halo-comfyui` toolbox on 8199 | The adapter package `comfy/`: `config.py` (`COMFY_*` settings), `db.py` (`comfy.db`: runs, per-task defaults), `server.py` (`create_app`), `hub.py` (`/v1/status`), `client.py` (ComfyUI's HTTP API), `control.py` (load = start ComfyUI, unload = `/free` + stop it, idle unload, the queue poller), `nodes.py` (`NodeCatalog`: `/object_info` cached in `data/object_info.json`), `convert.py` (editor workflow → API graph), `packs.py` (workflow packs, drafts, ComfyUI's view), `check.py` (missing nodes/models, mapping and task checks), `schema.py` (a pack's inputs as JSON Schema), `detect.py` (drafts a pack's `workflow.toml` from its graph), `resolve.py` (inputs → patched graph), `run.py` (`Runner`: queue, progress, results, sidecars), `api_run.py` (`/v1/run`, `/v1/jobs`, `/v1/queue`, `/v1/defaults`, `/v1/uploads`, `/v1/files`), `importer.py` (files, media metadata, zips and ComfyUI history → draft packs), `api_import.py` (`/v1/import`, saving and removing packs, `/v1/downloads`), `downloads.py` (missing model files, registered in AIHub), `tools.py` (agent tools: one per task, `list_workflows`, `run_workflow`; `/v1/tools`), `ui/page.js` + `ui/run.js` + `ui/import.js` (the Images & Video page: Workflows, Run, Import), `library.py` (cached analysis per pack), `tasks.py` + `tasks.toml` (tasks and shared input names), `api_workflows.py` (`/v1/workflows`, `/v1/tasks`), `cli.py` (`comfyui workflows …`), `logtail.py` (ComfyUI's log copied to the adapter's stdout); `skills/choosing-a-workflow/SKILL.md` (the agent's skill, plan 14.9); `bin/comfyui` (start/stop/status/logs/update ComfyUI in the toolbox; moved from `~/.local/bin/comfyui`), `extra_model_paths.yaml` (models from `$COMFY_MODELS`, custom nodes from the mod: `custom_nodes/` and `nodes/`); `nodes/aihub_nodes/` (AIHub's own ComfyUI nodes, tracked: the Qwen-VL patch-embed matmul fix, `AIHubTextEncodeQwenImage21` and the SAM 3D Body dtype fix, docs/workflows.md §9); `workflows/` (the packs: the development set, the held-out Qwen-Image-2.1 and Klein templates, the Qwen-Image-2.1 Turbo packs `qwen21-turbo-*`, the image-to-3D packs `trellis2-shape`, `trellis2-lowpoly`, `trellis2-draft` and `sam3d-body` that gen3d runs (plan 17.5); third-party packs are kept out of git by `workflows/.gitignore`), `scripts/download_qwen_image_2.1.sh`, `scripts/download_qwen_image_2.1_turbo.sh` (Turbo Q8_0 + FP8, sha256-checked), `scripts/fix_fp8_quant_metadata.py` (adds ComfyUI's per-layer metadata to a hybrid scaled-FP8 file; stdlib), `scripts/migrate_old_outputs.py`; gitignored: `custom_nodes/`, `user/` (ComfyUI's settings, database and its workflows folder) and `input/` (moved from `~/Models/ComfyUI-next`, symlinks left there), `data/`; `service.toml`, `install.sh`, `tests/` (`.venv/bin/python -m pytest` in the mod folder; `fakecomfy.py` is a fake ComfyUI; `fixtures/` holds the development workflows with ComfyUI's own API graphs and a trimmed `object_info.json`, plus `expected/` (hand-written input expectations scored by `scoring.py`), `holdout/` and `holdout-expected/` (plan 11.12); `transfer.py` scores the held-out set, `test_holdout.py` keeps it as regression tests) |
| `vllm` | new (plan Phase 18); vLLM runs in kyuz0's gfx1151 image on 7801 | The adapter package `vllm_mod/`: `settings.py` (`VLLM_*` settings, the GPU's GTT size), `profiles.py` (`Profile`, `load_profiles`, the `vllm serve` flags and the `podman run` line), `engine.py` (`Engine`: one vLLM container from load to unload, memory acquire, stages from its log, crash and timeout, adoption), `containers.py` (`Podman` in a transient systemd scope, and `FakeContainers`), `fake_engine.py` (a stand-in `vllm serve` for tests), `hubclient.py` (memory acquire, model registration), `downloads.py` (a profile's model into the HF cache, progress, registration in AIHub), `relay.py` (publishing the engine to the relay, its model facts, retry and reconcile), `metrics.py` (vLLM's `/metrics`, the stats sampler), `api_profiles.py` (the profile form's schema, save, delete), `server.py` (`create_app`: health, `/v1/profiles`, `/v1/load`, `/v1/unload`, `/v1/engine`, `/v1/engine/logs`, `/v1/status`); `profiles/*.toml` (one per model setup: `qwen3-0.6b`, `qwen3.6-35b-a3b-awq`); `service.toml` (the image pinned by digest), `install.sh` (venv, pulls the image), `requirements*.txt`, `pytest.ini`, `tests/` (`.venv/bin/python -m pytest` in the mod folder; `fixtures/metrics-0.31.txt` is the pinned image's `/metrics`), `README.md` |

## `docs/`

| File | Purpose |
| :--- | :--- |
| `architecture.md` | The agreed design: decisions, layout, mod contract, runtime, API, memory, registry, config, metrics, Stage D |
| `workflows.md` | ComfyUI workflow packs: the folder, `workflow.toml`, tasks, editing, the CLI, problems and fixes (plan 11.11) |
| `comfy-transfer-report.md` | Plan 11.12: the held-out ComfyUI workflows scored before and after fixes, what they found, and what's still a limit |
| `agent-architecture.md` | The chat agent's design and the research behind it: Claude Code's structure, the literature, frameworks considered, and facts checked on this machine (plan Phases 13–14) |
| `agent-eval.md` | Plan 13.5 and 14.12: the eval's and the live runs' results in short (the full account is the overnight report) |
| `report/` | The overnight report (Phases 13–16): `report.tex` and its parts, `build.py` (turns `data/*.json` from the eval, live and test runs into `gen/` tables and thumbnails), `gen/` (tracked). Local only, gitignored: `data/` (the runs' records), `img/` (UI screenshots, live outputs) and the built `report.pdf` |
| `test-plan.md` | The checks and edge cases for Phases 13–16, written before building them; results go in the overnight report |
| `backend-plan.md` | The build plan: Phases 0–16 with steps, checks and deliverables; steps are ticked as they land |
| `plans/comfy-qwen21-turbo.md` | Sub-plan: the Qwen-Image 2.1 Turbo packs (models, builder, packs, live runs, tests) |
| `plans/chat-uploads-and-fast-presets.md` | Sub-plan: `fast`/`draft` presets the agent can use, and uploading images in Chat |
| `plans/capabilities-and-learning.md` | A pointer: Stage H (Phases 20–22) was planned here and moved into the master plan in 20.1 |
| `design-brief-ui.md` | UI brief for Claude Design; §6 and §11.7 are the UI-facing API contract |
| `mods.md` | Writing a mod: the contract, the new → check → restart loop, the four UI levels, outputs/memory/tools, porting an app, fixing `aihub check` failures |
| `structure.md` | This file |
| `reference/ui-export-2026-10-04/` | Claude Design's Part A v1 export, the UI baseline (read-only reference) |
| `reference/chat-activity-2026-10/` | Screenshots of the Chat page's activity fold as built in Phase 19 (live and mock: running, waiting with the dock, done, a step opened; dark and light; phone width), replacing the design study |

## `utils/` — the hub package

Small subsystems are single files directly in `utils/`; anything that grows into several modules gets its own sub-package with an `__init__.py` (as `backends/` and `routes/` already do).

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `__init__.py` | ✅ | Package marker; nothing runs at import time |
| `paths.py` | ✅ | `Paths` (root, configurable dirs kept inside the root), `write_atomic()` |
| `config.py` | ✅ | `Config` (pydantic, §9), `load()`, `save()` via tomlkit, `service_override()`, loopback check |
| `db.py` | ✅ | `Database`: `hub.db` (WAL), migrations by `user_version` (001 activity/peaks/kv, 002 outputs, 003 metrics, 004 approvals and tool calls, 005 sessions, 006 tool records: refusals, filled, edited, duration, 007 prefs), one writer thread, locked per-thread readers, async helpers |
| `events.py` | ✅ | `EventBus` (per-subscriber queue, overflow → resync), `ActivityLog`, `Alerts`, `sse_stream()` |
| `server.py` | ✅ | `create_app()`, `Hub` (app state, live-area registry), lifespan, `HubError` + error envelope, static `web/` |
| `cli.py` | ✅ | Standard-library CLI behind `bin/aihub`: serve, install, start/stop/restart, status, logs, load/unload, open, url, doctor (local checks + the hub's `/api/doctor`) |
| `doctor.py` | ✅ | `GET /api/doctor` (plan 12.4): models on disk, manifests, paths outside the project and the allowlist, Stage D notes, ports, units, disk, offline mods |
| `cli_models.py` | ✅ | `aihub models list \| show \| scan [--add] \| verify` (standard library only, loaded on demand by `cli.py`) |
| `prefs.py` | ✅ | Preferences (plan 21.2–21.4; the hub tools `hub_set_preference`, `hub_list_preferences` are in `tools/hub_tools.py`; thumbs on outputs in `output_feedback`, migration 008): the `prefs` table (migration 007), checked against a tool's schema and `x-options`, `apply()` in the call path (after the capability defaults; explicit values and card edits win), carry-over and contradiction after an approval |
| `sessions.py` | ✅ | Sessions (plan Phase 15): snapshots of what runs and what's loaded (lcpp's instances with their launch specs), the restore plan and run through the memory manager, auto-save, the unclean-shutdown flag, restore at boot |
| `logfiles.py` | ✅ | Logs in `data/logs/` (plan 16.1): the per-mod shippers, rotation (10 MB × 5), reading back for the Logs tab, the hub's own log handler |
| `inventory.py` | ✅ | `aihub doctor --inventory` (plan 16.3): every path outside the project with its reason (allowlisted, runtime, outside) |
| `cli_backup.py` | ✅ | `aihub backup <folder>` (plan 12.5): online SQLite copies of every database, the registry, `config.toml` and `services/*/.env` in a dated owner-only archive (standard library only) |
| `cli_mods.py` | ✅ | `aihub new`, `aihub check`, `aihub install <id>`, `aihub rescan` (standard library only, loaded on demand by `cli.py`) |
| `manifest.py` | ✅ | `service.toml` schema (pydantic), `discover()` with collected errors, `effective()` config overrides, `launch_spec()` (placeholders + env), `start_order()` |
| `backends/` | ✅ | `base.py` (`Backend` protocol incl. `pids()`, `UnitState`, `LogLine`), `systemd.py` (`aihub-<id>.service` via `systemd-run`, journal logs), `subprocess.py` (child processes + log ring; tests and `--dev`) |
| `services/` | ✅ pkg | Running mods. `manager.py` (`ServiceManager`: start/stop/restart, logs), `discovery.py` (boot, adoption, autostart in `after` order, rescan), `health.py` (readiness, monitor, restart on failure, external mods), `status.py` (status polling, `validate()` for the §4.6 shape, job events), `loading.py` (load/unload via `[memory]`; Phase 5 adds make-room), `views.py` (`ServiceSummary` / `ServiceDetail` JSON), `check.py` (`aihub check`: the mod self-test), `model.py` (`Service`, `Timing`, `ServiceError`) |
| `proxy.py` | ✅ | `ANY /api/s/<id>/*`: streaming passthrough, hop-by-hop headers dropped, redirects kept inside the proxy |
| `operations.py` | ✅ | Mod OpenAPI → `Operation[]` (refs inlined, file fields, response kinds, hide globs, tools), cached per process start |
| `registry/` | ✅ pkg | Models registry (architecture §8): `model.py` (stored shape, validation, `RegistryError`), `store.py` (`Registry`: load/save `registry.json`, computed status, totals, filters, edit, delete with the in-use rule), `scan.py` (the scanner's grouping rules), `adding.py` (`POST /api/models/scan` filtering, `POST /api/models`), `verify.py` (`Verifier`: the one-at-a-time checksum queue), `alerts.py` (registry alerts and the once-a-minute watcher) |
| `outputs/` | ✅ pkg | Outputs index (architecture §4.7): `entries.py` (which files and folders are outputs, `scope_for`), `describe.py` (an output → its `outputs` row: sidecar, title, kind, main file, times), `media.py` (durations, sizes, previews via `wave`/Pillow/ffmpeg), `index.py` (`Outputs`: sync, reconcile, ingest, list/get, delete, files, previews), `upload.py` (Chat uploads → `outputs/uploads/<date>/`), `watch.py` (`watchfiles` watcher, startup rescan, trash purge), `trash.py` (`outputs/.trash/<date>/`, purged after 30 days), `announce.py` (batched activity items) |
| `proc.py` | ✅ | /proc and /sys facts: `meminfo`, `gpu`, process trees, PSS + DRM memory (`footprint`; RSS when `smaps_rollup` is unreadable), unit cgroups, unit globs, container pids, `port_listening`, `port_owner` |
| `memory/` | ✅ pkg | Memory manager (architecture §7): `source.py` (`ProcSource`: each mod's pids and footprint), `planner.py` (the load rule, `make_plan`), `manager.py` (`MemoryManager`: sampling, events, peaks, the `memory-high` alert, `ensure_room`, make-room, reservations), `triggers.py` (the proxy hook) |
| `metrics/` | ✅ pkg | Metrics (architecture §13): `store.py` (`Store`: series, samples on the 10 s grid, rollups with watermarks, retention, queries on an even `t` axis with gaps), `recorder.py` (`Recorder`: 10 s ticks from the memory snapshot and status stats, service/load/job history from events, closing rows at downtime, hourly rollup, the low-disk alert)) |
| `settings.py` | ✅ | The Settings page: `view()` (config.toml as the brief's `Settings`) and `save()` (partial saves, only changed values written, applied live; the port at the next start) |
| `widgets.py` | ✅ | `Widgets`: running mods' `[[ui.widgets]]`, their data fetched from each `source`, validated against `WidgetData` and cached for 30 s |
| `tools/` | ✅ pkg | Agent tools (plan Phase 13): `catalog.py` (`Catalog`, `ToolDef`: manifest tools, `tools_source` functions and hub tools, kept per mod in `kv` so a stopped mod's tools stay listed; search), `schema.py` (one flat schema per operation, `x-kind` file inputs, validation with fixes, `coerce`), `hub_tools.py` (the `hub_*` tools), `approvals.py` (permissions deny → ask → allow, modes, the `approvals` table), `calls.py` (`Calls`: run, follow jobs, cancel, resume after a restart), `options.py` (`x-options`, plan 20.1: per-choice `needs`/`excludes`/`default`/`allows`, filled defaults, refusals with a fix, the model's view, `aihub check`), `modcall.py` (`ToolError`, dry runs, a mod's error and its own `fix`), `edits.py` (which card fields the user really changed, plan 21.1), `records.py` (dry-run retention, per-tool usage), `results.py` (output references from paths and binary responses, the 8 KB cap), `api.py` (response models), `mcp.py` (the MCP endpoint, plan 13.4: JSON-RPC over streamable HTTP in both eras, `server/discover`, `tools/list`, `tools/call`, the Origin check), `mcp_approval.py` (MCP results, approvals as `input_required` elicitation with a signed `requestState`, `aihub_wait_approval`) |
| `routes/` | ✅ pkg | One FastAPI router per area, added with each area: `system.py` (`/api/system`, `/api/doctor`, `/config.js`), `events.py` (`/api/events`), `web.py` (`/`, `*.dc.html`), `services.py` (`/api/services/...`), `models.py` (`/api/models/...`), `outputs.py` (`/api/outputs/...`, file serving with Range), `memory.py` (`/api/memory`, `/plan`, `/acquire`), `metrics.py` (`/api/metrics`, `/series`, `/api/timeline`, `/api/outputs/stats`, `/api/activity/stats`, `/api/jobs/stats`), `widgets.py` (`/api/widgets/...`), `overview.py` (`/api/overview`), `settings.py` (`/api/settings`), `tools.py` (`/api/tools...`, `/api/approvals...`), `mcp.py` (`POST /mcp`), `skills.py` (`/api/skills...`), `sessions.py` (`/api/sessions...`), `prefs.py` (`/api/prefs...`); `system.py` also serves `/api/doctor/inventory` |
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
├── web/*.test.mjs + test_api_js.py ✅  Node unit tests (web/api.js; mod-ui.js + the template page.js on a fake DOM; the chart helpers and dashboard layout; the mock history; chat.test.mjs: the chat's Markdown, thread view, card and action registries, client errors and the scripted mock agent; chat-turn.test.mjs + chat-sample.mjs: the turn model on the design study's sample log; sessions.test.mjs: the session methods, the mock's plan and restore, the API tab's tool arguments; modpage.test.mjs also covers schemaForm's onchange), run from pytest; test_contract.py: api.js routes ↔ hub routes, brief types ↔ response models, every route documented
├── services/test_<behavior>.py ✅     fake mods (manifest, backends, state machine, proxy, operations follow)
├── models/test_<behavior>.py   ✅     registry storage and status, routes, safe deletes, the scanner on a tree covering every rule, verify, used-by, alerts, the CLI (conftest: a fake data/models/)
├── outputs/test_<behavior>.py  ✅     what counts as an output, rows, the watcher, previews, routes (paging, Range, traversal), delete to trash, activity, uploads (conftest: a fake outputs/ tree; the host's ffmpeg inside a toolbox)
├── memory/test_<behavior>.py   ✅     proc facts on fake /proc and /sys, the planner, the sampler, make-room end to end with two fake-mem mods, triggers, idle unload (conftest: a fake memory source)
├── settings/test_<behavior>.py ✅     GET/PUT /api/settings and GET /api/overview against fake-ok
├── sessions/test_sessions.py   ✅     save, switch and restore through the memory manager (fake-mem), auto-save at shutdown, the unclean flag, restore at boot, the tools
├── tools/test_skills.py        ✅     the mods' skills over /api/skills
├── tools/test_<behavior>.py    ✅     the catalog (manifest + tools_source + hub tools, search, a stopped mod), calls (validation, permissions, approvals with edits, no bypass, capping, media, jobs, cancel, restart), `x-options` (defaults, refusals, the model view, the check, a mod's own fix, the sibling-tool hint) and MCP (both eras, approvals, the `mcp` SDK against a hub process) against fake-tools
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
| `mod-options.js` | Ours: choices that follow the inputs (plan 20.7): `choices`, `defaultOf`, `labelOf`, `helpOf` over a schema's `x-options` (brief §11.12); `schemaForm` uses them, so the parameter card and mod pages list only what fits |
| `mock-comfy.js` | Ours: the comfy mod's API on the mock (packs, runs, imports, review, downloads, charts) |
| `viewer3d.js` | Ours: `mountViewer(el, {files, url, rig})`, the Viewer3D (orbit, file tabs, wireframe, part visibility, rig sliders), adapted from gen3d's viewer; three.js r16x is vendored in `vendor/three/` (its addons import it relatively, so no import map) |
| `mock-mods.js` | Ours: the built-in mods' native APIs on the mock (`createModMocks(m)`, moved out of `mock.js`): tts, gen3d (jobs with stages, live events, box GLBs), relay (DashLLM's `{dimensions, source}` stats, endpoints, tunnels), lcpp (instances, catalog, preflight, chat stream, downloads, relay, settings), comfy, transcribe |
| `mod-charts.js` | Ours: the §11.6 charts inside page modules: `chartCard` (a widget card with ranges, "View as table" and the data hook), `chart`, `rh` (createElement), `mountReact`, `waveform`, `wavSamples` |
| `sessions.js` | Ours: the Sessions panel (save, switch with the dry-run plan and live steps, rename, delete) and the "Restore last session?" prompt (Wire 15; brief §11.14) |
| `mock-sessions.js` | Ours: the `sessions` area on the mock (`createSessionMocks`): the same plan as `utils/sessions.py`, restored on the mock's services |
| `api-tool.js` | Ours: the API tab's tool runs (Wire 13): `ToolRun` (callTool → parameter card → decideApproval → progress → outputs) and `toolArgs` (form → flat arguments) |
| `mock-tools.js` | Ours: the `tools` area on the mock (`createToolMocks`): a small catalog with risk levels, calls as fake jobs, approvals (one pending from an MCP client) |
| `chat/` | Ours: the Chat page (plan 14.1; brief §11.13). `chat.js` the page (`ChatPage`, `getChatClient`; re-exports the registries), `chat-api.js` the agent client through `/api/s/agent` (SSE with reconnect `after=lastSeq`) or the mock, `chat-mock.js` the scripted mock agent, `chat-thread.js` events → card items (pure), `chat-turn.js` items → turns of steps with their live status and summary (pure, plan 19.2), `chat-activity.js` the **activity fold** per turn (a live status header with the thinking peek, then the summary; the step rows and the sentence a step opens to; `TurnView`), `chat-steps.js` the **step words registry** (`registerStep`: running and done labels, detail, the sentence a step opens to; built-ins and a fallback from the tool's name and schema; errors in plain words), `chat-cards.js` the **card registry** and the simple cards, `chat-forms.js` question and parameter cards (schemaForm, file pickers), `chat-results.js` the result card, the **preview registry** and the **output strip** (a turn's `#n` thumbnails, the picked one large with its preview capped at 300 px; plan 19.5), `chat-actions.js` the **actions registry** (result buttons, quick actions, derived from the tool catalog), `chat-list.js` / `chat-header.js` / `chat-composer.js` the page parts, `chat-md.js` the safe Markdown renderer, `chat-ui.js` tokens, icons, buttons, popover, prefs, `chat-settings.js` Settings → Agent (Show thinking retired in 19.4), `chat-approvals.js` the header's Approvals popover |
| `favicon.svg` | The AIHub logo: the browser tab's icon (the sidebar and header draw the same mark inline) |
| `support.js` | Claude Design's runtime. Generated: **never edit** |
| `vendor/` | three.js (`three/`, MIT, from 3DGenerate), React and ReactDOM 18.3.1 (UMD), `fonts.css` + `fonts/` (IBM Plex Sans, JetBrains Mono, OFL) |
| `PATCHES.md` | The UI's history (v1 export → revision 2 built here), hand edits since, and the mock-only states |

`GET /` serves `Hub.dc.html` with the vendor scripts and `/config.js` added before `support.js` (a page load gets an empty `<x-dc>`; the runtime fetches the template itself); see `utils/routes/web.py`. `/ui/services/<id>/…` serves a mod's `ui/` folder, and `/Mod_<id>.dc.html` its `ui/Page.dc.html`.

## `data/`

| Path | Tracked | Purpose |
| :--- | :--- | :--- |
| `data/models/registry.json` | yes | The models registry (architecture §8) |
| `data/models/<kind>/…` | no | Model weights (~190 GB once moved in) |
| `data/databases/` | no | `hub.db`, `relay.db`, `gen3d.db`, `agent.db` |
| `data/logs/` | no | `<mod>.log` and `aihub.log`, rotated at 10 MB, 5 kept (plan 16.1) |
| `data/state/` | no | Mods' runtime state that must survive a reboot, e.g. `lcpp/instances/` (plan 16.2) |
| `data/agent/` | no | The agent's `AGENT.md`, `memory/` (MEMORY.md + topic files) and your own `skills/<name>/SKILL.md` (plan 14.9) |

## Conventions

- **File length:** aim for under 500 lines; split any file that passes 800.
- **Packages:** `uv` only (`uv add`, `uv sync`, `uv run`).
- **No `libs/`:** shared code lives in `utils/`, and mods share nothing with the hub except HTTP.
- **Mods** follow their own internal layout; the agent mod (Stage D) follows the layout in architecture §14.1 (`llm.py`, `loop.py`, `store.py`, `context.py`, `tools.py`, `prompts.py`, `server.py`).
