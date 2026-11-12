# GAIFA — Architecture

> Agreed design, 2026-10-04. Companion docs:
> - [backend-plan.md](backend-plan.md): step-by-step build of the backend (Phases 0–51, closed); newer work has one plan per file in [plans/](plans/README.md)
> - [design-brief-ui.md](design-brief-ui.md): UI brief for Claude Design (its Sections 6 and 11.7 are the UI-facing API contract)
> - [reference/ui-export-2026-10-04/](reference/ui-export-2026-10-04/README.md): Claude Design's Part A v1, the UI baseline

## 1. Goal

GAIFA (*Great, Another Interface For Agents*, said "guy-fuh"; AIHub until the rename in plan Phase 50) is **one local app that controls every AI service on this machine**, from one UI and one API:
- the LLM relay and analytics (DashLLM)
- the llama.cpp launcher (lcpp)
- text to speech (LocalTTS)
- 3D generation (3DGenerate)
- later, image and video generation (ComfyUI) and a chat agent

It is built so that **anyone can add a service ("mod") by dropping a folder into `services/`**, with no changes to GAIFA's own code.

**Not goals, for now:**
- Access from anywhere but 127.0.0.1, accounts, or a login.
- Merging the apps' code into one process.
- Porting the Mango-Tree personal apps. They can come later as mods.

## 2. Decisions

| Topic | Choice | Why |
|---|---|---|
| Location | `/home/bdgr/Agents/GAIFA`, one git repo | requested |
| Shape | A **hub in front of mods**. Each mod is its own process. | The apps' torch/Python stacks conflict: Kokoro and Breeze need different ROCm torch builds, gen3d runs in a Python 3.13 container, and lcpp and relay use 3.14. Stopping a process is how GPU memory is freed. relay's event loop is tuned for concurrency, and lcpp's model instances must survive restarts. |
| Hub stack | Python ≥ 3.12, FastAPI + uvicorn + httpx, SQLite, uv | same as all four apps |
| Hub address | `127.0.0.1:7000`, no auth | only reachable from this machine; other devices on your own network only when you open it to them (`[hub.lan]`, plan lan-access), behind a password and their own rules, never the internet |
| Running mods | Each mod runs as a **temporary systemd user service** (`gaifa-<id>.service`), started with `systemd-run`; where there's no systemd user manager (macOS), a **detached process** with a pidfile in `data/state/hub/pids/` that is adopted after a hub restart (`[hub] backend`, plan 37.1) | the pattern lcpp already uses for models: survives hub restarts, logs go to journald, no unit files per mod |
| Installed services | Only `gaifa.service` (runs `app.py`) | today there are four separate ones |
| Mod contract | `service.toml` + an HTTP server on 127.0.0.1 + a health check | any language; all four apps already fit with small changes |
| API | Hub routes at `/api/*`, plus **every mod's own API at `/api/s/<id>/*`**, plus an operations list built from each mod's OpenAPI | generic UI pages and the future agent's tools come from the same source |
| Models | `data/models/<kind>/…`, with `data/models/registry.json` tracked in git | self-contained; recorded sources make lost files re-downloadable |
| Databases | `data/databases/*.db` | one place |
| Outputs | `outputs/<mod>/<YYYY-MM-DD>/…` + an optional JSON sidecar per output, indexed by a watcher | everything generated, in one browsable place |
| Memory | A hub-side **memory manager**: before a load it makes room by unloading idle mods. Mods can also ask for memory directly. | 121 GB of unified memory shared by every model, and today no app knows about the others |
| UI | **Claude Design's `.dc.html` format** (templates + `support.js`, rendered by React 18) is kept as the source in `web/`. React and ReactDOM are served from `web/vendor/`. No build step and no CDN. | Claude Design keeps iterating on the real UI, so there's no hand-port to drift out of sync. The v1 export is the baseline. |
| Wiring the UI | A **hybrid `api`**: each area (services, memory, models, …) switches from mock to live as its backend phase lands. `/config.js` lists the live areas. | Every phase ends with real, visible UI, and the UI is complete from day one. |
| Look | **Compact by default**, with charts everywhere and four Overview views (Dashboard, Services, Table, Timeline) | requested; the design brief's §11 is Part A revision 2 |
| Metrics | The hub records time series in `hub.db` (10 s samples kept 48 h, 1 min rollups 14 d, 1 h rollups 400 d) | charts need history, not just the current value |
| Mod UIs | Optional `services/<id>/ui/page.js` or `ui/Page.dc.html`, plus optional dashboard widgets (`[[ui.widgets]]`). Without them, a mod still gets a full generic page, and its numeric stats are charted automatically. | adding a mod needs no UI work |
| Chat, agent, save states | **Built last** (backend-plan Stage D): the agent is a mod with **its own loop, modelled on Claude Code** (no agent framework): tools load on demand, it asks for choices with question and parameter cards, threads are an append-only event log in SQLite; sessions can be saved and restored; logs and runtime state move inside the folder | requested: do these once everything else is built. Research: [agent-architecture.md](agent-architecture.md). A framework (LangGraph) was the earlier plan; a hand-written loop gives the control a local model needs (thinking fields, leaked tool calls, tool loading) |
| Git history | The existing repos were merged in with `git subtree` (2026-10-06); `relay`, `lcpp`, `tts` and `gen3d` are now git submodules of their own repositories (Relay, LLMs, LocalTTS, 3DGenerate), pinned per commit (plan mod-repos) | keeps every app's history, and each app stays a repository of its own that runs without GAIFA |
| Writing outside the folder | Nothing is written outside the project root, except the allowlist (plan 12.4) and **workspace folders the user set to Edit or above** (plan Phase 27). The GAIFA folder and `data/models/` are capped at Read. | requested 2026-10-20: the agent edits your projects in place, and only where you raised the folder's level |
| Heavy runtimes (engine venvs, CubeArt, the ROCm image) | Referenced where they are first, moved inside later | Python venvs can't be moved, so they must be recreated; don't break working GPU stacks while migrating |
| Mod ids | `relay`, `opencode`, `lcpp`, `tts`, `gen3d`, `comfy` | They become URLs (`/api/s/tts/…`, `#/s/tts`), so they are fixed once chosen. |
| Ports | Keep 4000 / 4096 / 7710 / 5040 / 5050. comfy adapter 5070 (ComfyUI itself on 8199). New mods use 5100–5199: `web` 5102, `workspace` 5103, `embed` 5104, `stt` 5105, `searxng` 5106, `decide` 5107, `mcp` 5108, `calendar` 5109, `voice` 5110. | clients such as video-maker keep working |

## 3. Directory layout

```
GAIFA/
├── CLAUDE.md                short, only rules that are true today
├── app.py                   `python app.py` starts the hub (same as `gaifa serve`)
├── config.toml              your settings: hub, paths, memory rules, per-mod overrides
├── pyproject.toml, uv.lock  hub dependencies (uv); the hub's venv is the hidden `.venv/`
├── bin/
│   ├── gaifa                the command: start · stop · status · logs · new · install · doctor · backup …
│   └── gaifa.service.in     systemd unit template, used by `gaifa install`
├── docs/                    this file, backend-plan.md, design-brief-ui.md, structure.md (what exists today), reference/ (UI exports)
├── utils/                   the hub's code (Python package)
│   ├── server.py            create_app(): FastAPI app, lifespan, static web/, error envelope
│   ├── config.py            load, validate and save config.toml (comments kept)
│   ├── paths.py             project paths, atomic writes
│   ├── db.py                hub.db: SQLite, migrations
│   ├── events.py            event bus, SSE, activity log, alerts
│   ├── manifest.py          service.toml schema, validation, placeholders
│   ├── services.py          finds mods, runs their state machines, polls health and status
│   ├── backends/            systemd.py (real), subprocess.py (tests and --dev)
│   ├── proxy.py             /api/s/<id>/* passthrough (streaming, SSE, uploads, WebSockets)
│   ├── operations.py        mod OpenAPI → Operation[]
│   ├── memory/              memory sampling, plans to make room, reservations, triggers, acquire
│   ├── proc.py              meminfo, AMD GPU sysfs/fdinfo, per-process memory (from lcpp) and GPU engine time
│   ├── registry/            models registry: storage, status, scan, verify, add, delete
│   ├── outputs/             outputs index: what counts, rows, media details and previews, watcher, trash
│   ├── tools.py             (later) agent tool catalog and approvals
│   ├── cli.py               standard-library-only CLI behind bin/gaifa
│   ├── routes/              one FastAPI router per area
│   └── tests/               pytest, grouped by area (<area>/test_<behavior>.py); fixtures/mods/ holds fake mods
├── services/                one folder per mod (see §4); relay, lcpp, tts, gen3d are submodules (`.gitmodules`)
│   ├── _template/           what `gaifa new <id>` copies
│   ├── relay/  opencode/  lcpp/  tts/  gen3d/  comfy/
├── data/
│   ├── models/
│   │   ├── registry.json    the only tracked file under data/
│   │   ├── llm/             <Name>/*.gguf (+ mmproj-*, mtp-*, split parts)
│   │   ├── tts/             breeze-tts-2/, …
│   │   ├── stt/             <model>/ (faster-whisper: small/, large-v3-turbo/, …)
│   │   ├── voices/          <slug>/reference.wav + voice.json
│   │   ├── 3d/              cube3d-v0.5/, cubepart/, Qwen3-VL-4B-Instruct/, clip-vit-large-patch14/
│   │   ├── comfyui/         ComfyUI's own layout: diffusion_models/, text_encoders/, vae/, loras/, unet/, …
│   │   └── hf-cache/        HF_HOME for every mod
│   ├── databases/           hub.db, relay.db, gen3d.db (+ agent.db in Stage D)
│   ├── logs/                Stage D: per-mod logs (until then: journald)
│   └── state/               Stage D: runtime state, e.g. lcpp's instance records (until then: $XDG_RUNTIME_DIR);
│                            ui/<scope>.json: what each page remembers (settings-that-stick 4.1)
├── outputs/                 <mod>/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext> (+ .json sidecar) or a folder per job
└── web/                     the UI in Claude Design's .dc.html format (v1 export; revision 2 built here)
    ├── Hub.dc.html          shell + core pages (served at /, with vendor scripts and /config.js injected)
    ├── *.dc.html            shared components: OutputCard, JsonView, ModPage
    ├── charts.js …          ours: chart kit, Overview views and dashboard (brief §11.4–11.6)
    ├── support.js           Claude Design runtime (generated; never edited)
    ├── mock.js              mock API (the brief's Section 6 contract)
    ├── api.js               ours: HTTP client + the hybrid mock/live switch
    ├── PATCHES.md           any edits made to an export, so they can be re-applied after the next one
    └── vendor/              react, react-dom (and fonts, so it works offline)
```

**Rule:** shared things live in `data/` and `outputs/`. Everything a mod needs to *run* (code, venvs, binaries, private state such as lcpp's catalog JSON, secrets in `.env`) lives in its own folder, so deleting `services/<id>/` removes the mod completely.

**Tracked in git:** code, manifests, `config.toml`, `data/models/registry.json`, docs, `web/`.

**Ignored:** `data/models/**` (except the registry), `data/databases/`, `outputs/`, every `.venv/`, `services/*/runtime/`, `services/*/.env`.

> ⚠ **Never run `git clean -x` or `-X` here.** They delete ignored files, and here that means ~190 GB of model weights. This rule goes in CLAUDE.md.

## 4. The mod contract

### 4.1 Required
1. A folder `services/<id>/` containing `service.toml`. `id` matches `[a-z][a-z0-9-]{1,31}` and equals the folder name.
2. A process that serves HTTP on `127.0.0.1:<port>`, in any language.
3. A health route that returns 2xx when ready.

### 4.2 Optional capabilities

| Capability | How | What you get |
|---|---|---|
| Memory management | `[memory]` with `load` / `unload` operations and `estimate_gb` | appears in the memory panel; the hub can unload it to make room |
| Status | `status` route returning the shape in §4.6 | load state, busy/idle, KPIs on its Overview tile, jobs in the header |
| Outputs | write into `{outputs}` (§4.7) | shows on the Outputs page automatically |
| Models | `[models] dirs` | registry entries in those folders (or deeper, e.g. `comfyui/loras`) are listed as "used by" this mod, and their files can't be deleted while it holds them |
| Custom page | `ui/page.js` or `ui/Page.dc.html` (UI brief §5) | own tabs inside the GAIFA shell |
| Main view | `[ui] main = { label, after = "chat" }` with `[ui] page` (calendar 3.1): the page module's `main: { mount(el, ctx) }` at `#/<id>`, full height; the mod's id can't be a hub page | a sidebar item after Overview, Chat or Outputs, with its manifest icon in the same muted colour and its badge, like the hub's own pages (the Calendar) |
| Chat panel | `[ui] chat_panel = { module = "ui/panel.js", label }` (calendar 7.1): `export default { mount(el, ctx) }` | a side panel on the Chat page, opened from the Chat header |
| Notifications | `POST /api/notify` (§6, calendar 2.1) | toasts with actions, an activity item, an unread badge on its sidebar item |
| Chat module | `[ui] chat = "ui/chat.js"` (plan 44.1, [mods.md](mods.md)): `export default function setup(chat)` registers the mod's step words and cards; listed as `chat_url` | its own cards in Chat (a live card while its job runs, its result) |
| Dashboard widgets | `[[ui.widgets]]` pointing at a route that returns `WidgetData` (UI brief §11.7) | its charts on the Overview dashboard |
| Charts for free | numeric values in `stats` (§4.6) | each one is recorded as a series `svc.<id>.stat.<slug>` and drawn as sparklines and charts |
| API polish | `[api]` hide list and response-kind overrides | a cleaner API tab |
| Agent tools | `[tools]` | operations the future agent may call, with optional approval |
| Call back into the hub | `GAIFA_URL` env | register models, ask for memory |

### 4.3 `service.toml` reference

```toml
id = "tts"                          # = folder name
name = "Speech"
description = "Text to speech, voice cloning and voice design"
icon = "wave"                       # icon key in web/js/components.js
version = "0.4.0"                   # optional

[run]
kind = "process"                    # "process" (default) | "external" (hub only health-checks + proxies)
command = [".venv/bin/python", "-m", "localtts"]   # relative paths resolve against the mod folder
cwd = "."                           # relative to the mod folder
port = 5040                         # default; config.toml may override
health = "/health"
status = "/v1/status"               # optional (§4.6)
openapi = "/openapi.json"           # default
env = { LOCALTTS_PORT = "{port}", LOCALTTS_OUTPUTS_DIR = "{outputs}" }
env_file = ".env"                   # optional, gitignored (secrets)
start_timeout_s = 60
stop_timeout_s = 180
restart = "on-failure"              # "no" | "on-failure"
after = ["relay"]                   # start ordering only, not a hard requirement
install = "install.sh"              # optional; run by `gaifa new` / `gaifa install <id>`
installed = [".venv/bin/python"]   # optional: what exists once the mod is set up, any one of them (default: the command's first word); a mod whose command is a tracked script names its real dependency (opencode: its binary where run.sh looks), so the hub doesn't autostart it before setup

[run.variants.cuda]                 # optional (plan 38.3): env for one variant (rocm | cuda | xpu | mps | vulkan | cpu), over [run].env
env = { MYMOD_ATTENTION = "flash" }

[memory]                            # only for mods that hold models in memory
estimate_gb = 9.2
vram_gb = 6.0                       # optional (plan 36.2): VRAM on a dedicated GPU; where GPUs share the RAM it adds to estimate_gb
load = "POST /v1/load"
unload = "POST /v1/unload"
triggers = ["POST /v1/speech", "POST /v1/audio/speech"]   # proxied calls that may load models
extra_units = []                    # other systemd units counted as this mod's memory, e.g. "lcpp-*.service"
containers = []                     # podman containers counted as this mod's memory (globs allowed)
idle_unload_s = 180                 # the mod's default; config.toml may override (0 = never)
idle_unload_env = "LOCALTTS_IDLE_UNLOAD_S"   # the variable the mod reads it from (GAIFA_IDLE_UNLOAD_S is always set too)

[llm]                               # optional (plan llm-servers 3.1): local language-model engines (lcpp, vllm), one contract
catalog = "GET /v1/llm/catalog"     # {models: [{id, name, format, size_gb, memory_gb, context, downloaded, loaded, relay_model?}]}
load = "POST /v1/llm/load"          # {id} → 202 (the mod asks GAIFA for memory itself)
unload = "POST /v1/llm/unload"      # {id} or {} for all
engine = "GET /v1/llm/engine"       # {state, loaded: [ids]}; `gaifa check` reads catalog and engine

[models]
dirs = ["tts", "voices"]            # data/models subfolders this mod uses

[outputs]                           # its presence means the mod writes to {outputs}
kinds = ["audio"]

[ui]
page = "ui/page.js"                 # optional custom page (or "ui/Page.dc.html")
chat = "ui/chat.js"                 # optional chat module: its own cards in Chat (plan 44.1)
main = { label = "Calendar", after = "chat" }   # optional (calendar 3.1): page.js's `main` as a main view at #/<id>
chat_panel = { module = "ui/panel.js", label = "Calendar" }   # optional (calendar 7.1): a side panel in Chat
native = "/ui/"                     # optional: the mod's own UI, linked from its page header
logo = "ui/logo.svg"                # optional (plan 33.1): .svg, .png or .webp inside ui/; unset = ui/logo.svg if it exists

[[ui.widgets]]                      # optional: charts for the Overview dashboard
id = "clips"
title = "Clips per day"
kind = "bar"                         # line | area | bar | donut | number | table
source = "GET /v1/hub/widgets/clips" # returns WidgetData; receives ?range=
ranges = ["7d", "30d"]
span = 4                             # grid columns out of 12

[api]
hide = ["GET /ui/{path}"]              # globs on "METHOD /path", e.g. "* /admin/*"
[api.responses]                     # response kinds FastAPI can't infer
"POST /v1/speech" = "audio"
"POST /v1/audio/speech" = "audio"

[tools]                             # the agent's tools (plan 13.1): <mod>_<name>, schema from the OpenAPI
speak = { op = "POST /v1/speech", description = "Speak text in a saved voice", risk = "generate", ask = ["name"], hide = ["stream"] }
delete_voice = { op = "DELETE /v1/voices/{name}", confirm = true }
# fetch = { op = "POST /v1/fetch", risk = "network", grant_key = "url:host" }   # grant_key: url:host | arg:<name> | const:<x> (§14.7)
# read = { op = "POST /v1/read", risk = "read", cap_kb = 64 }   # results kept whole up to 64 KB (default 8)
# risk: read | write | generate | network | execute | destructive (default: read for GET, destructive for DELETE/confirm, else write; §14.7)
# ask = [...] inputs the user chooses (parameter card) · examples = [{...}] · core = true (always loaded)
# hide = [...] / fixed = {...}: parameters kept from the model / always sent
# mcp = false: the chat's only, left out of /mcp (the agent's own tools, such as memory; structured-memory 3.1)
# job = true + job_status = "GET /v1/jobs/{id}" (+ job_cancel): the hub follows the job to its outputs

[agent]                             # optional: tools the mod lists at runtime (comfy: one per task)
tools_source = "GET /v1/tools"      # read at start and whenever status's tools_rev changes (§4.6) → {"tools": [{"type": "function", "function": {name, description, parameters}, "op": "POST …", "job": {…}|null, "risk", "ask", "examples", "core", "grant_key"}]}
skills = "skills"                   # optional: skills/<name>/SKILL.md for the agent (plan 14.9)
```

`config.toml` may override `port`, `env` (merged), `enabled`, `autostart`, `idle_unload_s`, `auto_unload` and `priority` per mod.

**Parsing rules** (`utils/manifest.py`):
- Only `id` and `[run].port` are required, plus `[run].command` for `kind = "process"`. `name` defaults to the id, `icon` to `box`.
- Unknown keys are errors, so a typo is reported rather than ignored. Each problem becomes one entry in the mod's `manifest_errors`; a broken mod is still listed (by folder name) and never stops the hub.
- `command` is a list, or a string split like a shell would. The executable resolves against the mod folder when it contains a `/` (`.venv/bin/python`); a bare name (`python3`) is looked up on `PATH`. Other arguments starting with `./` or `../` also resolve against the mod folder; the rest are passed as written (relative to `cwd`).
- Numbers and booleans in `env` become strings (`2` → `"2"`, `false` → `"false"`).
- Operations (`[memory]`, `[[ui.widgets]].source`, `[tools]`, `[api.responses]` keys) are written `"METHOD /path"`.
- `[ui].page` must be inside the mod's `ui/` folder, and so must `[ui].logo` (an `.svg`, `.png` or `.webp`). The summary's `logo_url` is `/ui/services/<id>/<file>`, or null when the file is missing.
- Two mods can't share a port, and no mod may use the hub's port.
- Mods not mentioned in `config.toml` are enabled and autostart, once they're installed: a mod whose command doesn't exist yet (no venv, binary or script) isn't autostarted and shows `not installed: run gaifa setup <id>` as its last error (plan 23.12).

### 4.4 Placeholders and environment

**Placeholders** (allowed in `command`, `cwd` and `env` values):

| Placeholder | Value |
|---|---|
| `{root}` | project root |
| `{service_dir}` | `services/<id>` (absolute) |
| `{port}` | the mod's port |
| `{models}` | `data/models` (absolute) |
| `{outputs}` | `outputs/<id>` (absolute; created on start) |
| `{databases}` | `data/databases` (absolute) |
| `{hf_home}` | `data/models/hf-cache` |
| `{hub_url}` | `http://127.0.0.1:7000` |

An unknown `{lowercase_name}` is an error when the mod starts. Other braces (JSON, `{UPPER}`) are left alone, and `env_file` values are never expanded.

**Environment layers**, later ones winning: the hub's variables below → `env_file` → `[run].env` → `config.toml`'s `[services.<id>].env`.

**Environment every mod gets:** `GAIFA_URL`, `GAIFA_SERVICE_ID`, `GAIFA_PORT`, `GAIFA_ROOT`, `GAIFA_MODELS`, `GAIFA_OUTPUTS`, `GAIFA_DATABASES`, `HF_HOME` (unless the mod sets its own) and `PYTHONUNBUFFERED=1`. A mod with `[memory]` also gets `GAIFA_IDLE_UNLOAD_S` (seconds, `0` = never) and the same value under its `idle_unload_env` name, after `[run].env` and before `config.toml`'s env. A mod whose variant `gaifa setup` recorded (`[services.<id>] accel`, plan 38.3) gets `GAIFA_ACCEL` (that accel), `GAIFA_DEVICE` (torch's device string: `cuda` for CUDA and ROCm, `xpu`, `mps`, `cpu`) and `GAIFA_GPU_ARCH` (gfx1151, sm_89, …), and its `[run.variants.<accel>].env`, after `[run].env`. When that accel isn't on this machine, the mod is **unavailable**: autostart skips it and starting it answers `409 unavailable`, with the reason in `ServiceSummary.unavailable`. Every mod gets `GAIFA_CONTAINER_RUNTIME` (`podman` or `docker`, from `[containers] runtime`, plan 37.4) when one is installed. On a machine with more than one GPU that can compute, a mod started on one GPU (`[services.<id>] gpu = <index>`, or the freest card under `auto`, the default; plan 36.3) also gets `GAIFA_GPU_INDEX` and its vendor's visible-devices variable: `CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`, or `ONEAPI_DEVICE_SELECTOR` and `ZE_AFFINITY_MASK`, counted among that vendor's GPUs.

### 4.5 Port rules
- A mod keeps the port in its manifest unless `config.toml` overrides it.
- `gaifa new` picks the first free port in 5100–5199.
- If the port is taken by something other than the mod's own unit, the start fails with `port_in_use` and names the process holding it.

### 4.6 Status shape (optional `[run] status` route)

```json
{
  "loaded": true,
  "busy": false,
  "idle_s": 42.0,
  "memory_estimate_gb": 9.2,
  "tools_rev": "a41c09e2",
  "stats": [{"label": "Voices", "value": 3}, {"label": "Clips today", "value": 12}],
  "jobs": [{"id": "j_1", "label": "low-poly fox", "progress": 0.4, "state": "running", "route": "#/s/gen3d/jobs?id=j_1"}]
}
```

- **`loaded`**: models are in memory; omit or set `null` if the mod has none.
- **`memory_estimate_gb`**: optional; overrides the manifest estimate, for example per workflow.
- **`tools_rev`** (plan 51.1, optional): a string or integer (1–64 characters) that changes whenever the mod's tools do. The tool catalog reads a mod's tools once per process start, and again on the next read after its `tools_rev` changes, so a `tools_source` that grows while the mod runs (comfy's, as packs become ready) reaches the agent, `/api/tools` and `/mcp` without a restart. Without it, a changed list waits for the next start.
- **Polling:** every 2 s while loading, busy or running jobs, otherwise every 10 s, only while the mod is ready. Invalid parts of the body are ignored (`gaifa check` lists them).
- **`jobs`**: each `{id, label, progress (0–1 or null), state, route?, live?}`, with `state` one of queued, running, done, failed, cancelled. Report finished jobs with their final state; a job that just disappears is shown as `done`. `route` must start with `#/` (a page in GAIFA); anything else is dropped and reported.
- **`live`** (plan 44.2, optional, on a status job and on a job's own status route that a tool follows): `{stage, stages: [{id, label, state, eta_s}], step, steps, eta_s, frames, preview: {url, seq, w, h}, lines: [done, of], audio}`, every field optional. `preview.url` and `audio` are paths on the mod; the hub rewrites them to `/api/s/<id>/…` and caps the object at 4 KB (`utils/live.py`). A running tool call carries it (`GET /api/tools/calls/{id}`, which with `?wait=&changed=true` answers at the next change), the agent passes it on its transient `progress` event, and `Job.live` goes out with the jobs. Whatever shows the job (a chat card, the Overview, a mod page) fetches the preview frame when `seq` changes.
- **Fixes on errors** (plan 46.5, `utils/tools/fixes.py`): a tool call that fails after it ran gets `error.fixes` (start or restart the mod, free the GPU, retry, retry with a lighter preset, the setup command) and `error.log` (the mod's log lines that name the error). The agent reads them with the error; Chat shows them as a fix-it card. A call refused before it ran (bad arguments, an unknown tool, a denial) gets none, nor does one the mod answered with its own `fix` (web's "answered HTTP 403 … try another source": restarting the mod wouldn't help), unless it ran out of memory.
- **`stats`**: at most 4 entries. **Numeric `value`s are recorded** each time status is polled, as the series `svc.<id>.stat.<slug(label)>`. That powers tile sparklines and the mod's charts with no extra work. Counters that reset ("… today") should say so with `"reset": "daily"`, so charts don't show the reset as a drop.

### 4.7 Output conventions
- **Where:** write into `{outputs}/<YYYY-MM-DD>/`.
- **File outputs:** name them `<HHMMSS>-<slug>.<ext>`. Write to `<name>.part` first, then rename; the watcher ignores `*.part` and dotfiles.
- **Folder outputs** (e.g. a 3D job): a folder `<id>-<slug>/`. Write `output.json` with `"complete": false` when you create it and set `"complete": true` when the job is done: a folder with `output.json` is indexed as one output, and only once it is complete. A folder **without** `output.json` is just a folder: each file in it is its own output (so a mod's own subfolders, like ComfyUI's, work as they are).
- **Sidecar:** `<file>.json` next to a file output (`<stem>.json` works too), or `output.json` inside a folder output. Every field is optional. `title`, `kind`, `main`, `preview`, `complete`, `created_ts` (unix seconds, for outputs copied in later) and `hidden` steer the index. **Hidden outputs** (plan 30.9): `"hidden": true` keeps an output out of the lists people see: `GET /api/outputs` and its totals (unless `include_hidden=true`; `totals.hidden` counts them), the Overview's recent outputs, the agent's output search, the outputs chart, the activity feed and the embed library. By id, its files, `/text`, `/search`, the viewer, citations and delete work as for any output. The web mod saves every page and PDF this way: they are for the agent's reading, not the user's outputs. `[outputs] hidden_keep_days` (§9; default 0, off) moves hidden outputs older than that to the trash. For the rest, everything else is shown as the output's metadata:

```json
{
  "title": "Good morning",
  "kind": "audio",
  "main": "rigged.glb",
  "preview": "preview.png",
  "complete": true,
  "prompt": "Good morning, everyone.",
  "model": "breeze-tts-2",
  "voice": "brendon",
  "seed": 1234,
  "params": {"speed": 1.0},
  "source": {"service": "tts", "request_id": "r_8f2a"}
}
```

- **Kind from extension**, when the sidecar doesn't give one:
  - audio: wav, mp3, flac, ogg, opus, m4a, aac
  - image: png, jpg, jpeg, webp, gif, bmp, avif
  - video: mp4, webm, mov, mkv
  - model3d: glb, gltf, obj, ply, stl, fbx
  - text (plan 24.1), with a `subtype` from the extension:
    - `markdown`: md, markdown · `plain`: txt, log, rst · `subtitles`: srt, vtt · `notebook`: ipynb
    - `code:<language>`: py, js, mjs, ts, tsx, jsx, rs, go, c, h, cpp, hpp, cc, java, kt, swift, rb, php, lua, sh, bash, zsh, fish, ps1, sql, r, jl, cs
    - `config:<format>`: toml, yaml, yml, ini, cfg, conf, env.example, xml · `web:<format>`: html, htm, css, scss · `data:<format>`: json, jsonl, csv, tsv
  - document: pdf, docx, epub, pptx, xlsx, odt (the subtype is the extension)
  - archive: zip, tar, gz, 7z
  - anything else is `other`
  - `Output.subtype` is set for text and documents. Text files are served as `text/plain` (an uploaded HTML page never runs on the hub's origin), every file with `X-Content-Type-Options: nosniff`.
- **Without a sidecar:** the title is the name as words (minus the `HHMMSS-` prefix); the time is the date folder plus that prefix, else the file's mtime. A folder's main file is the first model3d, then video, image, audio file.
- **Uploads:** images, video, audio, text and documents (plan 24.1; a text file must be UTF-8, or UTF-16 with a BOM, else `upload_encoding`) sent to `POST /api/outputs/upload` land in `{outputs}/uploads/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext>` with a sidecar (`title` = the original name, `source.service = "upload"`), so they are outputs of the service `uploads` like any other.
- **Previews:** the hub makes them itself (a 640 px JPEG for images over 4 MP, a video poster frame at 1 s via ffmpeg) and stores them as hidden `.<name>.preview.jpg` files next to the output. A 3D job brings its own (`preview` in the sidecar, or `preview.png`).
- **Text** (plan 24.2): the hub extracts the text of text and document outputs (`utils/outputs/text.py`: PDFs with `pypdfium2`, each page starting `--- page N ---`; docx, odt, epub, HTML and notebooks with the standard library; pptx and xlsx are left to the workspace sandbox) with page offsets, an outline (bookmarks, heading styles, `#` lines), a token estimate (chars / 4) and the PDF pages without a text layer. It is cached in `{outputs}/.text/<id>.json` (rebuilt when the file changes, warmed when the output is indexed) and cut at 4 M characters. Reading has limits, so a small file can't take the hub's memory: a docx, odt or epub unpacks at most 50 MB a file and 200 MB a document, parsed as it unpacks (at most 500,000 XML elements in one paragraph or table), and a PDF is read to 20,000 pages; past a limit the text read so far is kept, with a note.
- **Deleting** an output from the UI moves it, with its sidecar and preview, to `outputs/.trash/<YYYY-MM-DD>/` (its cached text and page images are deleted); the hub empties trash days older than 30 days. Dotfiles and dot-folders are never indexed.

### 4.8 Adding a mod
1. Run `gaifa new <id>`. It copies `services/_template/`, fills in the id, name and a free port, runs its `install.sh`, and asks the running hub to pick it up (`POST /api/services/rescan`). The mod appears in the sidebar, with an Overview tile, a working API tab and its Hello tab, and starts.
2. Edit `services/<id>/server.py` and `service.toml`, then `gaifa restart <id>` (a code change) or `gaifa rescan` (a manifest change, applied at the mod's next start).
3. A mod copied in by hand, or a folder deleted, is picked up the same way with `gaifa rescan` (or a hub restart).

## 5. Runtime

**Boot** (`app.py` → `utils/server.py:create_app`). Nothing happens at import time. The lifespan starts these in order, and stops them in reverse:
1. config
2. db
3. event bus
4. models registry (load the registry, cheap status check)
5. services:
   - find all manifests
   - adopt running `gaifa-*` units
   - autostart enabled mods in `after` order
6. outputs (watch `outputs/`, with a background rescan of what changed while the hub was down)
7. memory sampler
8. metrics recorder and rollups

**A request from the UI:**
```
browser ──► 127.0.0.1:7000
            ├─ /                     web/ (static) + /config.js (sets GAIFA_API_BASE)
            ├─ /ui/services/<id>/…   services/<id>/ui/… (page modules)
            ├─ /api/…                hub routes (services, memory, models, outputs, settings, events)
            └─ /api/s/<id>/…  ──►    127.0.0.1:<port>/…   (streamed; memory triggers run first)
```

**Processes:**
```
gaifa.service                        app.py (hub)
gaifa-relay.service                  relay (DashLLM)          :4000
gaifa-opencode.service               opencode serve           :4096
gaifa-lcpp.service                   lcppd                    :7710
  lcpp-<name>.service …              llama-server instances   :7071–7199 (owned by lcpp)
gaifa-tts.service                    LocalTTS                 :5040  (+ engine worker subprocesses)
gaifa-gen3d.service                  gen3d                    :5050  (+ podman worker container)
gaifa-comfy.service                  comfy adapter            :5070  (+ ComfyUI in the strix-halo toolbox :8199)
gaifa-stt.service                    stt (faster-whisper)     :5105  (+ its model's worker process)
gaifa-decide.service                 decide (d3-lite)         :5107  (+ its model's worker process)
```

`Ctrl+C` on `python app.py` stops only the hub; mods keep running. `gaifa stop all` stops everything.

**Service states** (`utils/services.py`): `stopped → starting → ready ⇄ degraded`, with `failed` and `stopping`.
- **starting:** health is polled every 0.5 s up to `start_timeout_s`. A mod that exits, or never gets healthy (it is then stopped), goes to `failed` with the last 20 log lines in `last_error`.
- **ready:** health every 5 s. 2 misses → `degraded`; 5 misses → stopped and `failed`; the process exiting → `failed`.
- **failed:** `restart = "on-failure"` retries after 2 / 4 / 8 s, at most 3 times in 5 minutes, then gives up. A failure raises an alert and an activity item.
- **On boot:** running `gaifa-*` units started from this root are adopted (`starting` until healthy); one whose folder is gone is stopped. Then enabled mods with autostart start in the background, each after the mods in its `after` list.
- **Settings changes while running:** a new port or env applies at the mod's next start. Until then, health checks and the proxy keep using the port the process was started with.
- **External mods** (`kind = "external"`): health only. Never reachable = `stopped`; reachable = `ready`; lost = `degraded`, then `failed`. Start and stop are refused (`external_service`).
- `python app.py --dev` runs mods as child processes instead of units; they stop with the hub.

**Who may call the hub.** There is no login; `utils/origin.py` keeps other websites out. A request whose `Host` isn't `127.0.0.1`, `localhost` or `[::1]` (any port) gets 421 `bad_host`, which stops DNS rebinding. POST, PUT, PATCH, DELETE and WebSocket handshakes that carry an `Origin` must come from the hub's own page (`http://<loopback name>:<hub port>`), and `Sec-Fetch-Site: cross-site` is refused: 403 `cross_origin`. Requests without an `Origin` (curl, the mods, MCP clients) are allowed. Proxied mod responses get `X-Content-Type-Options: nosniff`, and documents (HTML, SVG, XML, untyped) get `Content-Security-Policy: sandbox`. (Added overnight 2026-10-21: before, a website rebinding its name to 127.0.0.1 could read chats and call tools in Bypass mode.)

**Devices on your network (plan lan-access).** Off by default. With `[hub.lan] enabled`, a password (`data/state/lan/auth.json`, scrypt) and a restart, `app.py` listens on every address (`bind = "all"`) instead of loopback alone. Who a request is from is its connection's address, never a header: loopback is this machine, with the rules above and no sign-in. Anything else goes through `utils/lan/guard.py`: an address outside this machine's own network interfaces (container bridges and VPNs don't count unless `allow` names them) gets 403 `not_local`; a `Host` that isn't this machine's name, `<name>.local`, one of its network addresses or `names` gets 421; an unsafe method or WebSocket with another site's `Origin` 403 `cross_origin`; then, except for `/signin` and `POST /api/lan/signin`, a signed-in device's cookie (`gaifa_session`, HttpOnly, SameSite=Strict, a session per device in `data/state/lan/sessions.json`) or 401 `sign_in` (a page redirects to `/signin`; a WebSocket closes with 4401). What stays on this machine is refused with 403 `this_machine_only` (`utils/lan/limits.py`): `/mcp`, the `/api/lan` writes, the hub's own settings, Bypass anywhere in the agent, and a folder's level above Read or its Bypass. Mods stay on loopback (`gaifa doctor` warns otherwise) and never see the cookie (the proxy drops it). Five wrong passwords lock an address out for 30 s, doubling to 15 minutes.

## 6. Hub API

The UI-facing contract is **Section 6 of [design-brief-ui.md](design-brief-ui.md)**. These routes are backend-only additions:

| Route | Purpose |
|---|---|
| `GET /config.js` | sets `window.GAIFA_API_BASE = ""` and `window.GAIFA_LIVE_AREAS = [...]` (the areas whose backend exists), so the served UI is live area by area |
| `GET /` | `web/Hub.dc.html`, with `vendor/react*.js` and `/config.js` script tags added before `support.js` as it's served, so a fresh export works unchanged |
| `GET /ui/services/{id}/{path}`, `GET /Mod_<id>.dc.html` | a mod's `ui/` folder (page modules), and its `Page.dc.html` under a name `dc-import` can find |
| `GET /api/metrics`, `/api/metrics/series`, `/api/timeline`, `/api/outputs/stats`, `/api/activity/stats`, `/api/jobs/stats`, `/api/widgets`, `/api/widgets/{service}/{id}` | chart data; shapes in UI brief §11.7 |
| `GET /signin`, `POST /api/lan/signin {password}`, `POST /api/lan/signout`, `GET /api/lan/status`, `PUT /api/lan/settings`, `PUT /api/lan/password`, `DELETE /api/lan/sessions/{id|all}` | other devices on your network (plan lan-access, `utils/routes/lan.py`): the sign-in page and its cookie (401 `wrong_password`, 429 `locked`), this machine's view (on, the addresses to open, devices) or a device's own session, and the this-machine-only writes (`restart_required` when turning it on or off) |
| `POST /api/outputs/upload?name=` | a file sent as the body (image, video, audio, text or document, ≤ 64 MB) saved to `outputs/uploads/<date>/` and indexed; returns the `Output` (Chat's Upload, plan chat-uploads U.4) |
| `GET /api/outputs/{id}/file` | an output's main file (supports Range, for audio/video seeking); a symlink that leads out of `outputs/` is never indexed or served, here or by `/files`, `/text`, `/preview` |
| `GET /api/outputs/{id}/files/{path}` | a file inside a folder output |
| `GET /api/outputs/{id}/preview` | thumbnail or poster |
| `GET /api/outputs/{id}/text?offset=&limit=&page=&pages=&screened=` | a window of a text or document output's extracted text, with its outline, page count and scanned pages (plan 24.3; `not_text` 409, `no_page` 404); `screened=true` gives it as the chat model reads it, screened when `[agent.screen]` covers the output (the agent always sends it, so attachments sent whole and `view_output` are covered; plan 30.8) |
| `POST /api/screen {text}` | a text checked by the screening's fixed patterns only (hidden characters, chat-template tokens, encoded blobs, phrases aimed at an AI), no model, nothing kept: for skills, which are instructions to an AI by design (skill-sources 3.1) |
| `POST /api/web/read {url, text?}` | a web page read for the user (Chat's pasted links and "Add a web page", the web mod's Read a page): the web mod fetches and saves it (all its fetch rules; no card, the user asked), the hub screens all of its text (up to 400,000 characters) and keeps the report at `outputs/.text/<id>.screening.json`, which later reads reuse while the text and the screening setup are unchanged (plan 30.8, `utils/routes/webpages.py`, `utils/tools/screen_store.py`) |
| `GET /api/outputs/{id}/search?q=&limit=` | hits in that text: words in one line or paragraph, a `"phrase"`, or a `/regex/` run in a separate Python with a 1 s limit (`search_timeout`); at most 5,000 matches are counted, past that the answer has `capped: true` |
| `GET /api/outputs/{id}/page/{n}.png?width=` | page `n` of a PDF, rendered by `pypdfium2`, cached under `outputs/.previews/<id>/`; `width` at most 2400, and at most 25 MP and 10,000 px a side (a very tall page comes out narrower) |
| `GET /api/events/recent?limit=` | recent activity, current alerts and running jobs (the activity, alerts and jobs parts of `GET /api/overview`, with a larger `limit`) |
| `GET /api/services/{id}/check[?start=1]` | the mod self-test behind `gaifa check`: `{ok, checks: [{name, status: ok\|fail\|warn\|skip, ok, detail}]}` |
| `GET /api/doctor` | the checks behind `gaifa doctor` and Settings → About → Doctor (plan 12.4): models on disk, manifests, paths outside the project, the submodule mods (`repos`: each one's problems and fix, plan mod-repos 3.4) (allowlist: `/usr`, `~/.config/tts-engines`, `~/.local/bin`, podman images; Stage D items are notes), ports, units, disk, offline mods. Shape: UI brief §11.7 `Doctor` |
| `POST /api/services/rescan` | pick up added, removed and edited mod folders without restarting the hub: `{added, removed, changed}`; new mods autostart |
| `POST /api/memory/acquire[?make_room=1]` | a mod asks for memory: `{service, needs_bytes, reason}` → `200 {granted, freed[], plan}` or `409 needs_room {plan}`. `make_room=1` (or `X-GAIFA-Make-Room: 1`, or `auto_make_room`) unloads first; the grant is reserved for 120 s |
| `GET /api/tools[?q=][?names=]`, `GET /api/tools/index` | the agent's tool catalog (plan 13.1): every mod's `[tools]` and `tools_source` functions plus the hub's own `hub_*` tools, with risk, `ask` fields, examples and `core`; a stopped mod's tools stay listed (`available: false`; a call starts it) |
| `POST /api/tools/{name}/call {arguments, origin, mode}?wait=`, `GET /api/tools/calls/{id}[/result]`, `POST …/cancel` | a tool call (plan 13.2): validated (errors name the field and the fix), checked in §14.7's order (deny list → thread mode → the mod's own limits → grants → ask list → pages the chat's search found → allow list → risk default), run as a hub task (jobs followed to the end; outputs mapped to `output:<id>`; JSON capped at 8 KB). Shapes: UI brief §11.12 |
| `GET /api/approvals`, `GET/POST /api/approvals/{id} {approve, arguments?, remember?, confirm?, grant_hours?}` | approvals (plan 13.2): a call that must ask is stored in `approvals` (hub.db) and runs nothing; the decision may carry edited arguments, which are validated and are what runs; `remember: thread \| always` also writes a grant (plan 25.2, §14.7) |
| `GET /api/grants[?thread=][?tool=]`, `DELETE /api/grants/{id}`, `DELETE /api/grants?thread=` | grants (plan 25.2, §14.7): what the user allowed in a chat or always, with revoke; the agent ends a chat's grants when it deletes the chat |
| `GET /api/judge/recent[?thread=][?limit=]`, `GET /api/judge/status` | the Auto mode's judge (plan 30.3, §14.7): judged calls with their verdict and reason, newest first; whether the judge's model answers |
| `GET/POST /api/sessions`, `PUT/DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/restore?dry_run=1`, `GET /api/sessions/state` | sessions (plan Phase 15): named snapshots, the restore plan (steps and memory) and its run through the memory manager; `state` reports an unclean last shutdown |
| `GET /api/skills`, `GET /api/skills/{mod}/{name}`, `GET /api/skills/{mod}/{name}/files/{path}` | the mods' agent skills (plan 14.9); a skill lists its other files and each is read as text (skill-sources 1.2) |
| `GET/POST /api/prefs`, `PATCH/DELETE /api/prefs/{id}`, `POST /api/prefs/{id}/approve\|reject` | preferences (plan 21.2, §14.5): saved only when they fit the tool's schema and choices; applied to every caller's card |
| `GET /api/mentions?q=&kind=` | what the user can @-mention (plan 48.1): the kinds the mods declare in `[[agent.mentions]]` (a voice, a workflow, an engine), listed from each running mod (cached 30 s), each with the tool fields it fills |
| `GET /api/ui/store/{scope}`, `PATCH /api/ui/store/{scope}` | what a page remembers (settings-that-stick 4.1): a mod page's choices (scope = its id) and the hub's own view state (scope `hub`: the chat panes, folded Settings groups, sorts), in `data/state/ui/<scope>.json`; a PATCH `{set, delete}` changes only those keys (each value ≤ 16 KB, a file ≤ 256 KB: `413 payload_too_large`; an unknown mod `404`) and publishes `{type: "ui_store", scope, keys}` |
| `POST /api/notify` | a mod tells you something in the app (calendar 2.1): `{service, title?, body?, level, route?, key?, actions?: [{label, op: "POST /…" or "PATCH /…"}] (≤ 4), unread?}`; a title publishes `{type: "notification", id, ts, service, title, body, level, route, key, actions}` (a toast that stays until closed, each action called through the proxy) and adds an activity item; `unread` sets the mod's `badge` (in memory, in `ServiceSummary`; the mod posts it again when it starts) and publishes `{type: "badge", service, unread}`; an unknown mod is `422 unknown_service`. Nothing leaves the app |
| `GET /api/settings/defaults` | the `Settings` shape (brief §6.4) built from `config.example.toml` (read once per process; GAIFA's built-in defaults without it), the installed mods filling `services` and `memory.priority` as `GET /api/settings` does: the defaults the Settings page shows on each row and returns to with Reset (plan settings-redesign 4.1); this machine's `config.toml` never changes it |
| `GET /api/doctor/inventory` | every path outside the project that anything uses, with its reason (plan 16.3) |
| `GET /api/system/hardware[?refresh=true]` | what this machine has (plan 35.2, `utils/hardware/`): the OS, WSL, each GPU's vendor, arch, memory (unified or dedicated), runtimes, what it can run and its problems, and the accels usable here (`rocm`, `cuda`, `xpu`, `mps`, `vulkan`, `cpu`); read once and cached. `gaifa hardware` prints the same without the hub |
| `GET /api/repos[?refresh=1]`, `POST /api/repos/fetch[?id=]`, `POST /api/repos/{id}/update {to?, commit?, force_busy?}`, `POST /api/repos/{id}/pin` | the mods that are their own repositories (plan mod-repos 3.3, `utils/repos_watch.py`): each submodule's pin, checkout, branch, ahead/behind and problems with their fix, the `[repos]` settings and the last update; fetch asks GitHub (the only route that does); update runs in the background (`repos` events with each step; 202, then the result on `GET /api/repos`): refused with `409 repo_refused {refused: [codes]}` (changed files, unpushed commits, a split history, not checked out) or `409 repo_update_running`; it rolls back on a failed install or check and stages the pin (or commits only it after the tests, `commit`); pin stages a pushed checkout |
| `GET /api/llm/engines`, `POST /api/llm/{id}/load {id}[?make_room=1]`, `POST /api/llm/{id}/unload {id?}` | the local LLM engines (plan llm-servers 3.4, `utils/routes/llm.py`): every mod with `[llm]` (§4.3), whether it runs, its engine (`{state, loaded}`) and catalog (each model with the relay name it gets once loaded); load and unload go to that mod, its own errors passed on (`409 needs_room` with the hub's plan, a 404 for an unknown model); `409 engine_stopped` while the mod is stopped |
| `POST /mcp` | the agent's tools over MCP (plan 13.4; streamable HTTP, stateless, JSON responses; 2026-07-28 per-request `_meta` plus the 2025 `initialize` era). Annotations from `risk`; `ask` calls return `input_required` (an elicitation form of the ask fields) to clients that declare elicitation, else an explanation with `_meta["gaifa/approval"]`; the MCP-only tool `gaifa_wait_approval` waits for a decision (never approves). `GET`/`DELETE` → 405; an `Origin` other than the hub's own page, or `Sec-Fetch-Site: cross-site` → 403 (JSON-RPC error). A call's origin is `{service: "mcp", client}`: the client's name from the request's `clientInfo` (2026-07-28 era), else its user agent's first word (agent-workflows 4.2: the agent mod keeps each client's `agent_chat_*` chats by it). Claude Code: `claude mcp add --transport http gaifa http://127.0.0.1:7000/mcp` |

**Alerts** (plan 6.4) are the banner items above the Overview grid. Each has a stable id, so it is raised once and cleared when its cause goes away:

| Alert id | Level | Raised when | Cleared when |
|---|---|---|---|
| `manifest-<id>` | error | a mod's `service.toml` is invalid, or its `config.toml` override clashes (found at boot, rescan or a settings save) | the manifest is fixed and rescanned, or the folder is removed |
| `svc-<id>` | error | a mod failed (crashed, failed to start, or stopped answering its health check) | it starts again, or is stopped |
| `models-missing`, `models-partial`, `registry-invalid`, `sum-<model id>` (a checksum mismatch) | warn/error | registry problems (§8) | the registry watcher sees them fixed |
| `disk-low` | warn (error under 10 GB) | the project's disk has under 50 GB free (checked every 10 s) | 55 GB or more is free |
| `memory-high` | warn | memory is over 92% used | it drops under 90% |
| `outputs-watch` | error | the outputs watcher stopped | it recovers |
| `repos.<id>.<code>` | warn/error | a submodule mod has a problem (plan mod-repos 3.3): `not_checked_out`, `dirty`, `untracked`, `unpushed`, `pin_not_on_remote`, `checkout_behind_pin`, `diverged`, `wrong_remote`; with `[repos] notify = "all"` also `updates_available`, `checkout_ahead_of_pin`, `fetch_failed` (as warn). The text ends with the fix | the problem is gone (read again at each fetch, update, pin and `GET /api/repos?refresh=1`) |

**Error envelope:** every hub error is `{"detail": str, "code": str, "data"?: object}`, sent with an `X-GAIFA-Error: <code>` header. Responses proxied from a mod are passed through unchanged (no header), which is how the UI tells a mod's error from the hub's. The proxy adds `X-Forwarded-Prefix: /api/s/<id>` (plus `X-Forwarded-Host` / `-Proto`) to each request, and rewrites a `Location` that points at the mod so redirects stay inside `/api/s/<id>`. The hub only produces `service_not_running` (503) or `upstream_error` (502) when it can't reach the mod at all. **WebSockets** pass through the same path (plan 29.2): messages both ways until either side closes, the mod's close code included. A page from another origin is refused at the handshake (403); otherwise a missing, stopped or unreachable mod is reported as a close code the browser can read (4404, 4503, 4502). An open socket counts as a request in flight.

## 7. Memory manager

**Sampling** (every 2 s):
- **System:** `/proc/meminfo` (`MemTotal`, `MemAvailable`); where there's no `/proc` (macOS), psutil's totals, and the process reads below go through psutil too (`utils/proc_portable.py`, plan 35.3: no per-process GPU memory or engine time there).
- **GPU:** AMD sysfs `mem_info_gtt_*` / `mem_info_vram_*`.
- **Per mod:** the processes in its unit's cgroup, plus its `extra_units` and `containers`. A container's processes are its main pid plus everything in its `libpod-*` cgroup: `podman exec` processes (how a toolbox runs ComfyUI) aren't children of the main pid, and toolbox containers share the host's PID namespace. For each process, count PSS (from `smaps_rollup`, so pages shared by forked workers count once; RSS if it can't be read) plus GPU memory from DRM fdinfo (`drm-memory-gtt` / `vram`). This logic comes from lcpp's `proc.py`. The same sample reads the processes' DRM engine counters (`drm-engine-*`), and `GET /api/memory` gives each mod's `gpu_busy_pct`: its busiest engine's share of the time since the last sample. It sees Vulkan and graphics work (lcpp), not ROCm compute, which goes through `/dev/kfd` and has no per-process busy time on this kernel (plan 28.2).
- **Peaks:** each mod's observed peak is stored in `hub.db`, and used as the estimate when it's larger than the manifest's.

**Pools (plan 36.1–36.2):** where every GPU shares the system's memory (this machine, Apple Silicon, an integrated GPU), there's one pool, `system`, and everything above holds as written. Each **dedicated** GPU adds a `gpu:<index>` pool with its own VRAM budget (`utils/memory/pools.py`):
- **Reading the pools:** NVIDIA's totals and per-process use come from `nvidia-smi` (WSL2 doesn't report processes). For an AMD or Intel card, totals come from sysfs and per-process use from fdinfo's `drm-memory-vram` by `drm-pdev`; the system footprint then counts only GTT.
- **Where a mod goes:** to the GPU asked for (`device`), else where it already holds VRAM, else the freest.
- **What it needs:** its VRAM need is `max(vram_gb, its VRAM peak)`; VRAM peaks are kept in `service_peaks` as `<id>@gpu`.
- **Making room:** the planner covers the system gap first, then the GPU's, counting what the chosen mods free there. Steps that only free VRAM carry `pool`. A plan names the pool that's short (`pool`, and `pools` with each one's need and room), and `needs_room`'s detail says "needs ~X on <card>, Y free there".
- **Reservations and acquire:** reservations hold VRAM too, and `POST /api/memory/acquire` takes `vram_bytes` and `device`.
- **Where VRAM can't be read** per process (WSL2, macOS), a mod's share is what it acquired or its `vram_gb`.

The recorder keeps a `gpu.<index>.mem_used` series per dedicated GPU (plan 36.4), and the UI draws a bar per card under the system memory.

With more than one GPU, the **GPU queue keeps one slot per device** (plan 36.3): a lease is for a `device` (default: the GPU its mod was started on), nested work runs on its parent's, and `GET /api/gpu` lists the other cards' slots under `devices`.

**Load rule:**
- `available = MemAvailable − reserve`.
- `needs = max(estimate, learned peak)`, or the `needs_bytes` the mod sent to acquire. A learned peak counts for `[memory] peak_days` (7) after it was measured; an older one is ignored and the next load measures a fresh one, so a mod's worst load from weeks ago (an engine or workflow since retired) doesn't block today's smaller ones.
- If `needs ≤ available`, go ahead.
- Otherwise build a **plan**:
  - **Candidates:** loaded mods with `auto_unload = true`, not in `never_unload`, and not busy (no in-flight proxied requests and `busy = false` in status).
  - **Order:** by priority, then longest idle.
  - Add candidates until the gap is covered.
- **When it runs:**
  - With `auto_make_room = true`, or `?make_room=1` on a load call, it unloads the plan's mods one by one, waits for memory to drop (30 s timeout), then loads.
  - Otherwise it returns `409 needs_room` with the plan, and the UI shows the Make-room dialog.

**What starts a load:**
1. An explicit `POST /api/services/{id}/load`.
2. A proxied call that matches the mod's `triggers` while the mod is unloaded.
3. A mod calling `POST /api/memory/acquire` itself. lcpp (whose needs differ per model) and comfy (per workflow) use this.

**Reservations:** planning and unloading happen under one lock, which isn't held while a mod loads (that can take minutes). Instead, each grant reserves its bytes, and other plans subtract what's still reserved. A reservation shrinks as the mod's measured use grows, and ends shortly after the load finishes (or when the mod unloads, or after 30 min / 120 s for acquire / 300 s for a trigger).

**Proxy triggers:** a trigger in `[memory] triggers` is `"METHOD /path"`, where `{name}` matches one path segment and a trailing `*` matches the rest. A matching call to an unloaded mod makes room first, then goes through (the mod loads itself). Without room it returns `409 needs_room` with the plan, and the caller retries with `X-GAIFA-Make-Room: 1`.

**Known limit:** clients that call a mod's port directly (e.g. video-maker → `:5040`) bypass the hub. Their loads aren't managed unless the mod itself calls `acquire`.

### GPU queue (plan 31)

One GPU slot (`utils/gpu.py`, `[gpu] queue = true`, `lease_ttl_s = 60`). A mod with `[gpu] class = "job" | "interactive" | "background"` (and an optional `group`) takes the slot around its GPU work with `POST /api/gpu/acquire` (200 granted, 202 waiting with `ahead` and `eta_s`), renews it every 10 s and releases it (`services/_template/gpu_slot.py`). Order: interactive, then job, then background (only when nothing waits); FIFO within a class; nothing is pre-empted. A lease of the holder's group joins it unless another group's lease of the same or a higher class waits. `X-GAIFA-GPU-Lease` runs nested work under its caller (gen3d → comfy). A held lease not renewed for `lease_ttl_s` expires with the `gpu_lease_expired` alert; a mod that fails or stops frees its leases at once; after a hub restart, renewals re-register leases. Slot first, then memory. Routes: `GET /api/gpu`, `POST /api/gpu/acquire?wait=`, `POST /api/gpu/{lease}/renew`, `POST /api/gpu/{lease}/release`, `DELETE /api/gpu/{lease}` (cancel a waiting lease); `gpu` events. The relay takes a lease per request to a local engine, so a chat on a local model waits behind a job; live dictation moves to the CPU instead. Clients of an engine's own port bypass the queue. A caller with a short budget (the Auto judge, page screening) sends `X-GAIFA-Answer-Within: <s>`: the relay and the decide mod give the model that long once the slot is held (504 past it; the decide mod counts from when its model is loaded, so a load after an idle unload isn't the answer's time, plan web-approvals 1.3), and the caller waits up to 90 s for the slot itself. A proxied `[memory] trigger` of a mod with `[gpu]` that would wait gets its room check at once and its room (unloads, reservation) when its lease is granted. The agent's model timeout counts silence from the model, not the GPU wait.

## 8. Models registry

`data/models/registry.json` is written atomically and keyed by id, so git diffs stay readable:

```json
{
  "version": 1,
  "models": {
    "gemma-4-26b-it": {
      "name": "Gemma 4 26B A4B (Q4_K_M)",
      "kind": "llm",
      "format": "gguf",
      "path": "llm/Gemma4-26B",
      "files": [
        {"path": "llm/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf", "role": "model", "size_bytes": 16796015520, "sha256": null, "verified_at": null},
        {"path": "llm/Gemma4-26B/mmproj-Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf", "role": "mmproj", "size_bytes": 1194827776, "sha256": null, "verified_at": null},
        {"path": "llm/Gemma4-26B/mtp-gemma-4-26B-A4B-it.gguf", "role": "draft", "size_bytes": 251937728, "sha256": null, "verified_at": null}
      ],
      "services": ["lcpp"],
      "source": {"type": "huggingface", "repo": "<org>/<repo>", "revision": "<commit>"},
      "added": "2026-10-04T12:00:00-04:00",
      "tags": [],
      "notes": ""
    }
  }
}
```

- **Kinds:** `llm`, `tts`, `stt`, `voice`, `3d`, `image`, `video`, `text-encoder`, `vae`, `lora`, `vision`, `upscale`, `other`.
- **`status`** (`ok` / `missing` / `partial` / `unverified` / `checksum_mismatch` / `verifying`) is computed when the registry is read, not stored:
  - `missing`: none of the files exists.
  - `partial`: some file is missing, has a different size than recorded, or is still downloading (`<file>.part`).
  - `checksum_mismatch`: verify found a file whose sha256 differs from the recorded one (it stores the new hash as `actual_sha256`).
  - `ok`: every file has a recorded sha256 and hasn't been modified since its `verified_at`.
  - `unverified`: anything else (no checksum yet, or changed since verification).
  - `verifying`: queued or being hashed; the Model then carries `progress` (0–1).
- **Robustness:** the hub reloads `registry.json` when it changes on disk. An entry it can't validate is reported and saved back unchanged; a file it can't read at all makes the registry read-only (`registry_invalid`) rather than being overwritten.
- **Deleting files** removes only the recorded files inside `data/models` (a symlink's target too when it lies inside the model's own folder, as per-repo hf-cache blobs do), then any folders left empty. A whole repo in the Hugging Face cache (`hf-cache/hub/models--org--name`) is deleted through huggingface_hub's cache API instead, as `hf cache rm` does: the repo with every revision, then each shared blob in `hf-cache/hub/blobs/` once its `.refs` manifest names no other repo (huggingface_hub 2.x keeps Xet downloads there, shared across repos). The hub never removes shared blobs by hand; a repo huggingface_hub calls corrupted falls back to the recorded files. It is refused with `model_in_use` while a mod using the model is running and loading, loaded, unloading or busy; a running mod with no `[memory]` section counts as loaded.
- **Who registers models:**
  - the scanner suggests entries and you confirm them
  - mods can register what they download (`POST /api/models` with their source)
  - lcpp's Hugging Face downloader does this first
- **The model inventory follows the registry** (plan 23.6): with `[docs] regenerate = true`, every change (an add, edit, delete or verify, or a reload of `registry.json` after a hand edit) reaches the registry's listeners (`Registry.subscribe`: the alerts and `utils/registry/docs_hook.py`), which rewrites that model's doc in `data/state/setup/models/<id>.md` (local, gitignored: which models to set up is each person's choice) 2 s after the last change, off the event loop. `gaifa docs` does the same without the hub, and also writes the mods index in `docs/setup/README.md` (`utils/setupdocs/`). Setup docs live in the mods, `services/<id>/setup/*.md` (docs/mods.md §9).

## 9. `config.toml`

`config.toml` is each machine's own and not in git: on the first `gaifa` command or hub start it's copied from the tracked `config.example.toml`, which holds the defaults a fresh clone starts from (no autostarts, no judge model; plan 23.11). With neither file, the code's defaults apply.

Sizes in GB (`reserve_gb`, a manifest's `estimate_gb`, a status's `memory_estimate_gb`) are decimal: 1 GB = 10⁹ bytes, as the UI and `gaifa` show them.

```toml
# GAIFA settings. Each mod ships defaults in services/<id>/service.toml; values here override them.
# The Settings page edits this file and keeps comments.

[hub]
host = "127.0.0.1"          # loopback only; anything else is refused at startup
port = 7000
backend = "auto"            # plan 37.1: auto (systemd where there's a user manager, else detached), systemd, detached, subprocess

[hub.lan]                   # plan lan-access: other devices on your own network sign in; off by default
enabled = false             # with a password set (gaifa lan password) and a restart: the hub listens on the network too
bind = "all"                # all (0.0.0.0 and ::, so a new Wi-Fi address is followed) | one of this machine's private addresses
allow = []                  # more networks that count as yours (a VPN: "100.64.0.0/10"); private or CGNAT only
names = []                  # more host names devices may use (this machine's name and <name>.local always)
session_days = 30           # a device stays signed in this long without being used
https = "also"              # Phase 3: off | also (HTTPS on https_port: the microphone needs it) | only
https_port = 7443

[paths]                     # relative to this file; must stay inside the project
models = "data/models"
databases = "data/databases"
outputs = "outputs"

[memory]
reserve_gb = 12
auto_make_room = false      # false: ask (Make-room dialog); true: unload idle mods automatically
never_unload = ["lcpp"]     # stopping LLM instances is never automatic
priority = ["comfy", "tts", "gen3d"]   # unloaded first → last
peak_days = 7               # a learned peak older than this stops counting; the next load learns a fresh one

[ports]
new_mods = [5100, 5199]

[ui]
theme = "system"
density = "compact"         # or "comfortable"

[ui.dashboard]              # the Overview dashboard's Customize choices (written by the UI; plan overview-bento)
order = ["needs", "running", "memory-hero"]
hidden = ["activity"]       # tiles on by default, turned off
shown = ["storage"]         # tiles off by default, turned on
sizes = { memory = "f" }    # xs 3×1, s 4×2, m 4×3, w 6×3, l 8×3, f 12×2 (columns × rows); only those the tile allows
ranges = { memory = "6h" }

[ui.nav]                    # the sidebar (plan 33.2, written by the UI; only what differs from the defaults)
collapsed = true            # the thin rail
services = "counts"         # "list" (default), "button" or "counts"
hidden = ["fake-ok"]        # mods left out of the sidebar's list
folded = false              # the list folded under its header

[ui.chat]                   # the Chat page's choices (settings-that-stick 3.1, written by the UI; only what differs from the defaults)
steps = "split"             # Steps between messages: "fold" (default, one fold per turn) or "split" (at each of the agent's messages)
environment = "work"        # the environment a new chat starts in (the last one picked)

[ui.chat.list]              # the chat list's View menu
group = "date"              # "environment" (default), "date" or "none"; show ("chats", "archived", "both"), env_order, chat_order, collapsed

[ui.overview]               # the Overview (settings-that-stick 3.1)
view = "timeline"           # "dashboard" (default), "table" or "timeline"; "services" (from before) opens the dashboard
timeline_range = "7d"       # 1h, 6h, 24h (default) or 7d; services_range: a service's History charts

[services]
order = ["relay", "lcpp", "tts", "gen3d", "comfy", "opencode"]

[services.tts]
enabled = true
autostart = true
idle_unload_s = 180

[services.gen3d]
enabled = true
autostart = true
idle_unload_s = 600

[services.comfy]
enabled = true
autostart = false

[agent.judge]            # plan Phase 30: the Auto mode's judge (utils/tools/judge.py)
backend = "decide"       # always (plan web-approvals): a decision model in the decide mod, never a chat model; an old "relay" loads as these defaults
model = "d3-lite"        # a decide model id
url = "http://127.0.0.1:7000/api/s/decide"
threshold = 0.35         # every answer must clear it (judge.DECIDE_CUTOFF)
timeout_s = 3            # slower → ask

[outputs]                # plan 30.9; not on the Settings page
hidden_keep_days = 0     # hidden outputs (the web mod's saved pages) older than this go to outputs/.trash; 0 keeps them

[agent.screen]           # plan 30.6: text screened for instructions aimed at an AI before the chat model reads it
pages = true             # fetched pages (web_fetch, and hub_read_document on web outputs)
documents = false        # your uploads
transcripts = false
timeout_s = 30
window_chars = 800       # a chat model's passages per call: 800 for a small model (MiniCPM5 2B), 6000 for a large one
# backend = "decide"     # optional (plan 30.8): the screening model when it isn't the judge's; unset: [agent.judge]'s
# model = "d3-lite"      #   another backend than the judge's starts from its defaults (decide: d3-lite, the hub's /api/s/decide, 0.95)
# threshold = 0.95
# confirm = true         # ignored since plan web-approvals (it re-read with the judge's chat model; the judge is a decision model only)

[agent.workflows]        # plan agent-workflows 3.6: sub-agents (the agent mod reads them from GET /api/settings → workflows); Settings → Agent → Model
enabled = true
parallel_local = 1       # sub-agents at once on this machine's models (the relay's local group); they only queue on one GPU
parallel_remote = 3      # …on remote and cloud models
max_children = 8         # per turn of the chat that starts them
max_depth = 1            # 1: a sub-agent can't start its own
child_max_steps = 25
workflow_tokens = 400000 # per turn, every sub-agent's prompt and reply tokens; past it they are stopped
queue_wait_s = 1800      # a queued sub-agent that waited longer is dropped
min_window = 16384       # the agent tool only on models with at least this context window

[learning]               # plan 21–22: preferences on the cards, and the learner; Settings → Agent → Learning
enabled = true
nightly_at = "03:00"     # the learner's nightly run; it also runs after idle_min minutes without a chat
idle_min = 60
infer_after = 2          # an inferred preference is proposed after this many times, in as many chats
fade_days = 60           # inferred preferences unused this long fade out; stated ones never do

[speech_input]           # plan 29.4: dictation in Chat (the stt mod); Settings → Speech → Dictation, or the mic's menu
mics = ["Samson GoMic Analog Stereo", "ThinkPad USB-C Dock Audio Mono"]   # labels, most preferred first; the first present is used
language = ""            # an ISO code, or "" to detect
preset = "balanced"      # fast | balanced | accurate | best
mode = "both"            # both (click or hold) | toggle | hold
[voice_mode]             # plan voice-speech-model 3.1: what answers in Chat's voice mode; Settings → Speech → Voice mode
engine = "chat"          # chat: the chat's model through the stt and tts mods | speech: the voice mod's speech-to-speech model
answers = "agent"        # with engine = "speech", who answers. agent: your words go to the chat as a message, the chat's own
                         # model answers with its tools, apps and cards, and the speech model says it | speech: it answers itself
quant = "q4_k_m"         # the speech model's size: q4_k_m | q8_0
voice = "female"         # female | male
tools = []               # answers = "speech": tools it may call (at most 6); what would ask is refused, never a card
ask_chat = false         # answers = "speech": it may hand a hard question to the chat's own model
start_muted = false      # plan voice-mute 1.3: voice mode (either engine) starts muted; the bar's button and M unmute
talk = "open"            # plan voice-mute 2.2: open (always listening) | push (heard only while push_key or the button is held)
push_key = "Space"       # Space | Backquote | F2 | F8 | ControlRight
interrupt = "speech"     # plan voice-mute 3.2: talking over a reply. speech: a voice stops it (the voice mod decides with Silero) | off
[repos]                  # plan mod-repos 3.3: relay, lcpp, tts and gen3d are their own repositories (submodules)
fetch_every_h = 24       # how often the hub asks GitHub what's new; 0 = never
notify = "warnings"      # warnings | all (updates and unpinned commits too) | off
check_on_start = true    # read their state (local git only) when the hub starts
[docs]                   # plan 23.3/23.6; not on the Settings page
regenerate = false       # true: keep this machine's model inventory (data/state/setup/models/, local) current as the registry changes
```

**Saving** (settings-that-stick 2.1). Every write to `config.toml` goes through `config.save()` under `hub.config_lock`, one at a time (`PUT /api/settings`, `PUT /api/services/{id}/config`). A writer that loaded the settings earlier sends `base`, what each changed key held when it loaded them; `utils/settings_merge.py` merges the save with what is saved now. A list keeps what others added and drops only what this writer removed. A table (`services.enabled`, `ui.nav`) merges entry by entry. A value both sides changed differently is `409 settings_conflict` (`data: {field, current, yours}`), and nothing is written. So a command rule added from a chat survives the Settings page saving its own edit to the same list.

After each save that changed something, the hub publishes `{type: "settings", changed: [<dotted keys>]}` on `/api/events` (`settings.publish_saved`, settings-that-stick 2.3). The shell reloads `getSettings()` and passes the result to every page as a `gaifa:settings` window event. The Settings page merges it into its draft (`schema.js` `mergeReload`): a key the user hasn't touched follows it; a list or table the user edited merges both sides; a plain value changed on both sides is listed as **Changed elsewhere since you opened this page**, with Use theirs / Keep mine. A save refused with `409` is reloaded the same way.

## 10. The existing apps as mods

| Mod | From | Port | Models | Databases | Changes inside the app |
|---|---|---|---|---|---|
| `tts` | `~/Projects/LocalTTS` | 5040 | `~/models/breeze-tts-2` → `data/models/tts/`; Kokoro and Whisper → `data/models/hf-cache` (copied); voices → `data/models/voices/` | — | status route, dated outputs + sidecars, `LOCALTTS_VOICES_DIR`, `save_dir` kept under outputs |
| `gen3d` | `~/Projects/3DGenerate` | 5050 | `~/Models/3D/CubeArt/weights/*` → `data/models/3d/` | `gen3d.db` → `data/databases/` | `GEN3D_DB`, `GEN3D_OUTPUTS`, `GEN3D_WEIGHTS` (+ container mount), per-job folder column, `output.json`, status route; image to 3D (plan 17): Hunyuan3D 2.1 and SAM 3D Objects in its own worker containers (one family at a time, memory acquired per engine), TRELLIS.2 and SAM 3D Body as `comfy` packs it runs through the hub |
| `relay` | `~/Tools/DashLLM` | 4000 | — | `relay.db` (+ `-wal`, `-shm`) → `data/databases/` | status route (KPIs); cloud providers (plan llm-servers Phase 1): Anthropic and Gemini translated through their official SDKs, OpenAI's API with its rules, live model lists, `<alias>/<model>`, cloud for chats only (`RELAY_CLOUD_REQUIRES_PURPOSE`, `X-GAIFA-Purpose: chat`); its `docs/cloud.md`. OpenCode's free models read live from its `/config/providers` as `agent/<provider>/<model>` (llm-servers 6.1; the older `<provider>/<model>` ids still route); each id listed once |
| `opencode` | DashLLM's `opencode.service` | 4096 | — | — | none: a manifest-only mod |
| `lcpp` | `~/Models/LLMs` | 7710 | `models/*` → `data/models/llm/` | — (its JSON state stays in `services/lcpp/data/`) | `LCPP_MODELS_DIR`, catalog paths relative to it, downloads register in the hub, memory acquire, status route, `pidfd_open` fallback |
| `comfy` | `~/Models/ComfyUI*` + `~/.local/bin/comfyui` | 5070 (ComfyUI 8199) | `~/Models/ComfyUI/models/*` → `data/models/comfyui/` | — | new adapter mod (§11) |
| `web` | new (plan Phase 26); searches through the SearXNG on 8080 that runs outside GAIFA (`SEARXNG_URL`); `GET /v1/favicon?host=` gives a site's own icon for Chat's Sources (plan 32.1: `/favicon.ico`, else the home page's `<link rel=icon>` when robots.txt allows; the fetch rules, 8 s, 100 KB, ICO/PNG/GIF/JPEG/WebP by their bytes, never SVG; `nosniff`; cached in `data/state/web/favicons/`, hits 30 days, misses 1 day, at most 2000 files / 20 MB). Showing a reply's sources contacts each shown site for its icon at most monthly, including search results the agent didn't open | 5102 | — | — | new mod: `POST /v1/search`, `POST /v1/fetch` (pages → markdown `text` outputs, PDFs → `document` outputs, with sidecars); fetches only public http(s) addresses, checked after DNS and on every redirect, 10 MB / 20 s, `robots.txt`; tools `web_search` and `web_fetch` (risk `network`) |
| `workspace` | new (plan Phase 27): folders on this machine at a level each (Read · Edit · Run · Run + network) | 5103 | — | — (folders, checkpoints and run records in `data/state/workspace/`) | new mod: reading tools, edits in place with checkpoints and undo per turn, commands and Python in a rootless podman sandbox (`localhost/gaifa-workspace-sandbox:2`) or, asking each time, on the host; the hub's preflight `POST /v1/limits` (`[agent] limits`, §14.7) |
| `searxng` | new (plan 26.3); SearXNG itself runs in Docker outside GAIFA | 5106 | — | — | new mod: finds SearXNG (`SEARXNG_URL`, a probe of 8080 and 8888, a `searxng/*` container), publishes its URL for `web` (`GET /v1/endpoint`), watches `/healthz`, its engines (`/config`, `/stats/errors`) and a test search, and changes engines, timeouts, safe search, the default language and the JSON format: each change backs up `settings.yml` (keeping the newest 10 of its backups), writes it through the container (a checked copy renamed over it), restarts it and checks a search, rolling back when the check fails. A `settings.yml` that doesn't parse is reported in status and as `409 settings_invalid` with its line and column; changes wait until it's fixed. Its only writes outside the root are that `settings.yml` and its backups (§14.4) |
| `mcp` | new (plan mcp-client) | 5108 | — | — | new mod: GAIFA's MCP client. Other MCP servers (stdio programs or Streamable HTTP endpoints, in `data/state/mcp/servers.json`, secrets as `${NAME}` from its `.env`) give their tools to the hub through `tools_source` once the user approves them: each tool screened by the hub's fixed patterns and fingerprinted, a server whose tools change held until approved again (`tools_rev`), all `mcp = false`; one session a server, stopped when idle; results inside `<untrusted>`, pictures and sound as outputs |
| `voice` | new (plan voice-speech-model) | 5110 | — | `data/models/s2s/` | new mod: a speech-to-speech model for voice mode. It runs llama.cpp's server (its own pinned build in `runtime/llama.cpp/`) as a child process on a free loopback port with LFM3-Omni-2B (`Q4_K_M` or `Q8_0`, plus the projector), and bridges the page to its `/v1/realtime`: `WS /v1/realtime` in the mod's own small protocol (`voice/bridge.py`), turn ends found by Silero VAD on the CPU (`voice/vad.py`), your words written down by a second llama.cpp session of type `transcription`, interrupts, and a session renewed with the talk as text near the 32K context. With a `thread` it reads the agent's `/v1/threads/{tid}/voice-context` and posts each turn to `/voice-turn`, both through the hub. `POST /v1/load`, `/v1/unload` (asks `/api/memory/acquire`; idle unload 300 s), `/v1/speech` (the model's voice as WAV). One conversation at a time; it holds an interactive GPU lease while open. `voice/tools.py` (Phase 5): the tools a conversation may call, through the hub as unattended calls, and `ask_chat`. **Who answers** (`[voice_mode] answers`, or `answers` in the start message; Phase 6): with `agent`, the default for a conversation in a chat, the speech model only hears and speaks (`voice/agent_turns.py`): no conversation session is opened, your turn is written down by the transcription session and sent to the chat as a message (the agent's `/voice-ask`), the chat's own turn runs as for a typed message (its harness, tools, apps, memory, mode, cards), and each step's text is spoken as it comes (`/voice-answer?step=1` → llama.cpp's `/tts`, streamed; markdown taken out and numbers said as words, `voice/speak.py`, `voice/numbers.py`). Talking over it stops the speech, and the chat's turn too when it still runs (`/cancel`). The GPU lease is then held only while you are heard and while it speaks, so the chat's model and the apps its tools start get the GPU in between. With `speech` the speech model answers by itself, as above. **Mute** (plan voice-mute 1.1): `{type: "mute", on}` from the page drops the microphone's frames before the turn detector, so nothing heard starts a turn or interrupts; a turn being heard is dropped (`input_audio_buffer.clear` on both llama.cpp sessions) and a reply under way goes on. **Push to talk** (2.1; `talk: "push"` in the start, else `[voice_mode] talk`): the VAD decides nothing; `{type: "talk", on: true, played_ms?}` stops a reply under way and starts the turn, `on: false` sends it at once (a press under 250 ms sends nothing), and frames outside a press are dropped. **Talking over a reply** (3.2–3.3, `[voice_mode] interrupt`): the mod decides, not the page's loudness: while it speaks, the microphone's frames go through Silero (`vad.BargeDetector`: probability 0.7 for 200 ms, frames under −45 dBFS ignored; `docs/voice-eval.md` Noise) and a voice sends `{type: "interrupted"}`, which the page answers with `interrupt` and how much played. With the chat's agent answering, that only pauses: the chat's turn keeps running while what interrupted is heard, and when its transcription holds no words meant for it (nothing, filler, or one word that isn't a command), the answer goes on from the start of the sentence it stopped in (`resumed`); with words, the chat's turn is stopped (`/cancel`) and they are the next message. A press of push to talk always stops it. `interrupt = "off"`: nothing does but Stop, Mute and Esc. |

**Their own repositories** (plan mod-repos, 2026-10-26): `relay` → `brendondgr/Relay` (`main`), `lcpp` → `brendondgr/LLMs` (`master`), `tts` → `brendondgr/LocalTTS` (`main`) and `gen3d` → `brendondgr/3DGenerate` (`main`) are git submodules: their GAIFA-era history was pushed back to them as a fast-forward and each folder was adopted in place (its venv, `runtime/`, `.env` and `data/` untouched). Work on one happens in its repository (branch, commit, push), and GAIFA records the commit it was tested with (the gitlink in `services/<id>`). The old clones (`~/Tools/DashLLM`, `~/Models/LLMs`, `~/Projects/LocalTTS`, `~/Projects/3DGenerate`) no longer run.

**Moves are instant:** every source path and GAIFA are on the same btrfs subvolume (`/home`), so `mv` is a rename, not a copy. Old paths keep a symlink until everything that uses them has been updated.

## 11. Later pieces

**comfy mod:**
- **The adapter:** a small FastAPI on 5070. Its load starts ComfyUI in the strix-halo toolbox (the existing `comfyui` script, moved into the mod), and its unload calls ComfyUI's `/free`. ComfyUI writes to `outputs/comfy` via `--output-directory` and reads models from `data/models/comfyui` via `extra_model_paths.yaml`.
- **Workflow packs:** each workflow is a folder `services/comfy/workflows/<id>/`, built the way mods are. It holds the ComfyUI editor file `workflow.json`, an optional exact API graph `workflow.api.json`, and an optional `workflow.toml` that names its task, its inputs (shared names such as `prompt`, `image`, `seed`, mapped to node fields) and presets. Adding, editing or deleting the folder applies without a restart. ComfyUI's workflows folder holds a symlink per pack (the adapter keeps them, and carries saves made in ComfyUI back into the pack), so packs open in ComfyUI, and workflows saved there under a new name become drafts. Plan Phase 11 has the format.
- **Not hand-exported:** the adapter converts editor files to API graphs itself using ComfyUI's `/object_info` (cached, so packs can be checked while ComfyUI is down). It drafts the inputs by tracing the graph, and checks for missing nodes and model files. Imports also take API JSON, ComfyUI history, and PNG/WebP/MP4 files with embedded workflows.
- **Running one:** `POST /v1/run {workflow, inputs}` acquires memory, patches the graph (including dated `filename_prefix` values), queues it, reports progress from ComfyUI's websocket, and writes a sidecar per result. Cancelling interrupts ComfyUI; an interrupt only lands between steps, so if the prompt is still running 90 s later the adapter unloads ComfyUI as stuck, and the next job starts it fresh.
- **Tasks:** `tasks.toml` defines tasks such as `text-to-image` and `image-to-video`. The agent gets one tool per task (`generate_image`, …) from the mod's `GET /v1/tools`, with an optional `workflow` choice, rather than one tool per workflow.

**Agent-ready API** (Phase 13): `[tools]` sections become `/api/tools` (JSON-schema function definitions). Calls go through `/api/tools/{name}/call`, and tools marked `confirm` wait for an approval that the hub enforces. The same catalog can later be exposed as an MCP server, so Claude Code can drive GAIFA too.

**Chat, agent and save states:** §14, built last.

## 12. Risks and gotchas

- **Opened to the network, the password is all that stands between the Wi-Fi and the sandbox** (plan lan-access): a signed-in device can do almost everything this machine can. Plain HTTP shows the password and the chats to anyone who can read the network's traffic; HTTPS (`[hub.lan] https`) closes that. Bypass, folder levels, the hub's settings and the network settings stay on this machine. Any device on a private network interface counts as local, so a guest Wi-Fi shared with strangers is a reason to keep it closed.

1. **Python venvs aren't relocatable.** Recreate them (`uv venv` + install) instead of moving them. The speech engine venvs are rebuilt in `services/tts/runtime/` from pinned package lists (`services/tts/locks/`); CubeArt's venv is rebuilt inside the ROCm image in `services/gen3d/runtime/CubeArt/` (`services/gen3d/locks/cubeart.txt`).
2. **`git subtree` brings tracked files only.** Each app's ignored-but-needed state has to be copied separately, and `backend-plan.md` lists it for every app.
3. **Container bind mounts and symlinks:** a symlink inside a mount that points outside it is broken inside the container. Mount real paths, such as `data/models/3d` for gen3d.
4. **The Hugging Face cache uses a shared blob store** (`~/.cache/huggingface/hub/blobs`). Copy repos with `cp -rL` to dereference the links, and leave the originals in place for other projects. `data/models/hf-cache` uses one too, so deleting a repo there goes through huggingface_hub (§8). Keep the hub's huggingface_hub at least as new as the mods' (`pyproject.toml`: `>=2.2,<3`): an older one doesn't recognize a newer store layout and leaves its blobs on disk rather than risk deleting them.
5. **FastAPI's OpenAPI often can't tell audio or file responses apart from JSON.** Use `[api.responses]` overrides.
6. **SSE through the proxy must not be buffered:** stream raw bytes and use no gzip on `/api/s/*` or `/api/events`.
7. **Audio and video seeking need HTTP Range** on output files.
8. **Clients that call a mod's port directly bypass memory management** (§7).
9. **`git clean -x` would delete the models** (§3).
10. **Some UIs use absolute paths:** mods' own UIs keep working on their own ports and are linked as "native UI". GAIFA's UI never loads them inside its own pages.
11. **The UI runtime is Claude Design's generated `support.js` (React 18).** Don't edit it. Any change a new export needs goes in `web/PATCHES.md`, and the brief asks Claude Design to fold those changes in on its next pass.
12. **Metric storage grows over time.** Rollups and retention (§13) keep `hub.db` small: roughly 30 series × 10 s for 48 h is about 0.5 M rows, pruned hourly.
13. **Workspace folders are written in place** (plan Phase 27). Only folders at Edit or above, never the GAIFA folder or `data/models/`, and never through a symlink out of the folder (`services/workspace/folders.py`).
14. **Four mods are submodules** (plan mod-repos): `relay`, `lcpp`, `tts` and `gen3d` commit to their own repositories and GAIFA pins a commit of each. A clone or a GAIFA worktree has them empty until `git submodule update --init` (and never their venvs or runtimes); a change to one is two commits (the mod's, then GAIFA's pin); `git submodule update` over changed files loses them. `gaifa repos` and the `repos.*` alerts say which state each is in and the fix; the workflow is [mods.md §10](mods.md#10-mods-with-their-own-repository).

## 13. Metrics and charts

**What gets recorded** (`utils/metrics.py`, in `hub.db`):

| Series | Source | How often |
|---|---|---|
| `mem.total`, `mem.used`, `mem.available`, `mem.reserve`, `mem.other`, `gpu.gtt_used` (and `gpu.vram_used` on GPUs with VRAM) | memory sampler (§7) | 10 s |
| `mem.svc.<id>` | memory sampler, per mod | 10 s |
| `jobs.running` | status polls | 10 s (the current count, so it is held between changes) |
| `svc.<id>.stat.<slug>` | numeric `stats` from each ready mod's latest status (§4.6) | 10 s |

**As built (plan 6.1, `utils/metrics/`):** the recorder ticks on a 10 s grid and reads the memory sampler's latest snapshot and each mod's latest status, so every series has one sample per 10 s bucket. A `"reset": "daily"` counter that drops on a new local day records one `null` for that tick, so charts break the line instead of drawing the reset as a drop. Each series is named once in a `series` table (label, unit, service, `reset`), which `GET /api/metrics/series` lists. A heartbeat in `kv` notes the last tick: rows still open when the hub stops are closed at its stop (or, after a crash, at the last heartbeat) and reopen when it starts again, so downtime is a gap in both the series and the timeline. A job its mod still reports after a hub restart continues its row.

It also records **events** that charts need besides numbers:
- `service_states` (every state change, for timelines and uptime)
- `load_intervals` (loaded to unloaded)
- `job_history` (start, end, final state, service, label, from `job` events)
- `tools.calls.<mod>` and `tools.errors.<mod>`: finished tool calls per 10 s, from `tool_call` events (plan 21.1; dry runs don't count)

Outputs and activity statistics are queried straight from their own tables.

**Storage:**

| Table | Holds | Kept for |
|---|---|---|
| `metrics_raw (sid, ts, value)` | 10 s samples | 48 h |
| `metrics_1m` | rollups: avg, min, max, sample count `n` | 14 d |
| `metrics_1h` | rollups: avg (weighted by `n`), min, max, `n` | 400 d |
| `service_states`, `load_intervals`, `job_history` | events for timelines and job stats | 400 d after they end |
| `tool_calls`, `approvals`, `tool_refusals` (plan 21.1) | every tool attempt: arguments, what the hub filled, what the user edited, duration, result | real ones always; dry-run rows (the eval) 30 d |

An hourly task (and one at startup) rolls up finished minutes and hours and prunes. Watermarks in `kv` mark what is rolled up, so a rollup never counts a sample twice, and a query reads rolled-up history from the coarse table and the rest from the finer ones. `GET /api/metrics` chooses the table from the range:
- **≤ 6 h:** raw samples
- **≤ 7 d:** 1-minute rollups
- **longer:** 1-hour rollups

The results are always on an evenly spaced `t` axis, with `null` for gaps. A hub that was down shows as a gap, never as a line drawn across the missing time.

**Widgets from mods:**
- `GET /api/widgets` lists every `[[ui.widgets]]` from running mods.
- `GET /api/widgets/{service}/{id}?range=` calls the widget's `source` through the proxy and caches the result for 30 s.
- The relay mod is the first to use this, with an LLM traffic widget (backend-plan Phase 9).

## 14. Stage D: chat, agent and save states (built last)

These are built after everything else works (backend-plan Phases 14–16). They come together because the chat interface is where they're needed.

### 14.1 The agent is a mod: `services/agent/`
It works the way Claude Code does, scaled to a local model. The reasons and sources are in [agent-architecture.md](agent-architecture.md).
- **One loop, no framework.** Call the model, run its tool calls, append the results, and repeat until a reply has no tool calls. It stops at a step cap (25) and says so instead of inventing an answer, which was one of Mango-Tree's bugs. A call repeated with the same arguments is refused from the third time; after the second refusal in a turn, the next model call gets `tool_choice: "none"` and a note asking for a plain answer, so a stuck turn ends in words instead of running to the cap. Dependencies: FastAPI, uvicorn, httpx.
- **Model.** Through the relay (`http://127.0.0.1:4000/v1`), so every call shows in its stats. The default is `skynet` (Gemma 4 31B on the GPU box, 131,072 tokens), with the local Gemma 4 26B as the fallback.
  - No `max_tokens`: thinking and output may use the whole window. A reply that degenerates into one span repeated over and over (≥ 10 × 300 characters) is cut off and asked once more; a second runaway ends the turn with an honest note.
  - Thinking (`reasoning` / `reasoning_content`) is stored and shown on request, and never re-sent to the model.
  - Tool calls leaked into the text are re-parsed: Gemma's tags (also its `<call:…</call>` variant), Hermes', a known tool's name used as a tag (`<ask_user>{…}</ask_user>`), JSON objects, and a reply that is nothing but Python-style calls of known tools with literal arguments (parsed with `ast`, never run).
- **Tools.**
  - **Source:** the hub's catalog (`GET /api/tools`, Phase 13), called through `POST /api/tools/{name}/call`.
  - **Local tools:** `ask_user`, `update_todos`, `find_tools`, `load_tools`, `read_skill`, `view_output`, `read_result`, `remember`; a project chat's `project_search`, `project_read`, `project_refresh_page` (plan projects 3.4).
  - **Tool groups** (mcp-client 4.1): a group is a mod, or a group a mod's `tools_source` row names (`group`, `<mod>:<name>`; the `mcp` mod gives each MCP server `mcp:<server>`). `pinned`, `disabled` and the composer's Auto / Pinned / Off work per group. An MCP server's group is hidden (not in the tool index, not loaded, found by `find_tools` only when the query names the server) until it's on in the chat (`settings.mcp_on`): reading a skill whose `metadata.mcp-servers` names it loads its tools, `@mcp:<server>` pins it, and the composer can pin it.
  - **Reading (plan 24.4):** the hub's `hub_read_document(ref, offset?, pages?, limit?)` and `hub_search_document(ref, query, limit?)` (risk `read`, `core`, in `utils/tools/doc_tools.py`) read a text or document output's extracted text a window at a time or find words in it. They answer text, not JSON: the hub's own lines (sizes, "next: offset N", scanned pages) outside, the document's words inside `<untrusted source="…">`; their results are kept whole up to 64 KB (other tools' are cut at 8 KB). The agent turns a `ref` of `#n` into `output:<id>` before calling, and shows a text result as text. `view_output(ref, page)` sends a PDF page to a vision model as an image (its text to a model without vision); on a text output it gives the first 2,000 characters and points to `hub_read_document`.
  - **Loading:** only the `core` tools are loaded. The rest are listed by group (name and one line), and their schemas are loaded on demand.
  - **Capabilities (plan 20):** engines and workflows say what they take in their schemas (`x-options`: `needs`, `excludes`, `default`, `allows`; brief §11.12). The hub fills the default that fits the inputs, refuses a choice that doesn't with a `fix` naming the ones that do, and serves the model a copy with the choices written into the descriptions (`GET /api/tools?view=model`), so the prompt makes no capability claims of its own.
- **Asking.** Choices are a fixed step rather than the model's judgement:
  - `ask_user` puts question cards in the thread
  - every `generate`/`write` call becomes a parameter card (a hub approval whose `ask` fields you can edit) unless the thread is in "Use defaults"; `network`, `execute` and `destructive` calls ask in every mode unless a grant covers them (§14.7)
  - buttons on result cards and quick actions append a tool call directly, so clicking and typing end up in the same thread
- **Chaining.** Each result gets a reference (`#1`, `#2`…) listed in the prompt, and file inputs take `output:<id>`. Image → 3D, image → video and "describe this, then speak it" are ordinary tool calls. `view_output` shows an image to a vision-capable model.
- **Context.**
  - **The meter:** the window comes from the relay's model facts and the use from each response's `usage`. Both show in the thread header with a breakdown.
  - **Model facts** (plan 13.3): each `/v1/models` entry carries `meta: {context_length, tools, vision, reasoning, source}`, read from llama.cpp's `/props`, vLLM's `max_model_len`, or a one-time probe through another relay; a per-endpoint `facts_override` wins. `null` means unknown.
  - **Models by server (plan llm-servers 2, 5):** the agent's `/v1/models` gives each model its server, group (`local`, `remote`, `cloud`), provider, health and `cloud`, one row per id, OpenCode's agent models left out; a chat's model must be one the relay serves (`400` naming the near ones). The Chat page's model menu adds the local engines' models that aren't loaded (`/api/llm/engines`) and loads one on request. Chat turns, their title and their compaction send `X-GAIFA-Thread` and `X-GAIFA-Purpose: chat`; the judge, screening and other background callers don't, so the relay refuses them a cloud model (`403 cloud_not_allowed`). A cloud reply's `reasoning_details` (Claude's thinking with its signatures, Gemini's thought signatures) are kept per step and sent back unchanged to the same model only.
  - **Tool results:** capped in the history; the full result can be read back with `read_result`.
  - **Compaction:** at 70% old tool results are cleared, and at 85% older turns are summarized.
  - **Quote-replies (plan 32.2, Select → Reply):** `POST /v1/threads/{id}/messages` takes `quotes: [{text, reply, seq?}]`: any number, each quote 1–8,000 characters and not blank, each reply 0–4,000, at most 200,000 characters in all; `seq` must name an `assistant` event in the thread; the text may be empty when a reply says something (422 `invalid_quote` / `empty_message` otherwise). The older `quote: {text, seq?}` is still accepted and stored as one quote-reply with an empty reply; events that hold it are read the same way. The model gets each one first, in order: "About this part of your earlier answer:", the part as a blockquote (every line starts with `>`, `</untrusted` broken up, then defused like all user text), then "My reply: …"; the message's text follows, then attachments and documents. Replies are the user's words (the Auto judge's `said`, `named_files`, the learner, the chat title); quoted parts are the model's and count for none of these. Compaction and branches keep them (a branch keeps the same seqs).
  - **Attachments (plan 24.5):** at `send`, each attached text or document is described once (`GET /api/outputs/{id}` and `/text`) into the user event's `docs` (`#n`, name, kind, subtype, tokens, pages or lines, the first 30 headings, `inline`, and the text itself when inline), so a rebuild never refetches. Attached documents are numbered with the outputs. How much goes in whole is the user's (plan 24.9, `agent/docs.py`): **Settings → Agent → Documents** sets *Whole documents up to* (default `AGENT_INLINE_TOKENS`, 6000 tokens, or "the model's window") and a *reply reserve* (default `AGENT_REPLY_RESERVE`, 4096), kept in `data/agent/documents.json`. The room is the window less the reserve and what the chat already holds (the meter); documents attached together share it. Each attachment is `auto` (whole up to the setting and the room), `whole` (whole if it fits the room; otherwise the user event's `fallback` says how much didn't fit, shown on the user's message and as a note, and it goes as a card) or `card`, from the chip's Whole / Card (`doc_modes` on `POST /v1/threads/{id}/messages`), else the chat's `settings.doc_mode`, which the last chip choice sets. A whole document goes into the message inside `<untrusted source="#n name">` (fetched in 48,000-character windows); a card is (size, outline, "read it with hub_read_document or hub_search_document"). A card for a document over 50 pages also says "too large to read whole: search it by meaning with embed_library_search (thread_only=true)" when that tool is in the catalog (plan 28.3). Pictures attach as before (`(attached: output:<id>)`). The meter has a "Documents" part. Clearing drops an inline document's text once it is older than the last two user turns, leaving its card.
  - **Speech out (plan 49.1):** `config.toml [speech_output]` (Settings → Speech → Voice): the voice that reads replies aloud, its engine and speed, `auto_read`, and voice mode's `pause_ms`. The page reads a reply through the tts mod's `POST /v1/speech` with `stream` (raw PCM as it's made, not saved). Voice mode (plan 49.2) is the page alone: the stt mod's live stream to listen, `pause_ms` of quiet to send, the same streaming speech to answer. With `[voice_mode] engine = "speech"` (plan voice-speech-model) the page talks to the `voice` mod instead (`WS /api/s/voice/v1/realtime`): its speech-to-speech model answers by itself, whatever model the chat uses, and the mod writes each turn into the chat through the agent's `POST /v1/threads/{tid}/voice-turn` (a `user` and an `assistant` event with `via: "voice"`, no model call; `409 turn_running` during the chat's own turn) after reading `GET /v1/threads/{tid}/voice-context` (the profile, *Your calendar*, a short project, the last turns as text) when the session starts. The page falls back to the chat-model loop when the mod can't run. **Tools (Phase 5, off by default):** `[voice_mode] tools` names at most six; the mod reads them per conversation (`GET /api/settings`, each tool's schema from `GET /api/tools?names=&view=model`) and runs a call as `POST /api/tools/{name}/call` with origin `{service: "voice", thread, unattended: true}` and mode `manual`, so what the chat's permissions allow runs and what would ask is refused (`unattended`), never a card; the model is told why and says so. `time_now` is the mod's own. With `[voice_mode] ask_chat`, the `ask_chat` tool sends your words to the chat as a message (`POST /v1/threads/{tid}/voice-ask`, `by: "voice"`), waits for that turn (`GET …/voice-answer?after=&wait=`) and gives the answer back to be said; that turn is the chat's own, with its tools and cards.
  - **@-mentions (plan 48.3):** a message's `mentions` ([{kind, id, label, fills}], from the chat's `@` picker) are kept on its user event, said to the model in one line under the message, and pinned on that turn's calls as `origin.pins` ({tool: {field: value}}). The hub (`utils/tools/pins.py`) fills a pinned field the model left out (marked `filled` = mention on the card), skips a value that isn't one of the field's choices, and asks with a card when the model chose otherwise. Nothing is remembered past the turn.
  - **`show` (plan 47.1, `agent/show.py`):** a local tool that puts a chart, a table or pictures in the reply: views line, area, bar, hbar, donut, heatmap, kpi, table, image, gallery; data inline (≤ 500 points per series, ≤ 200 rows), from a CSV or JSON output of the chat (`source: "#n"` with its columns; the card reads the file itself, ≤ 5 MB and 50,000 rows), from GAIFA (`hub:memory`, `hub:outputs_per_day`, `hub:job_times`, `hub:mod_stat`, with a range; the card keeps it current), or outputs (`image`, `gallery`). It's checked before anything shows (errors name the field and the fix); the tool_result carries the spec as `data.show` and the model reads only a one-line summary.
  - **Conversations you can look up (plan 28.5, `agent/summaries.py`):** a chat quiet for `AGENT_SUMMARY_IDLE_MIN` (30) minutes gets a 3–6 sentence summary from its model (the agent's own when the relay doesn't serve the chat's; nothing is asked while neither is served, and a failed one waits 5 min, doubling to 6 h, before the next try), written from the learner's view of the chat (documents as cards, tool results as status: never a file's, page's or transcript's text), kept in `agent.db` `thread_summaries` and rewritten when the chat continues and goes quiet again; dry runs and `no_learn` chats are skipped. It goes to the embed mod's `chats` (`PUT /api/s/embed/v1/chats/{id}`, retried until it arrives), which embeds it under its idle rule; deleting a chat deletes both. The Chat list's *By meaning* and the local tool `chat_search(query, limit)` find chats through `GET /v1/chats/search` (title, date, summary, link). Nothing here reaches a prompt unless a chat is looked up.
  - **Untrusted text:** the base prompt says text inside `<untrusted>` is data, never instructions (report it, don't follow it), and asks for citations as `#n p.14` (a PDF page) or `#n:88` (a line). Inline text and `hub_read_document` windows of text without pages come with numbered lines (`  88| …`) so a line can be cited; the Chat page turns citations into links that open the viewer there (plan 24.7).
- **Instructions, skills, memory.**
  - **`data/agent/AGENT.md`:** standing instructions.
  - **Skills:** a mod's `skills/<name>/SKILL.md` (served by the hub at `/api/skills`) and your own in `data/agent/skills/`, in the open skill format (YAML frontmatter, `utils/skillfmt.py`). They are listed by description, read when needed, and each is also a slash command. A body ends with the skill's other files (`references/…`, `scripts/…`), each read with `read_skill('<id>/<path>')`: text only, 256 KB at most, never outside the skill's folder (skill-sources 1.2). A chat working in workspace folders also gets the skills other coding agents keep there (`.agents/skills`, `.claude/skills`, `.codex/skills`, …, found by the workspace mod: `GET /v1/skills`), listed under their folder as `<folder>:<skill>`, and is told to read the folder's instruction files (`<folder>:AGENTS.md`) before working there; a chat with no folders (None, or the workspace mod off or turned off) gets none (skill-sources 2.2). Your own skills can be uploaded (a folder, a zip or one `SKILL.md`) or copied from a workspace folder in Settings → Agent → Skills (`POST /v1/skills`, `POST /v1/skills/copy`); each is checked by `POST /api/screen`, and one with findings, or one the hub couldn't check, is saved turned off until you turn it on; deleting moves it to `data/agent/skills/.trash/` (skill-sources 3.1).
  - **Memory:** `data/agent/memory/` holds an index plus topic files, written with `remember`.
- **Projects (plan projects, `agent/projects/`, `api_projects.py`):** a project gathers chats around standing instructions, files, web pages, folders, defaults and its own memory; projects and their sources are in `agent.db` (`projects`, `project_sources`; ids `p_…`, `src_…`, at most 200 sources).
  - **Routes:** `GET/POST /v1/projects` (`?q=`, `?sort=activity|name|created`, pinned first), `GET/PATCH/DELETE /v1/projects/{id}` (GET carries its `sources`), `GET /v1/projects/{id}/threads` (the `/v1/threads` query); `GET /v1/threads?project=<ids>` (`none`: chats in no project) and `GET /v1/threads/groups?by=project`.
  - **Chats:** a chat is in a project through `settings.project`. `POST /v1/threads` with it takes the project's defaults (model, mode, `disabled`, `pinned`, `mcp_on`) and its primary environment (the first in its list) as `settings.environment`, under what the request sets itself; `PATCH /v1/threads/{id}` with it moves a chat in (the environment changes, not the model or mode) or out (`null`: the environment stays). When a project's primary environment changes, its chats follow. A project chat's workspace calls (tool calls, the folders and skills in its prompt, `read_skill`) carry `environments`: the project's, then its hidden one (`projects/origin.py`, §14.7); the prompt's folders note names the project and each environment.
  - **Its own folders (2.3):** `GET/POST /v1/projects/{id}/folders`, `PATCH/DELETE /v1/projects/{id}/folders/{fid}`: kept in a hidden workspace environment (`proj-<hex>`, "<project> (project)", `project: <id>`) made with the first folder; the workspace mod's rules apply unchanged (Read to start, the GAIFA folder and `data/models/` at Read, secrets refused).
  - **Files and pages (3.1, `projects/sources.py`):** `POST /v1/projects/{id}/sources` `{kind: "file", output_id}` (a text or document output; the output stays when it is taken out) or `{kind: "page", url, max_age_s?}` (default 3,600 s; null: never fetched again on its own), `PATCH …/sources/{sid}` (title, `max_age_s`, position), `DELETE …/sources/{sid}`, `POST …/sources/{sid}/refresh`. A page is fetched through the hub's `POST /api/web/read` (no card: the user linked it; screened whole), in the background when added; each fetch is a new output and the source keeps the newest, and a failed fetch keeps the last copy with `error`. Text is read through `/api/outputs/{id}/text` (screened), kept in memory per output. `{type: "project_source", id, source}` events show fetching, ok and error.
  - **Its collection (3.2, `projects/index.py`):** each source's text in chunks of ~3,000 characters (300 of overlap, ending at a line break, with its page and first line) kept in `agent.db` (`project_chunks`) and sent to the embed mod's text collection `proj-<hex>` as `<sid>#<n>`, in a background task after a source is added or fetched; search asks the embed mod and falls back to BM25 over the kept chunks when it is off or hasn't embedded them. Taking a source out forgets its chunks.
  - **In the prompt (3.3, `projects/knowledge.py`):** a project chat's system prompt has a *Project* part after AGENT.md (the name, description and instructions) and *Project files and pages* after Skills: every source whole, each inside `<untrusted>` with its lines numbered, its kind, URL and, for a page, how old its copy is (and the last fetch's error), while all of them fit `project_share` of the model's window (default 0.25, Settings → Agent → Documents, `data/agent/documents.json`); past that, one line per source and how to search and read them. The meter counts both as *Project*. The prompt and model-call side of the loop is `agent/prompting.py` (split from `loop.py`).
  - **Skills that are always on (4.1):** the bodies of a project's `defaults.skills` (the agent's own, or a workspace skill read through the chat's folders) go before the Skills list in its chats, up to 8,000 characters; the rest are named first in the list ("This project uses").
  - **Project memory (4.2, `projects/memory.py`):** making a project makes (or adopts, by name) a `project` entity anchored `{kind: "project", value: <id>}`; renaming the project renames it (the old name an alias). It and what is under it are kept to the project's own chats: in them its facts lead the profile (up to 1,500 characters), elsewhere it is left off the "Projects:" line and out of recall. The learner is told when a chat is in a project, so facts about the work go under it (the rules for saving without asking are unchanged). `GET /v1/projects/{id}/memory` lists its facts; deleting the project removes the anchor and keeps the entity and its facts.
  - **Tools (3.4, `projects/tools.py`):** a project chat also has the local tools `project_search {query, k?}` (passages with `src_…` and line), `project_read {source, offset?, limit?}` (a window with numbered lines, cited `src_…:line`) and `project_refresh_page {source}` (a page fetched again now; no card); never in a plain chat, never at `/mcp`. Their results start with how to cite them and carry the text inside `<untrusted>`; a chat that used them counts as having read untrusted text.
  - **Pages fetched again when a question needs them (3.5, `projects/fresh.py`):** before each answer in a project chat, the message is matched with the project's pages (page chunks by meaning, score ≥ 0.6, or by words without the embed mod; or the page's title or URL words in the message; at most 3). Matched pages older than their `max_age_s` are fetched again in parallel and re-indexed, and a `project_refresh {for, pages: [{sid, title, ok, error?, slow?}]}` event is written; the first model call waits for it beside recall, and a page still fetching after 8 s is read as its last copy (the prompt says so). Never on a schedule. The Chat page draws the event as a step ("Refreshed 2 pages").
  - **Delete:** its chats become ordinary chats (their order unchanged); the project, its instructions and its sources go, then its collection, its hidden environment and its memory entity's anchor (each step is skipped and logged when its mod is off).
  - **Events:** every change is `{type: "project", id, project}` (`project` null once deleted), sent to the `/v1/streams` connections opened with `watch=projects` (`watch` takes a comma list, and every watcher hears all of `project`, `project_source`, `task`, `task_run` and `agent_child`; the Chat page opens one, `watch=projects,tasks,workflows`, for all its listeners).
- **Scheduled tasks (plan scheduled-tasks, `agent/tasks/`, `api_tasks.py`):** a task starts a chat on its own, on a schedule, alone or attached to a project; tasks, their runs and their notes are in `agent.db` (`tasks`, `task_runs`, `task_notes`; ids `k_…`, `r_…`, `n_…`; the store is `agent.scheduled`, since `agent.tasks` holds the running turns).
  - **Schedules (1.1, `tasks/when.py`):** `{kind: "hourly", every, minute, from?, to?, weekdays?}`, `{kind: "daily" | "weekdays", time}`, `{kind: "weekly", day (Monday 0), time}`, `{kind: "monthly", day, time}` (a shorter month: its last day), in local time; a time a DST change skips moves to the next valid minute, a repeated hour runs once. `next_due` is recomputed from now when the schedule changes or the task is turned on, and cleared when it's turned off. *Calendar 6.1–6.2:* `{kind: "once", at: "YYYY-MM-DDTHH:MM"}` runs once and turns the task off (missed, it runs late); `{kind: "event", item, before_min, title?}` runs N minutes before each occurrence of a calendar item: the scheduler asks the calendar mod (`GET /api/s/calendar/v1/items/{id}/next`, `tasks/event_due.py`, kept 60 s) for the first occurrence that hasn't ended and has no run (runs record `occurrence`), so a moved occurrence follows and one missed runs late while its event is on; an item that's gone turns the task off and the check on save says `event_gone`; the calendar down leaves it waiting. `GET /v1/history?from=&to=` (calendar 8.1, `api_history.py`) lists per day the chats with a message of yours (first and last event, turns, a task's runs flagged). `GET /v1/tasks/calendar?from=&to=` (calendar 6.4, `tasks/layer.py`) answers each task's due times in a range (event tasks have none of their own) and its runs there, for the Calendar's layer.
  - **Routes (1.3):** `GET/POST /v1/tasks` (`?q=`, `?project=<id>|none`; on first, then by the next run), `GET/PATCH/DELETE /v1/tasks/{id}` (with its `last_run`, `unread` and the schedule in words, `when`), `GET /v1/tasks/{id}/runs`, `PATCH …/runs/{rid}` `{seen}`, `GET /v1/tasks/unread`, `GET/POST /v1/tasks/{id}/notes`, `PATCH/DELETE …/notes/{nid}` (at most 20, 500 characters each), `GET/POST /v1/tasks/{id}/folders`, `PATCH/DELETE …/folders/{fid}` (a hidden workspace environment `task-<hex>`, "<task> (scheduled)", `project: <task id>`, made with the first folder, as a project's); `GET /v1/threads?task=<ids>` (`none`: chats no task started). A task's mode is Plan, Accept edits, Auto or Bypass (Manual would ask every time).
  - **Runs (2.2, `tasks/runner.py`):** a run is a new chat titled "<task> · <Mon 10 Nov 07:00>" in the task's model (else the project's default, else the agent's) and mode, with `settings` `{task, task_run, unattended, no_learn, use_profile, use_project_memory, task_env?, task_only?}` and the task's tool groups (a project task's take the project's defaults under its own; its pre-allowed MCP servers are on). Its pre-allows become the chat's grants (`POST /api/grants`: each tool glob; each site as `web_fetch` per host or every site; each MCP server as `mcp_<server>_*`; one the hub refuses is noted and the run goes on). In Auto it asks `GET /api/judge/status` first; when the judge doesn't answer, a note says only pre-allowed and rule-allowed calls will run, and the run's `judge` records it. The first message is the instructions, a user event with `by: "schedule"`; its calls carry `origin.unattended` (§14.7). The run ends with the chat's first turn (`on_turn_end`): `done`, or `failed` (an error, or waiting on a card), with `refused` counted and `seen: false`; after that the chat is an ordinary chat. At most 2 runs at once (`AGENT_TASKS_PARALLEL`; test runs don't count), the rest `queued`, and one queued over an hour (`AGENT_TASKS_MAX_WAIT_S`) is `skipped` (busy); a task whose run is still going skips the next. A test run (`POST /v1/tasks/{id}/test`) isn't unattended: its calls get cards as usual.
  - **Folders:** a run's workspace calls carry the task's hidden environment (`projects/origin.chat_envs`): only it for a standalone task with folders (`task_only`) or a project task kept to them (`only_own`), else after the project's; a standalone task without folders works in Default.
  - **The scheduler (2.3, `tasks/schedule.py`):** every 30 s, each task whose `next_due` passed starts a run and moves to its next time after now; one due more than 2 minutes ago (GAIFA was off) runs once for the latest due time with `late` = how many passed. Each check also drains the queue, and once a day run chats older than the task's `keep_days` are archived. `POST /v1/tasks/{id}/run` is Run now.
  - **In the prompt (2.4, `tasks/notes.py`):** a *Scheduled task* part after *Project*: the task, whether anyone is watching (refused calls worked around and reported, `ask_user` answered at once with `unattended`, a closing summary), and its notes. The task's `skills` are always on, as a project's are. `task_note {action: add | replace | remove, id?, text?}` is a local tool in its runs only: notes on how to do the task (at most 20 × 500 characters), read by later runs. `use_profile: false` leaves the user's facts and the projects line out of the profile and recall; `use_project_memory: false` the project's own memory. Runs carry `no_learn`, so the memory learner and the preference miner skip them.
  - **The check (3.1, `tasks/check.py`):** `POST /v1/tasks/{id}/check` → `{problems: [{field, detail, fix}], warnings: [{field, detail}]}`. Problems: empty instructions or ones the hub's patterns flag (`POST /api/screen`: a run reads them as your words), a model the relay doesn't serve, a skill that isn't there (the agent's own or in the run's folders), a pre-allowed tool glob that matches nothing, an MCP server with no tools in the catalog, a folder of its own that doesn't exist. Warnings: Bypass, pre-allowed `execute`/`destructive` tools, a capped folder, what couldn't be checked. A new task with problems is saved turned off (its answer carries `check`); a task that's on and changes something the check reads, turning one on, and Run now answer `409 task_problems` (`data`: the problems, warnings and the task, saved and turned off). A test run isn't checked.
  - **Pre-allows from a test run (3.2, `tasks/allows.py`):** `GET /v1/tasks/{id}/runs/{rid}/allows` lists the run's approved cards as suggestions (a site for a `web_fetch`, a server for an MCP tool, else the tool; what the task allows is left out), and `POST /v1/tasks/{id}/allow {tools?, sites?, mcp?}` adds them (checked as a change).
  - **The judgement log (3.3, `tasks/log.py`):** `GET /v1/tasks/{id}/runs/{rid}/log` → per tool call of the run's chat, in order, `{seq, tool, summary, outcome: allowed | refused | denied | asked | pending, by: pre-allow | always | rules | judge | mode | you | local, reason}`, from the chat's events (each result's `judge` and `grant_id`, a card's decision); a grant that isn't the chat's own (`GET /api/grants?thread=`) is one of your `always` grants.
  - **Delete:** its run chats become ordinary chats, its hidden environment goes, then the task, its runs and notes. Deleting a project detaches its tasks: they stand alone, turned off.
  - **Events:** every change is `{type: "task", id, task}` (null once deleted) and a run's `{type: "task_run", id, task_id, run}`, sent to the `/v1/streams` connections opened with `watch=tasks` (or `watch=projects`).
- **Agent workflows (plan agent-workflows, `agent/workflows/`, `api_workflows.py`):** a chat spawns sub-agents, each a chat of its own linked to it; a parent with its sub-agents is a workflow.
  - **Sub-agents in the store (1.1):** a sub-agent is a thread with `parent_id` and `settings.spawn` `{root, parent, label, by: agent | mcp, tool_call_id, write, depth, seen}` (a fork has `parent_id` and no `spawn`; forking a sub-agent makes an ordinary chat). Every thread carries `children` (its sub-agents' count) and a sub-agent its `spawn`. `GET /v1/threads`, `/count` and `/groups` leave sub-agents out unless `?children=true` (a search `q` finds them, with their `spawn.parent`); `GET /v1/threads/{id}/tree` → `{root, children: [{id, title, label, parent, state, model, mode, write, depth, by, seen, archived, created, updated, children}]}` for the workflow the chat is in. Archiving or unarchiving a root does the same to its sub-agents; deleting a chat deletes its sub-agents first (each stopped, its grants ended, its summary forgotten; the answer lists them as `children`). A sub-agent left `running` resumes at startup like any chat.
  - **The runner (1.2, `workflows/runner.py`, `workflows/settings.py`):** `Workflows.spawn(parent, prompt, label, model?, write?)` makes a sub-agent titled by its label, in the parent's model (or the one named) and mode, with the parent's `project`, `environment`, `task_env`, `task_only`, `disabled`, `pinned`, `mcp_on`, `unattended`, `use_profile`, `use_project_memory`, `dry_run` and `window` (never `task` or `task_run`), plus `no_learn`, its own `max_steps` (the loop's step limit per chat) and `spawn` (with the parent's `turn`, the seq of its last user message); a note says whose sub-agent it is and the prompt is its first message (`by: "parent"`), state `queued`. Limits are `[agent.workflows]` from the hub's settings (`workflows`, read at most every 30 s): `enabled`, `parallel_local` (1: sub-agents at once on the relay's `local` models, or one it doesn't list), `parallel_remote` (3), `max_children` (8 per parent turn), `max_depth` (1), `child_max_steps` (25), `workflow_tokens` (400,000 per parent turn, every sub-agent's prompt and reply tokens), `queue_wait_s` (1800); a refused spawn is `workflow_limit`, `workflow_budget`, `workflows_off` or `invalid_arguments`, and only one sub-agent per workflow may change files at a time (`write`). The queue starts the oldest queued sub-agent whose slot has room, after each sub-agent's turn and every 5 s (also those queued before a restart); one that waited past `queue_wait_s` ends in an error (`queue_timeout`). A sub-agent whose turn ended without waiting on a card is finished, unseen (`spawn.seen: false`, `spawn.ended`); its result is `{child, label, state, answer (its last reply, cut at 8,000 characters with a link), refused?: [tools], error?}`. Stopping a chat (`Agent.on_cancel`, after its own turn stops) stops its sub-agents, queued ones first (`cancelled`, with a note), and theirs in turn; past the token budget, the turn's sub-agents are stopped with a note and further spawns refused. Each change sends a transient `agent_child` `{child: <tree row>}` to the parent's and the root's streams, and an `agent_child` `{id, parent, root, child}` to every `/v1/streams` connection opened with `watch=workflows` (3.1: the sidebar's tree).
  - **The `agent` tool (1.3, `workflows/tool.py`):** a local tool `agent {prompt, label, model?, write?}` (its follow-up tools `agent_wait`, `agent_send`, `agent_stop`, `agent_list` and `agent_review` only once the chat has sub-agents: 5.2, about 480 tokens a call saved in chats that never spawn), offered when workflows are on, the chat is above `max_depth` and its model's window (or the chat's own cap) is at least `min_window` (16,384); the *Sub-agents* prompt part after *Scheduled task* says when to use it (independent parts, side by side; never one lookup or steps that build on each other), that a sub-agent sees none of the chat, and how many run at once on the chat's model. It spawns and waits: transient `progress` events `{id, note: "<label>: running <tool> | thinking | waiting for a free slot | waiting on a card", live: {agent: {child, label, state, tool, calls}}}` while it runs; the result is the runner's plus `chat: "#/chat/<id>"` and `data.agent`, its answer inside `<untrusted source="sub-agent <label>">` when the sub-agent read outside text, and the sub-agent is then seen. It counts as a read, so several in one step are gathered and run side by side, each in its slot; a turn resumed after a restart waits for the sub-agent its call started (`spawn.tool_call_id`). A sub-agent's own prompt part says whose sub-agent it is, that its last reply goes back, whether it may change files, and not to ask questions.
  - **In the background (2.1):** `agent {…, background: true}` returns at once `{child, label, state, background, chat, note}` (`spawn.background`, `spawn.reported: false`). When such a sub-agent ends, its parent gets a stored `agent_done` event (the result as the parent reads it: `{child, label, state, answer, refused?, error?, chat}`), which the model reads as a user-role message that says it is from GAIFA, not the user; an idle parent starts a turn, a running one reads it at its next model call (it counts in `_unanswered`, and a turn that ended just before it starts again), one waiting on a card reads it after. More local tools come with `agent`: `agent_wait {child?, timeout?}` (the first background sub-agent to end, or the one named; while one runs, ends aren't sent as events, and those it didn't return are sent when it ends; it returns `needs_review` at once when a sub-agent it waits for sends a request; `nothing_to_wait_for`, `timed_out` with `still_running`), `agent_send {child, text}` (a follow-up as a user event `by: "parent"`; a finished sub-agent is queued again, and its next end comes back as a background one's), `agent_stop {child}` and `agent_list`; a child that isn't the chat's own is `unknown_child`. A sub-agent stopped by `agent_stop` or with its parent reports nothing.
  - **Requests go to the parent (2.2, `workflows/requests.py`):** when a sub-agent's turn ends waiting on a card (a hub approval, or a question it asked anyway), its parent gets one `agent_request` event per card: `{id: rq_…, child, label, kind: approval | question, call, approval_id?, tool?, risk?, arguments?, ask_fields?, schema?, description?, grant_key?, limits?, why?, questions?, in_result}` (the card's fields from the sub-agent's approval, 3.4). A foreground `agent` call returns `{state: "needs_review", requests: [{request, child, label, tool, risk, arguments (inside <untrusted>)}], note}` (`in_result`: not sent again as a message) and the sub-agent goes on as a background one; a background sub-agent's request is a message from GAIFA (its arguments inside `<untrusted>`) and starts an idle parent's turn. `agent_review {request?, action: deny | forward, reason?}` (the request may be left out when only one is open) writes an `agent_review` event `{id, child, action, reason, kind, approval_id?}`: deny decides the hub approval as denied with "the chat that started you said no: <reason>" (or answers the question with it), forward leaves the card to the user. There is no approve: anything but deny or forward is `invalid_request`. A request the parent's model read (or got in a result) and didn't review by the end of its turn is forwarded (`auto: true`). A request is open while it isn't reviewed and its card waits; the user can decide any card at any time (the header's Approvals, the sub-agent's chat), and `agent_review` on a card decided meanwhile is `invalid_request` or `already_decided`. An unattended sub-agent (a scheduled run's) gets no cards, so nothing is sent: what would ask is refused.
  - **Seen (3.2):** `POST /v1/threads/{id}/seen` marks a sub-agent's end as seen (`spawn.seen`, and an `agent_child` event); the Chat page calls it when one is opened.
  - **Deciding from the parent (2.3, `api_workflows.py`):** `GET /v1/threads/{id}/requests` lists the chat's sub-agents' requests, each with `waiting` (its card still waits), `open` (waiting and not reviewed) and its `review` (`?waiting=true`: only those waiting, the dock's cards); `POST /v1/threads/{id}/requests/{rid}` `{approve, arguments?, reason?, remember?, confirm?}` decides an approval through the sub-agent's chat (`remember: "thread"` is written for the workflow's root, §14.7), or `{answers}` a question; it writes an `agent_review` `{…, action: approve | deny | answer, by: "user"}` and answers 202; 404 for an unknown request, 409 `already_decided` for one no longer waiting.
  - **Memory and learning (2.4):** a sub-agent reads memory (the profile, recall, `memory_search`) but never writes it: it has no `remember` and its `agent_memory_*` tools are off, and `POST /v1/memory/save`, `/entity` and `/forget` answer `403 sub_agent` for a call from one (what it learned goes back in its answer). Sub-agents are `no_learn` and out of the chat list, so the preference miner, memory learning, the harness learner and chat summaries skip them. A scheduled run's sub-agents are unattended like the run, and the run's pre-allows cover them (grants on the root).
  - **Chats for other agents (4.1, `api_external.py`):** the agent mod's `[tools]` `chat_start` (execute), `chat_send` (execute), `chat_read`, `chat_wait` (read), `chat_stop` (write) and `chat_list` (read) are offered at `/mcp` as `agent_chat_*` (GAIFA's own chats never get them: they have the `agent` tool). `POST /v1/external/start` `{prompt, title?, model?, mode?, environment?, project?}` makes a root chat with `settings.external = {by: "mcp", client, started}` (the client from `origin.client`), in `mode` (manual by default; plan, accept_edits or auto; `bypass` is `422 bypass_refused`, a model the relay doesn't serve `400 unknown_model`), sends the prompt (`by: "mcp"`) and answers `{chat, title, state, link, note}`; `…/send {chat, text}`, `…/read {chat, after?}` (`{chat, title, state, running, answer, messages after the seq, last_seq, sub_agents, link, waiting_for_you?: [{kind, tool, risk, sub_agent?}], note}`), `…/wait {chat, timeout ≤ 60}` (until its turn ends, then the read), `…/stop {chat}` and `…/list` (this client's chats). Only chats started over `/mcp` and their sub-agents are reachable (else 404): the user's own chats stay theirs. The cards such a chat waits on are the user's to decide; the caller only reads that they wait.
  - **Its calls (1.4):** a sub-agent's hub calls carry `origin.root`, `origin.parent` and, unless it is the writer, `origin.read_only` (§14.7: refused above `read` and `network`; grants on the root cover it).
- **Code layout:**
  - `llm.py`: the model client
  - `loop.py`
  - `store.py`: the event log
  - `context.py`
  - `tools.py`
  - `prompts.py`
  - `server.py`

- **As built (plan Phases 13–14, 2026-10-07):**
  - **Models:** models on grammar-constrained servers (llama.cpp, facts from `/props`) get every tool loaded, since they can only name tools they were given; others get tools on demand.
  - **Model output:** the client repairs what vLLM's streaming parsers drop. Truncated tool-call JSON is closed, a reply that comes back empty is asked again without streaming, and Gemma's `<channel|>` thought marker is split off as thinking.
  - **Buttons:** a button's call is introduced in the history as the user's.
  - **Restarts:** a graceful restart leaves turns running, and they resume at the next start.
  - **Memory:** eval threads (`dry_run`) never write memory.
  - **Turned-off groups:** `load_tools` and `find_tools` say a group is turned off in this chat (an error for the group, `turned_off` for named tools) rather than listing its tools as unknown. `hub_start_service`, `hub_stop_service` and `hub_unload_service` are refused for a turned-off mod.
  - **The calendar in the prompt (calendar 5.2, `context.chat_agenda`):** when the calendar mod is ready and not turned off in the chat, the system prompt ends its Environment with *Your calendar*: the mod's `GET /v1/agenda/prompt` (today's items, to-dos due today and overdue, all of tomorrow, and in a project's chat the project's next 14 days; at most 40 lines). The text lists whole days and no time, so it changes only with the calendar or the date (a local server's prefix cache holds); the agent keeps it 20 s. The calendar's setting *Today's agenda in chats* turns it off. The meter counts it under instructions.
  - **Prompt rules:** the system prompt asks the model to look at an image (`view_output`) before describing it, says which groups are off and when a chat is read-only, and forbids stopping mods or LLMs to make room.
  - **Evaluation:** the eval and live results are in [agent-eval.md](agent-eval.md).
- **The chat list (plan 41.1, chat-history 1.1):** `GET /v1/threads?q=&archived=&environment=a,b&sort=updated|created|title&limit=&offset=` (`q` searches titles and messages; a chat without `settings.environment` is in `default`), `GET /v1/threads/groups?archived=` (per environment: count, newest `updated`, running or waiting) and `GET /v1/threads/count?q=&archived=&environment=` → `{count}`, the list's length for the same filters without a limit. `archived` is `false` (the default), `true` or `all` (live and archived together; each thread carries `archived`).

### 14.2 Threads, questions and approvals survive restarts
1. **The event log.** A thread is an append-only log in `agent.db` (`threads`, `events`): messages, thinking, tool calls, results, questions, answers, approvals, recalls, a project chat's page refreshes (`project_refresh`, plan projects 3.5) and compaction marks. The model's messages are rebuilt from it, and a page reconnects with `GET /v1/threads/{id}/events?after=`. A user event carries the page's `client_id` when it sent one (`POST /v1/threads/{id}/messages`), so the page can match the message it drew at once (chat-responsive 1.1). `POST /v1/threads` takes the first `message` (the same body) and makes the thread and sends it in one call, answering the thread with that message's `event` (1.2); a model the relay's last list names is accepted without asking the relay again. **One stream for every open chat (chat-split 3.1, chat-responsive 3.1):** `GET /v1/streams?threads=<id>:<seq>,…`; its first event is `{type: "stream", id}`, and `POST /v1/streams/{id}/threads` `{add: [[thread, after]], remove: [thread]}` adds a chat to the open connection (its events after `after`, a `ready`, then live) or removes it, without a reconnect (404 once the stream ended). The context meter (`GET /v1/threads/{id}/context`) reuses the sizes of the prompt the chat's turn built in the last 10 s (`PROMPT_REUSE_S`) instead of building it again with its hub calls. **The queue (chat-responsive 2.1, `agent/queue.py`, `api_queue.py`):** a message sent while a turn runs is held in `agent.db` (`queue`, `queue_paused`), outside the event log, so the model never reads it early; `POST …/messages` answers `{queued: item}` and the stream gets a transient `queue` event `{items, paused}` (also in each `ready`). When the turn ends idle, or the user stops it, every held message is written in order as its own user event (each with its recall) and one turn answers them together; a turn that ends in an error pauses the queue (`paused: "error"`) until `POST …/queue/resume`; a turn that ends waiting on a card keeps it until the turn after the answer ends. With no turn running, a message sent behind held ones sends them all, itself last (typing instead of answering a card dismisses it, as before). `GET …/queue`, `PATCH …/queue/{qid}` `{text?, index?}`, `DELETE …/queue/{qid}`, `POST …/queue/{qid}/send` (Send now) and `DELETE …/queue` (clear) change it; deleting a chat deletes its queue, and a fork doesn't copy it. `when: "now"` on a message (Send now) writes it at once with `queued` and `steer`, for the running turn's next model call; one written while the turn's last reply streams, or during its turn-end hooks, gets a model call of its own (a turn never ends with a message it hasn't read, unless the user stopped it).
2. **Pausing.** A question or a parameter card ends the request in a `waiting` state. Nothing is held in memory.
3. **Answering.** The answer (`/answer`), or the hub's approval with the edited arguments (`/approval`), is appended, and the same turn continues from the log. A card decided in the hub's Approvals popover continues the thread the same way; Stop dismisses a waiting card, and the hub's echo of that denial is ignored, so a stopped turn stays stopped. Stop also cancels a running hub call, whether it started directly or through a card.
4. **Rewind and branch.** Fork copies the events up to a chosen point into a new thread.

Both the event log and the hub's approval are on disk, so a reboot between steps 2 and 3 loses nothing. Deciding an approval past `agent.approval_ttl_h` closes it as `expired` and answers 409 `already_decided`. Each call reads the thread's mode when it's made, so switching to Plan mid-turn stops that turn's next change.

### 14.3 Save states
- **Chats.** Threads, the step history behind **rewind and branch** (continue from any earlier checkpoint), and titles and search (agent mod's tables in `agent.db`). A chat's title is its first words until its model names it: the first message goes to the model inside `<message>` as something to name (2–6 words), and a reply that reads as an answer (over 8 words or 60 characters, cut off, starting "For a…", "It seems…", "Sure", "Here…", or talking to the user) keeps the first words (`agent/prompts.py` `good_title`); a title filed under the reply's reasoning (vLLM's reasoning parser, with no thinking block) is used too. The model is asked for the title after the chat's first model call has begun (chat-responsive 3.2), so on a local GPU it doesn't compete with the reply.
- **Grounding (2026-10-21):** the base prompt asks the agent to search and answer from the pages it reads, with citations, for questions about the real world (facts, places, conditions, products, prices, news, health, advice that rests on facts), and not for chit-chat, the user's files, version-free coding help, creative writing or the chat itself. The web mod's `web_search` and `web_fetch` are `core` (always loaded).
- **Sessions.** The hub can **snapshot the current setup**: which mods are running and loaded, lcpp's instances with their launch settings, and ComfyUI's state. Each snapshot is saved under a name in `hub.db`.
  - **Restore** replays a snapshot through the memory manager, so it never overcommits memory.
  - Optionally, the last session is restored at boot. At each start the previous run's auto-saved "Last session" is copied to "Before restart", which the auto-save never overwrites; the boot restore and the unclean-shutdown offer use that copy (before this, an auto-save five minutes after a reboot replaced the setup worth restoring).
  - Named setups ("LLM work", "3D work") can be switched with one action.
- **Backups.** `gaifa backup` (Phase 12.5) also covers `agent.db` and the session snapshots.

### 14.5 Records and preferences (plan Phase 21)
- **Records.** Every tool attempt from every caller is in `hub.db`:
  - `tool_calls` (duration, what the hub `filled`);
  - `approvals` (what was `filled`, what the user `edited`);
  - `tool_refusals` (calls refused before they ran).
- **Preferences** (`utils/prefs.py`, `/api/prefs`) are hub data, so chat, MCP clients and buttons all get them:
  - A tool preference sets one argument, under `when` conditions. A choice that needs a picture applies only with one; that is derived from its `x-options`.
  - **On a call,** after the capability defaults (§14.1), active preferences fill arguments the caller left out or left at the default. An explicit value wins, and so does a card edit. Each filled field is marked `pref:<id>` or `carried`.
  - **After an approval,** the fields the user edited are carried to that chat's next card of the tool. An edit away from a preference's value counts against it: two contradictions retire an inferred preference.
  - **Off switches:** `[learning] enabled = false` or a chat's `no_learn` origin stop all of it.
  - **Never learned (plan 24.8):** document contents never become preferences or memories. The miner skips free-text fields (`prompt`, `text`, an instruction…) and the hub refuses an `inferred` preference on one (`free_text`); the learner's transcripts show an attached document as its card (`(document #n: name, 12 pages)`) and a tool result (a read document, a fetched page, a transcript) as its status only.
  - **`remember`** runs as `agent_memory_save` (the agent mod's own tool, structured-memory 3.2; it was `hub_set_preference` until then) through the call path: Plan refuses it, and otherwise it gets a card (the default `ask` list: `hub_set_preference`, `agent_memory_save`, `agent_memory_entity`), shown in the composer's dock and the header's Approvals; a chat that read untrusted text gets a card even with a grant. Prose preferences are memory now; `hub_set_preference` keeps tool settings.
- **Structured memory** (plan structured-memory; `services/agent/agent/memory/`, tables `mem_*` in `agent.db`) is the agent's own, never the hub's, so MCP clients never see it:
  - **Entities** form a tree (the user `you`, `projects/GAIFA`, `projects/GAIFA/agent`, people, places, tools, topics, organizations), each with a stable id, a name, aliases and anchors (a workspace folder, a folder, a git remote, or an agent project: plan projects 4.2). A rename keeps the old name as an alias, so every fact and every old name still finds it; names resolve without a model (exact name or alias, normalized).
  - **Facts** are sentences about one or more entities, with `valid_from`/`valid_until`, a source (`stated`, `inferred`, `imported`), a state (`proposed`, `active`, `retired`, `rejected`) and evidence. A fact is never overwritten: a new one `replaces` it and the old one is retired and kept. The same sentence again counts as seen once more. Kinds: `preference`, `fact`, `interest` (what the user is into or learning for now; plan memory-auto-learning 3.1), `event`, `procedure`. A learned fact's `valid_from` is the date of the message its quote is in, and each piece of evidence keeps that message's time (`ts`), so a fact has the first and last time it was said. The profile (up to 3000 characters, memory-import 2.2; what doesn't fit comes in through recall) writes each of the user's facts with its time ("(since 2026-11)"), preferences first, newest first by when they began (`valid_from`, else when saved), then interests by when they were last said, and an "Earlier interests" line for interests not said for `interest_days` (90, `memory.json`) or replaced or ended in the past year ("(2026-09 – 2026-11)"); a learned preference or interest is filed under the user as well as what it's about. A learned fact that says the user stopped something (the model's `ends`, or "no longer X", "not X anymore", "instead of X" in its text or quote) replaces the newest current fact naming it without asking the model, and a proposed rename of it is dropped. The nightly tidy retires a learned interest that wasn't said or used for `interest_days` (logged by `tidy`, with Undo). `memory_search` with `history` also finds facts that held once, by their words and their entries' paths, and a question about the past brings the newest of them. `GET /v1/memory/facts?thread=&source=` lists what was learned from one chat: the chat shows it under its last turn ("Remembered: … · Review").
  - **Every change is logged** with the rows before and after (`mem_log`), so any change can be undone; forgetting a fact deletes it and scrubs it from the log.
  - **Routes:** `/v1/memory/tree`, `/v1/memory/entities/{id|name|path}` (with its facts, history and log), `/v1/memory/facts`, `/v1/memory/undo/{log}`, `/v1/memory/log` (`api_memory.py`).
  - **Writing from a chat:** `remember` (`{text, about?, kind?}`) and the agent mod's tools `agent_memory_save` (with `replaces`), `agent_memory_entity` (make, rename, move, describe) and `agent_memory_forget`, all `mcp = false` and decided by the hub like any write (`[tools]` in `services/agent/service.toml`, routes `/v1/memory/save`, `/entity`, `/forget`). A save's result offers up to three related current facts, so the model can mark one as replaced.
  - **Search** (`memory_search`, a local tool, so never in the hub's catalog): names and aliases found in the query, FTS5 keywords and meaning (the embed mod's `memory` text collection, kept in step by `memory/index.py` as facts and entities change; proposed and ended ones are taken out), fused by reciprocal rank; an entity found brings its current facts and its children's. Without the embed mod, names and keywords still answer.
  - **In every chat** (`memory/profile.py`): the system prompt's Memory section is a profile: the user's current facts, preferences first (≤ 1,500 characters), the active projects by name and summary, and for a chat in workspace folders the projects those folders are (an anchor at or above the folder, a workspace id, or the folder's name) with their facts. It changes only when memory does, so a local server's prefix cache holds. Each user message gets a recall: `memory_search` on its words (meaning given 2.5 s, names and keywords meanwhile), the facts not in the profile (≤ 8, ≤ 800 characters), stored as a `recall` event `{for: <the user event's seq>, memory}` (on the user event's `memory` before chat-responsive 1.1) and drawn into that message as a `<memory>` block, so a message is byte-identical every time it's sent. Recall runs after the user event is written, so a message shows at once; the turn's next model call waits for it (10 s at most). Not for eval threads; `data/agent/memory.json` `{"recall": false}` turns it off.
  - **Learning** (`memory/learn.py`, Phase 4): once a chat has been quiet for the summaries' idle time (not an eval's, not `no_learn`; `[learning] enabled = false` stops it), its new part goes to the chat's model (the agent's own when the relay doesn't serve it or it's a paid provider's; a failed pass waits like the summaries', 5 min doubling to 6 h) as the learner renders it (the user's words plain; the agent's side, tool results and documents' cards inside `<untrusted>`), which lists lasting facts the user stated, in the third person ("The user prefers…", never "I…"; one still in the first person is reworded once, `memory/wording.py`, plan memory-auto-learning), each with the user's quote, a confidence and whether it's sensitive, and renames as JSON; each is compared with the five nearest current facts (a second call: same, replaces, adds, skip) and saved with its evidence (the chat, the message its quote is in, the quote), new entries with it: **active at once** when it passes `memory/auto.py` (plan memory-auto-learning 2.1: auto-approval on in `data/agent/memory.json`; the quote found in one of the user's messages; confidence ≥ `auto_threshold`, 0.8; not sensitive by the model's flag or a word of the `always_review` categories; not replacing a stated fact; not in the first person), logged `fact_auto` by `learner` (Undo makes it a proposal again; `GET /v1/memory/auto` lists the last 14 days' that weren't kept, `POST /v1/memory/facts/{id}/keep`), else **proposed** with the reason in its evidence (`why`); a proposal said again `auto_after_seen` (2) times is approved the same way unless sensitive. Learning starts from the chats as they were when it first ran (a whole history would flood the review). A reply that isn't JSON is retried once. Nightly (`memory/tidy.py`, with the learner's nightly run): ended facts retired, near-duplicate entries proposed for merging, summaries written for entries with new facts, learned facts unused for 180 days proposed for retiring, learned facts still in the first person reworded (`POST /v1/memory/reword` does it now; each change is logged and can be undone; a stated fact keeps the user's words). Proposals act only when approved (a rename renames, a merge merges); rejecting or forgetting the last proposal about a proposed entry archives it. `POST /v1/memory/learn[?thread=]` (503 with a fix when the model didn't answer) and `POST /v1/memory/tidy` run them now.
  - **Imports** (`memory/sources.py`, `memory/imports.py`, `api_imports.py`; plan memory-import): another assistant's memory, as its answer to `EXPORT_PROMPT` (`GET /v1/memory/imports/prompt`: five sections, one `[YYYY-MM-DD] - entry` per line in a code block) pasted into `POST /v1/memory/imports {text, source}`. The entries are read without a model (the code block's inside, headers as sections, `[date]`/`[unknown]`, bullets; at most 200 KB and 1000 lines); the agent's background model then reads 20 at a time into facts (the third person; an instruction stays a rule for the assistant, about the user when it applies to any work, else about its topic or project), with their kind, what they're about, whether they're sensitive and, for a project, its entry (old names as aliases, a summary). An entry imported before is `same` without asking; the rest go through the learner's compare step (`memory/compare.py`, shared). The result is a **preview** (`GET /v1/memory/imports/{id}`, read in the background, one import at a time): each fact's op, the held fact, and a default choice, `save` when `auto.decide_import` passes (the auto-approval rules, the entry standing for the user's words) else `review` with the reason. Nothing is saved until `POST /v1/memory/imports/{id}/save {choices}`: `source = imported`, `valid_from` the entry's date, evidence `{import, from, line, section, ts}` (`GET /v1/memory/facts?import=`), every change logged `by = import`. `DELETE /v1/memory/imports/{id}` undoes the import's changes through the log, newest first (what it replaced comes back; a fact changed since stays). Imports are rows of `mem_imports`. The nightly tidy retires imported interests like learned ones. Claude's export file is read the same way (`POST /v1/memory/imports/file {name, data}`, base64, 50 MB: the export's zip, whose `memories.json` holds `conversations_memory` and `project_memories` named by `projects.json`, or that `memories.json` alone; a ChatGPT export, which holds chats and no memory, is refused with what to do instead). `GET /v1/memory/export` writes the current memory in the prompt's format (Instructions, Identity, Projects, Preferences, Other; oldest first), and an entry that is a current fact's own text previews as `same` without a model call, so the export pasted back is all known.
  - **The page** (the agent's page, `ui/memory.js`): a Memory tab (the tree, an entry's facts with Edit and Forget, rename, aliases, summary, history with Undo, search, Remember something) and the memory proposals at the top of Review; Settings → Agent → Memory holds recall and fading (`data/agent/memory.json`) and the counts; the agent's status shows "Memories to review".
  - **Import:** at start, active `agent`-scope preferences become facts and are retired; the old `data/agent/memory/*.md` files once (marker `.structured`). The prompt's Memory section lists the current facts (and, until Settings' MEMORY.md editor goes, its lines that aren't facts).
  - **Untrusted text** in tool results comes inside `<untrusted source=…>`: web_search titles, snippets and answers, web_fetch's title and content (screening reads the page's own lines inside the block), workspace edit and write diffs and the `old_not_found` hint, stt's transcript, and `chat_search` summaries. Names and titles in the model's text are one line, with `<`/`>` replaced and a length cap.

### 14.6 The learner (plan Phase 22)
- **The harness is files.**
  - The base is in git, in `services/agent/harness/`: `systemprompt.md`, `guardrails.md`, `hooks.toml`, `tools/<tool>.md` notes and `skills/`.
  - Learned versions are overlays in `data/agent/harness/versions/<n>/` with a `current` pointer, so a rollback is moving the pointer.
  - A chat can pin a version (`settings.harness`), and each turn records the one it used.
- **Hooks** are declarative and four verbs only (hint after an error, cap, require a step first, trim). No model-written code runs in the loop.
- **The loop (after Harness², arXiv 2610.14224), in the agent mod and on the chat's own model:**
  1. reflect on an area's new chats;
  2. propose two scoped candidates, INV (how the agent works) and PREF (what you want);
  3. probe them by replaying chats as dry runs pinned to each candidate, scored from the record: the share of your card edits the candidate now pre-chooses, no repeated denials, no new errors;
  4. compose;
  5. gate on the eval (the area's tasks plus a core set; the full suite when a change reaches every chat), in dry runs only (no live task), 8 at a time, the tasks that reach this machine's GPU (`local_gpu` or attachments: stt, embed, the decide screener) one at a time;
  6. adopt;
  7. keep one lesson per round in that area's library, which only the improver reads. A lesson whose change went live is withdrawn (the editors stop reading it, Learning → Library marks it) once its version is rejected or rolled back; activating that version again brings it back.
- **Who adopts what:** the area's own tool notes and skill bodies are adopted automatically once the gate passes. Changes to the prompt, the guardrails, `hooks.toml` or a skill's description (listed in every prompt, at most 200 characters) wait for the user. A run may change tool notes only for its own area's tools. Chats that read a page, a file or a transcript never teach the learner; in the others the agent's own words, arguments and errors reach it inside `<untrusted>`, as does the review it passes to the editors. Hook hints are at most 300 characters, and `trim` closes an `<untrusted>` block it cuts (overnight 2026-10-21: a page's text could make the learner auto-adopt a skill whose description went into every later chat's prompt).
- **When it runs:** nightly, after `[learning] idle_min` without a chat, or on Learn now. It pauses while you chat.
- **Dry runs change nothing:** generating tools make stand-ins (a picture drawn from the prompt, a hard link to the newest real output of that kind, or a small stub when there is none), and write and destructive tools return a stand-in success. In a dry-run chat, `view_output` on a stand-in describes it (its prompt and settings, and that it stands in for a good result) instead of showing its picture, so a model that checks its work carries on. A person's `always` grants don't apply to dry-run calls (only the shipped ones and the chat's own), so the eval measures GAIFA's defaults on any machine.
- **Eval and test runs leave nothing behind:** when a run ends, the harness deletes its chats (with their events and turn records) and the outputs it made, dry-run stand-ins and live results alike, for good (`DELETE /api/outputs/{id}?permanent=true`, not the trash); seeds a task wrote to `outputs/eval/` go when the harness closes; the one-off live checks (`compact_live`, `meter_check`, `restart_live`) delete theirs too (`evals/cleanup.py`). `--keep` leaves them to look at. Only chats and outputs a person made stay.

### 14.7 Permissions: risks, the order, grants (plan Phase 25)
- **Risks.** Every tool has one: `read`, `write`, `generate`, `network` (reaches the internet), `execute` (runs code or commands) or `destructive`. A mod declares it in `[tools]` (`risk = …`) or its `tools_source`.
- **Modes** (plan 27.4, after Claude Code's): `plan` (reads only), `manual` (everything that changes something asks), `accept_edits` (edits and generations apply; commands, the internet and deletes ask), `auto` (as Accept edits, with a judge for commands, network calls and deletes, plan Phase 30) and `bypass` (edits and sandbox commands run; only in workspace folders that allow it). The old names map over: `ask` → `manual`, `read_only` → `plan`; `auto` is the Auto mode (the agent migrated stored `auto` threads, which meant "Use defaults", to `accept_edits`).
- **The order** in which a call is decided is fixed (`utils/tools/approvals.py` `decide`); the first that answers wins:
  1. the **deny** list of `[agent.permissions]`;
  2. a **mod's limits**: a mod with `[agent] limits` (the workspace mod) answers a preflight before each call: what it would do (`action`), the folder's level and Bypass, a diff or the command, and a refusal for hard limits (paths out of the folder, secrets, `.git/`, `sudo`, the GAIFA folder above Read) or a level too low ("needs the folder at Run"). A refusal ends the call in every mode; the mod checks again when the call arrives; a preflight that fails refuses;
  3. the thread's **mode**: with limits, the cell of the table below for the call's action (Bypass in a folder that doesn't allow it counts as Accept edits); without, `plan` denies everything but `read`;
  - *Between 3 and 4:* a lasting preference (`hub_set_preference`, and the agent's `remember`, which runs as it) asks when the call's `origin.untrusted` says its chat has read a page, a file or a transcript, whatever a grant, the allow list or the mode says (overnight 2026-10-21: an injected page could save a preference that went into every later chat's prompt).
  4. a **grant** that covers the call allows it, keyed by the mod's `key` when it gives one (the folder, its subfolder `cwd` and the exact command line, plus whether it has internet or runs on this machine; a compound command (`;`, `&&`, `||`, `|`, `&`, backticks, `$(`, newlines, redirections) has no key and is allowed one call at a time); never for actions that ask every time (`host`, `remote`, `commit`); in a dry run (the agent eval) only the grants GAIFA ships (`gr_default_*`) and the chat's own count;
  - *With limits (plan 34):* a preflight may answer `ask_folder: {path, level, max_level, capped?, environment}` (a read in a folder outside the chat's environment). That asks in every mode; no grant, list or judge lifts it. "Allow for this chat" writes a folder grant (`kind = "folder"`, `tool = "<mod>_*"`, `key = "folder:<path>"`, thread scope only; "always" is refused with `folder_always`). For every call to a mod with a preflight, the hub drops any `origin.folders` the caller sent and fills it from the chat's folder grants (always Read). The agent sends `origin.environment` (the chat's `settings.environment`); its prompt lists the chat's folders. Workspace folders belong to **environments** (`data/state/workspace/environments.json`; `folders.json` migrated into Default): a folder's level is per environment, its id the same in every one; the agent may ask only for folders inside the home folder or a mounted drive, not hidden or secret-looking, symlinks resolved; the GAIFA folder and `data/models` stay at Read everywhere. *Several environments (plan projects 2.1):* the origin may carry `environments` (ids, primary first; it wins over `environment`): the call uses the union of their folders, a folder in more than one at the highest level any of them gives it; folder grants still add folders at Read, and `GET /v1/folders` then lists the `environments` too. An environment may belong to a project (`project`, the agent's project whose own folders it holds): `GET /v1/environments` leaves those out unless `?all=1`.
  5. the **ask** list; then a **page the chat's search found**: a `web_fetch` whose URL a `web_search` earlier in the same chat (`origin.thread`) returned runs without a card in every mode but Plan, with no judge in Auto (`utils/tools/searched.py`, 2026-10-21): the same URL after trivial normalisation only (scheme and host in lower case, no default port, no fragment, an empty path as "/"; no prefix matches, another query is another URL), from the chat's last 50 finished searches read back from `tool_calls` (so it holds across restarts), and only when the judge's URL rules don't flag it (credentials, a long encoded value, a private address take the usual way). The URL came from the search engine, so the model can't hide data in it; the record says `origin.found_by`. Then the **allow** list (`execute` ignores the allow list: only a grant skips its card). Defaults: `ask = ["hub_set_preference"]` (a lasting preference reaches every later chat, so it asks in every mode, Bypass too, unless you chose "Always allow" on its card), `allow = ["hub_start_service"]`. A preference that couldn't be saved (an unknown tool or field, a value the tool doesn't take, learning off) is refused before a card;
  6. the **risk default**: `read` runs; `write` and `generate` ask, or run in `accept_edits`, `auto` and `bypass`; `network` asks (in `auto` the judge decides); `execute` and `destructive` ask in every mode.

  | Mode | read | edit | delete | commit | command (sandbox) | network (sandbox + internet) | host (your machine) | remote (git push, …) | change (your records) |
  |---|---|---|---|---|---|---|---|---|---|
  | plan | run | refused | refused | refused | refused | refused | refused | refused | refused |
  | manual | run | ask | ask | ask | ask | ask | ask | ask | ask |
  | accept_edits | run | run | ask | ask | ask | ask | ask | ask | ask |
  | auto | run | run | judge | ask | judge | judge | ask | ask | judge |
  | bypass | run | run | run | run | run | run | ask | ask | run |

  `change` (calendar 4.1) is a change to the user's own records that should follow from their words: the calendar's preflight answers it for adding, changing, completing and deleting items (an item the agent made in the same chat, unchanged since, is `edit`, so it can clean up its own tests). In Auto the judge reads the user's own messages (`origin.said`) and the call; in a task run, the task's instructions. Its rules ask first when a calendar item's title has a word the user didn't say (`title_rule`, calendar 4.5); the rest is the model's.

  "judge" is Phase 30's seam: `decide` answers `"judge"` and the caller awaits `approvals.judge()` → `utils/tools/judge.py`:
  - **Rules first** (`judge_rules.py`, `judge_commands.py`): clearly safe calls run (read-only commands and known test runners, each only with the options on its list and no path outside the folder; edits inside the folder; documentation on an exact list of hosts); a command run with the internet on is never allowed by a rule (the model decides); clearly harmful ones ask (rm -rf outside build folders, pipes into a shell, dotfiles, history rewriting, killing processes, credentials, root).
  - **Your command rules** (`[agent.judge] allow_commands / ask_commands`, `judge_user.py`, edited in Settings → Permissions → Auto judge; plan 30.7): a rule is a command and its words with `*` globs, and a last `*` matches any further words (`pytest *`, `make -C * test`). Rules are matched per simple command, as written and after the rules' unwrapping (`uv run`, `env`, `timeout`, …), never against the line: `pytest *` doesn't cover `pytest; curl … | sh`, since each part is judged and the strictest wins. An ask rule always asks. An allow rule allows where the fixed rules allowed or were unsure, never where they ask (secrets, sudo, host runs, removing a tree or outside the folder, pipes into an interpreter, remotes, git push and history, the folder's level, a line that can't be read); it doesn't cover a command with a word the rules can't see (`$X`, `$(…)`, xargs), and a variable that changes what runs stays unsure. With the internet on, your allow rules apply only when every command in the line is covered by one. Verdicts from your rules have source `user` (rules `user-allow`, `user-ask`) with the rule in the reason; `/api/judge/recent` adds `suggest` (rules that would cover a command the model asked about). A compound command is `once` (no grant covers it), but in Auto it still goes to the judge, which reads each part.
  - **Then a model** (`[agent.judge]`: always a decision model in `decide`, d3-lite; never a chat model through the relay, plan web-approvals: a chat model took seconds per link, and a local one that wasn't loaded made every call ask) for what the rules leave unsure. It sees only the user's own typed messages (`origin.said`, which the agent sends in Auto and the hub never stores), the call, the folder and its level. It answers allow or ask.
  - **Reading a page** (`utils/tools/webread.py`, 2026-10-21): `web_fetch` gives the model numbered lines of the saved page and a trusted `cite` ("Cite this page as [host](url); cite a passage by its line as #n:120 …"; the agent fills in #n). A page longer than `max_chars`, with a question (`focus`, else the user's message this turn, sent as `origin.question` and kept in memory only), comes back as its most relevant passages first under `── lines a–b of N · under "…" ──`, with an "About this page" line and `relevance: {by, passages, chars, of_chars, ms, note}`. `[agent.web] relevance = auto|decide|lexical|off` (auto: the decide mod only while it's up with its model loaded; decide re-ranks lexical's best `candidates`, falling back to lexical after `timeout_s`). Only what is shown is screened, on a copy with the other lines blank; code and table rows without a sentence go to the patterns only (`structural`); `[agent.screen] parallel` sets the model calls at once. A link the user typed in the chat (the agent sends the links of the user's own messages as `origin.links`) is fetched without a card in every mode but Plan, like a page the chat's search found (`searched.shared`); the hub drops `said`, `question` and `links` from an origin before storing it (the call records `shared_link: true`).
  - **Screening** (`screen.py`, plan 30.6, 30.8): text from outside goes through fixed patterns (hidden characters, chat-template tokens, HTML comments, long encoded blobs), then a model reads every passage that has words. The model is `[agent.judge]`'s unless `[agent.screen]` names its own (`screen_config`): a chat model reads windows of numbered passages; a decision model (`decide`) answers one yes/no question per passage, 4 calls at once. With no model of its own, screening uses the judge's, d3-lite. (`confirm`, the judge's chat model re-reading what d3-lite flags, ended when the judge became a decision model only; `[agent.screen] confirm` is ignored, and only the screen eval still sets one.) Removed passages become `[removed by screening: …]` lines, so line numbers hold. `web_fetch` results are screened as they arrive; `hub_read_document` windows and `/text?screened=true` when `[agent.screen]` covers the output (pages always; uploads and transcripts when turned on); `POST /api/web/read` screens a whole page once and keeps the report.
  - **Defused input:** what the model reads has chat-template control tokens (`<|turn>`, `<turn|>`, `<|im_start|>`, `[INST]`, `<s>`, …) changed to lookalikes (`‹`, `［`), since llama.cpp parses special tokens in the rendered prompt; the agent does the same to user and tool text it sends its own model.
  - **Fail closed:** a timeout (3 s), an error, a malformed answer, or arguments the model couldn't read whole (a string over 1,500 characters, over 50 items, deeper than 6, over 6,000 characters in all) asks without the model. It never denies. The verdict must be the reply's last JSON object, after any thinking.
  - **The record:** the verdict goes into the call's `origin.judge` (the result, the card and the step row show `why`: "Auto: ran (judged safe: …)" or "Auto: asked you (…)") and into the `judged` table (`GET /api/judge/recent`).
  - Host runs, remotes and commits never reach the judge. `GET /api/judge/status` says whether the judge's model answers.
- **Grants** (`utils/tools/grants.py`, table `grants`, migration 009): one answer that covers more than one call. Deciding an approval with `remember: "thread"` ("Allow in this chat"), `"sites"` ("Allow every site in this chat", web tools) or `"always"` writes a grant `{tool, key, scope, thread, expires_ts}`; `once` (the default) writes none. `always` for `execute` and `destructive` needs a second confirm (`confirm: true`, else 422 `confirm_needed`); `thread` needs a call from a chat (else 422 `no_thread`).
  - **Keys.** A tool may declare `grant_key` in `[tools]` (or its `tools_source` item): `url:host` takes the host of its `url` argument (exact: `api.github.com` is not `github.com`), `arg:<name>` takes that argument as is (a folder), `const:<x>` is always `x` (every search). A grant covers a call of its tool whose key equals the grant's; a tool without a grant key gets grants that cover every call. **Every site in one chat** (plan web-approvals 2.1): `remember: "sites"` on a `url:host` tool writes a `thread` grant with `key = "*"`, `kind = "url:any"`; it covers the tool on any host in that chat while the URL passes the judge's URL rules (`judge_rules.fetch_rule`: credentials, a long encoded value or a private address take the usual way), and the call's reason reads "allowed in this chat for every site". It is refused for a tool without `url:host` (`422 not_a_web_tool`) and outside a chat (`no_thread`).
  - **Shipped.** Migration 010 adds one `always` grant, `gr_default_web_search` (`web_search`, key `search`), so web searches run without asking (the user's decision, plan 26.2). It's listed and revoked like any other, and since a migration runs once per database, a revoked grant stays revoked.
  - **Who.** A `thread` grant covers calls whose `origin.thread` is that chat, or whose `origin.root` is (a sub-agent's workflow root, agent-workflows 1.4: grants on the chat that started a workflow cover its sub-agents, folder grants too, and "allow in this chat" decided on a sub-agent's card is written for the root; a sub-agent's own grant stays its own); MCP and API calls have no thread, so only `always` grants apply to them. A call run by a grant carries `origin.grant`. `GET /api/grants` lists the live ones (Settings → Permissions, with revoke); expired ones are dropped; `thread` grants end when the agent deletes the chat (`DELETE /api/grants?thread=`).
  - **Ahead of time (scheduled-tasks 2.1).** `POST /api/grants {tool, kind?, key?, thread, note?}` writes a `thread` grant before any call: a tool name or glob (every call of it), or for web tools (`grant_key = "url:host"`) one host (`kind: "url:host"`) or every site (`kind: "url:any"`, under the judge's URL rules). Never `always`, never a folder (folders stay with their levels). A scheduled run's pre-allows are these, and a call a grant ran answers with `grant_id`.
- **Read-only sub-agents (agent-workflows 1.4).** A call whose `origin.read_only` is set (a sub-agent not spawned as its workflow's writer) and whose tool's risk is above `read` and `network` (write, generate, execute, destructive) is refused before anything else decides it: `{status: "denied", error: {code: "read_only", …, fix}}`, kept with the refused calls. Reading here or on the web is decided as usual.
- **Unattended calls (scheduled-tasks 2.1).** A call whose `origin.unattended` is set (a scheduled run, with no one watching) never gets a card: what the order would have asked about is refused, `{status: "denied", error: {code: "unattended", …}}`, and kept with the refused calls. A judged one keeps the judge's verdict with `refused: true`, and the `judged` table marks it (migration 013); `GET /api/judge/recent` shows it as `refused`, and the step row says "Auto: refused, no one to ask (…)". A preflight's refusal and Plan mode's are unchanged. With the judge down it fails closed, so only granted, rule-allowed and mode-allowed calls run.

### 14.4 Everything inside the folder
- **Logs.** Each mod's output is also written to `data/logs/<id>.log`, rotated. journald stays as a second copy, and the Logs tab reads the file.
- **Runtime state.** lcpp's instance records move from `$XDG_RUNTIME_DIR/lcpp` to `data/state/lcpp` via `LCPP_STATE_DIR`. Instances are still systemd units, so after a reboot they come back through session restore, not by adoption.
- **What's left outside.** `gaifa doctor` then reports only the allowlist: the systemd unit file, podman images, system tools (ffmpeg, blender, podman), and the `~/.local/bin` wrappers. One mod writes outside the root: `searxng` changes SearXNG's `settings.yml` and keeps its backups next to it (plan 26.3).
- **As built (plan 16):** a shipper per mod follows the backend into `data/logs/<id>.log` (rotated 10 MB × 5) and the hub logs to `data/logs/gaifa.log`; the Logs tab and `gaifa logs` read the files. lcpp runs with `LCPP_STATE_DIR=data/state/lcpp` and forgets records from before the last boot. `gaifa doctor --inventory` lists every outside path with its reason.
