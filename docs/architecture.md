# AIHub — Architecture

> Agreed design, 2026-10-04. Companion docs:
> - [backend-plan.md](backend-plan.md): step-by-step build of the backend
> - [design-brief-ui.md](design-brief-ui.md): UI brief for Claude Design (its Sections 6 and 11.7 are the UI-facing API contract)
> - [reference/ui-export-2026-10-04/](reference/ui-export-2026-10-04/README.md): Claude Design's Part A v1, the UI baseline

## 1. Goal

AIHub is **one local app that controls every AI service on this machine**, from one UI and one API:
- the LLM relay and analytics (DashLLM)
- the llama.cpp launcher (lcpp)
- text to speech (LocalTTS)
- 3D generation (3DGenerate)
- later, image and video generation (ComfyUI) and a chat agent

It is built so that **anyone can add a service ("mod") by dropping a folder into `services/`**, with no changes to AIHub's own code.

**Not goals, for now:**
- Access from anywhere but 127.0.0.1, accounts, or a login.
- Merging the apps' code into one process.
- Porting the Mango-Tree personal apps. They can come later as mods.

## 2. Decisions

| Topic | Choice | Why |
|---|---|---|
| Location | `/home/bdgr/Agents/AIHub`, one git repo | requested |
| Shape | A **hub in front of mods**. Each mod is its own process. | The apps' torch/Python stacks conflict: Kokoro and Breeze need different ROCm torch builds, gen3d runs in a Python 3.13 container, and lcpp and relay use 3.14. Stopping a process is how GPU memory is freed. relay's event loop is tuned for concurrency, and lcpp's model instances must survive restarts. |
| Hub stack | Python ≥ 3.12, FastAPI + uvicorn + httpx, SQLite, uv | same as all four apps |
| Hub address | `127.0.0.1:7000`, no auth | only reachable from this machine |
| Running mods | Each mod runs as a **temporary systemd user service** (`aihub-<id>.service`), started with `systemd-run` | the pattern lcpp already uses for models: survives hub restarts, logs go to journald, no unit files per mod |
| Installed services | Only `aihub.service` (runs `app.py`) | today there are four separate ones |
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
| Chat, agent, save states | **Built last** (backend-plan Stage D): the agent is a mod built on **LangGraph with a SQLite checkpointer**; sessions can be saved and restored; logs and runtime state move inside the folder | requested: do these once everything else is built |
| Git history | The existing repos are merged in with `git subtree` | keeps every app's history |
| Heavy runtimes (engine venvs, CubeArt, the ROCm image) | Referenced where they are first, moved inside later | Python venvs can't be moved, so they must be recreated; don't break working GPU stacks while migrating |
| Mod ids | `relay`, `opencode`, `lcpp`, `tts`, `gen3d`, `comfy` | They become URLs (`/api/s/tts/…`, `#/s/tts`), so they are fixed once chosen. |
| Ports | Keep 4000 / 4096 / 7710 / 5040 / 5050. comfy adapter 5070 (ComfyUI itself on 8199). New mods use 5100–5199. | clients such as video-maker keep working |

## 3. Directory layout

```
AIHub/
├── CLAUDE.md                short, only rules that are true today
├── app.py                   `python app.py` starts the hub (same as `aihub serve`)
├── config.toml              your settings: hub, paths, memory rules, per-mod overrides
├── pyproject.toml, uv.lock  hub dependencies (uv); the hub's venv is the hidden `.venv/`
├── bin/
│   ├── aihub                the command: start · stop · status · logs · new · install · doctor …
│   └── aihub.service.in     systemd unit template, used by `aihub install`
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
│   ├── proxy.py             /api/s/<id>/* passthrough (streaming, SSE, uploads)
│   ├── operations.py        mod OpenAPI → Operation[]
│   ├── memory.py            memory sampling, plans to make room, acquire
│   ├── proc.py              meminfo, AMD GPU sysfs/fdinfo, per-process memory (from lcpp)
│   ├── registry.py          models registry: scan, verify, add, delete
│   ├── outputs.py           outputs watcher, index, previews, file serving
│   ├── tools.py             (later) agent tool catalog and approvals
│   ├── cli.py               standard-library-only CLI behind bin/aihub
│   ├── routes/              one FastAPI router per area
│   └── tests/               pytest, grouped by area (<area>/test_<behavior>.py); fixtures/mods/ holds fake mods
├── services/                one folder per mod (see §4)
│   ├── _template/           what `aihub new <id>` copies
│   ├── relay/  opencode/  lcpp/  tts/  gen3d/  comfy/
├── data/
│   ├── models/
│   │   ├── registry.json    the only tracked file under data/
│   │   ├── llm/             <Name>/*.gguf (+ mmproj-*, mtp-*, split parts)
│   │   ├── tts/             breeze-tts-2/, …
│   │   ├── stt/             (Whisper, when not in hf-cache)
│   │   ├── voices/          <slug>/reference.wav + voice.json
│   │   ├── 3d/              cube3d-v0.5/, cubepart/, Qwen3-VL-4B-Instruct/, clip-vit-large-patch14/
│   │   ├── comfyui/         ComfyUI's own layout: diffusion_models/, text_encoders/, vae/, loras/, unet/, …
│   │   └── hf-cache/        HF_HOME for every mod
│   ├── databases/           hub.db, relay.db, gen3d.db (+ agent.db in Stage D)
│   ├── logs/                Stage D: per-mod logs (until then: journald)
│   └── state/               Stage D: runtime state, e.g. lcpp's instance records (until then: $XDG_RUNTIME_DIR)
├── outputs/                 <mod>/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext> (+ .json sidecar) or a folder per job
└── web/                     the UI, as Claude Design exports it
    ├── Hub.dc.html          shell + core pages (served at /, with vendor scripts and /config.js injected)
    ├── *.dc.html            shared components: OutputCard, JsonView, ModPage, charts (§11.6 of the brief) …
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
| Models | `[models] dirs` | registry entries in those folders are listed as "used by" this mod |
| Custom page | `ui/page.js` or `ui/Page.dc.html` (UI brief §5) | own tabs inside the AIHub shell |
| Dashboard widgets | `[[ui.widgets]]` pointing at a route that returns `WidgetData` (UI brief §11.7) | its charts on the Overview dashboard |
| Charts for free | numeric values in `stats` (§4.6) | each one is recorded as a series `svc.<id>.stat.<slug>` and drawn as sparklines and charts |
| API polish | `[api]` hide list and response-kind overrides | a cleaner API tab |
| Agent tools | `[tools]` | operations the future agent may call, with optional approval |
| Call back into the hub | `AIHUB_URL` env | register models, ask for memory |

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
install = "install.sh"              # optional; run by `aihub new` / `aihub install <id>`

[memory]                            # only for mods that hold models in memory
estimate_gb = 9.2
load = "POST /v1/load"
unload = "POST /v1/unload"
triggers = ["POST /v1/speech", "POST /v1/audio/speech"]   # proxied calls that may load models
extra_units = []                    # other systemd units counted as this mod's memory, e.g. "lcpp-*.service"
containers = []                     # podman containers counted as this mod's memory

[models]
dirs = ["tts", "voices"]            # data/models subfolders this mod uses

[outputs]                           # its presence means the mod writes to {outputs}
kinds = ["audio"]

[ui]
page = "ui/page.js"                 # optional custom page (or "ui/Page.dc.html")
native = "/ui/"                     # optional: the mod's own UI, linked from its page header

[[ui.widgets]]                      # optional: charts for the Overview dashboard
id = "clips"
title = "Clips per day"
kind = "bar"                         # line | area | bar | donut | number | table
source = "GET /v1/hub/widgets/clips" # returns WidgetData; receives ?range=
ranges = ["7d", "30d"]
span = 4                             # grid columns out of 12

[api]
hide = ["GET /ui/{path}"]
[api.responses]                     # response kinds FastAPI can't infer
"POST /v1/speech" = "audio"
"POST /v1/audio/speech" = "audio"

[tools]                             # used by the agent later
speak = { op = "POST /v1/speech", description = "Speak text in a saved voice" }
delete_voice = { op = "DELETE /v1/voices/{name}", confirm = true }
```

`config.toml` may override `port`, `env` (merged), `enabled`, `autostart`, `idle_unload_s`, `auto_unload` and `priority` per mod.

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

**Environment every mod gets:** `AIHUB_URL`, `AIHUB_SERVICE_ID`, `AIHUB_PORT`, `AIHUB_ROOT`, `AIHUB_MODELS`, `AIHUB_OUTPUTS`, `AIHUB_DATABASES`, `HF_HOME` (unless the mod sets its own) and `PYTHONUNBUFFERED=1`.

### 4.5 Port rules
- A mod keeps the port in its manifest unless `config.toml` overrides it.
- `aihub new` picks the first free port in 5100–5199.
- If the port is taken by something other than the mod's own unit, the start fails with `port_in_use` and names the process holding it.

### 4.6 Status shape (optional `[run] status` route)

```json
{
  "loaded": true,
  "busy": false,
  "idle_s": 42.0,
  "memory_estimate_gb": 9.2,
  "stats": [{"label": "Voices", "value": 3}, {"label": "Clips today", "value": 12}],
  "jobs": [{"id": "j_1", "label": "low-poly fox", "progress": 0.4, "state": "running", "route": "#/s/gen3d/jobs?id=j_1"}]
}
```

- **`loaded`**: models are in memory; omit or set `null` if the mod has none.
- **`memory_estimate_gb`**: optional; overrides the manifest estimate, for example per workflow.
- **`stats`**: at most 4 entries. **Numeric `value`s are recorded** each time status is polled, as the series `svc.<id>.stat.<slug(label)>`. That powers tile sparklines and the mod's charts with no extra work. Counters that reset ("… today") should say so with `"reset": "daily"`, so charts don't show the reset as a drop.

### 4.7 Output conventions
- **Where:** write into `{outputs}/<YYYY-MM-DD>/`.
- **File outputs:** name them `<HHMMSS>-<slug>.<ext>`. Write to `<name>.part` first, then rename; the watcher ignores `*.part` and dotfiles.
- **Folder outputs** (e.g. a 3D job): a folder `<id>-<slug>/`. It is indexed only once it contains `output.json` with `"complete": true`.
- **Sidecar:** `<file>.json` next to a file output, or `output.json` inside a folder output. Every field is optional:

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
  - audio: wav, mp3, flac, ogg, opus
  - image: png, jpg, jpeg, webp, gif
  - video: mp4, webm, mov
  - model3d: glb, gltf, obj, ply, stl
  - text: txt, md, json
  - archive: zip
  - anything else is `other`
- **Previews:** the hub makes them itself (a video poster frame via ffmpeg) and stores them as hidden `.<name>.preview.jpg` files next to the output.

### 4.8 Adding a mod
1. Run `aihub new <id>`. It copies `services/_template/`, fills in the id, name and a free port, and runs its `install.sh`.
2. Edit `services/<id>/server.py` and `service.toml`.
3. Run `aihub restart`. The mod appears in the sidebar, with an Overview tile and a working API tab.

## 5. Runtime

**Boot** (`app.py` → `utils/server.py:create_app`). Nothing happens at import time. The lifespan starts these in order, and stops them in reverse:
1. config
2. db
3. event bus
4. models registry (load the registry, cheap status check)
5. services:
   - find all manifests
   - adopt running `aihub-*` units
   - autostart enabled mods in `after` order
6. outputs (rescan, then watch)
7. memory sampler
8. metrics recorder and rollups

**A request from the UI:**
```
browser ──► 127.0.0.1:7000
            ├─ /                     web/ (static) + /config.js (sets AIHUB_API_BASE)
            ├─ /ui/services/<id>/…   services/<id>/ui/… (page modules)
            ├─ /api/…                hub routes (services, memory, models, outputs, settings, events)
            └─ /api/s/<id>/…  ──►    127.0.0.1:<port>/…   (streamed; memory triggers run first)
```

**Processes:**
```
aihub.service                        app.py (hub)
aihub-relay.service                  relay (DashLLM)          :4000
aihub-opencode.service               opencode serve           :4096
aihub-lcpp.service                   lcppd                    :7710
  lcpp-<name>.service …              llama-server instances   :7071–7199 (owned by lcpp)
aihub-tts.service                    LocalTTS                 :5040  (+ engine worker subprocesses)
aihub-gen3d.service                  gen3d                    :5050  (+ podman worker container)
aihub-comfy.service                  comfy adapter            :5070  (+ ComfyUI in the strix-halo toolbox :8199)
```

`Ctrl+C` on `python app.py` stops only the hub; mods keep running. `aihub stop all` stops everything.

## 6. Hub API

The UI-facing contract is **Section 6 of [design-brief-ui.md](design-brief-ui.md)**. These routes are backend-only additions:

| Route | Purpose |
|---|---|
| `GET /config.js` | sets `window.AIHUB_API_BASE = ""` and `window.AIHUB_LIVE_AREAS = [...]` (the areas whose backend exists), so the served UI is live area by area |
| `GET /` | `web/Hub.dc.html`, with `vendor/react*.js` and `/config.js` script tags added before `support.js` as it's served, so a fresh export works unchanged |
| `GET /ui/services/{id}/{path}`, `GET /Mod_<id>.dc.html` | a mod's `ui/` folder (page modules), and its `Page.dc.html` under a name `dc-import` can find |
| `GET /api/metrics`, `/api/metrics/series`, `/api/timeline`, `/api/outputs/stats`, `/api/activity/stats`, `/api/jobs/stats`, `/api/widgets`, `/api/widgets/{service}/{id}` | chart data; shapes in UI brief §11.7 |
| `GET /api/outputs/{id}/file` | an output's main file (supports Range, for audio/video seeking) |
| `GET /api/outputs/{id}/files/{path}` | a file inside a folder output |
| `GET /api/outputs/{id}/preview` | thumbnail or poster |
| `POST /api/memory/acquire` | a mod asks for memory: `{service, needs_bytes, reason}` → `200 {granted, freed[]}` or `409 needs_room {plan}` |
| `GET /api/tools`, `POST /api/tools/{name}/call`, `POST /api/approvals/{id}` | later: agent tools and approval decisions |

**Error envelope:** every hub error is `{"detail": str, "code": str, "data"?: object}`, sent with an `X-AIHub-Error: <code>` header. Responses proxied from a mod are passed through unchanged (no header), which is how the UI tells a mod's error from the hub's. The hub only produces `service_not_running` (503) or `upstream_error` (502) when it can't reach the mod at all.

## 7. Memory manager

**Sampling** (every 2 s):
- **System:** `/proc/meminfo` (`MemTotal`, `MemAvailable`).
- **GPU:** AMD sysfs `mem_info_gtt_*` / `mem_info_vram_*`.
- **Per mod:** the processes in its unit's cgroup, plus its `extra_units` and `containers`. For each process, count RSS plus GPU memory from DRM fdinfo (`drm-memory-gtt` / `vram`). This logic comes from lcpp's `proc.py`.
- **Peaks:** each mod's observed peak is stored in `hub.db`, and used as the estimate when it's larger than the manifest's.

**Load rule:**
- `available = MemAvailable − reserve`.
- `needs = max(estimate, learned peak)`, or the `needs_bytes` the mod sent to acquire.
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

**Known limit:** clients that call a mod's port directly (e.g. video-maker → `:5040`) bypass the hub. Their loads aren't managed unless the mod itself calls `acquire`.

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
- **`status`** (`ok` / `missing` / `partial` / `unverified` / `checksum_mismatch` / `verifying`) is computed when the registry is read, not stored.
- **Who registers models:**
  - the scanner suggests entries and you confirm them
  - mods can register what they download (`POST /api/models` with their source)
  - lcpp's Hugging Face downloader does this first

## 9. `config.toml`

```toml
# AIHub settings. Each mod ships defaults in services/<id>/service.toml; values here override them.
# The Settings page edits this file and keeps comments.

[hub]
host = "127.0.0.1"          # loopback only; anything else is refused at startup
port = 7000

[paths]                     # relative to this file; must stay inside the project
models = "data/models"
databases = "data/databases"
outputs = "outputs"

[memory]
reserve_gb = 12
auto_make_room = false      # false: ask (Make-room dialog); true: unload idle mods automatically
never_unload = ["lcpp"]     # stopping LLM instances is never automatic
priority = ["comfy", "tts", "gen3d"]   # unloaded first → last

[ports]
new_mods = [5100, 5199]

[ui]
theme = "system"
density = "comfortable"

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
```

## 10. The existing apps as mods

| Mod | From | Port | Models | Databases | Changes inside the app |
|---|---|---|---|---|---|
| `tts` | `~/Projects/LocalTTS` | 5040 | `~/models/breeze-tts-2` → `data/models/tts/`; Kokoro and Whisper → `data/models/hf-cache` (copied); voices → `data/models/voices/` | — | status route, dated outputs + sidecars, `LOCALTTS_VOICES_DIR`, `save_dir` kept under outputs |
| `gen3d` | `~/Projects/3DGenerate` | 5050 | `~/Models/3D/CubeArt/weights/*` → `data/models/3d/` | `gen3d.db` → `data/databases/` | `GEN3D_DB`, `GEN3D_OUTPUTS`, `GEN3D_WEIGHTS` (+ container mount), per-job folder column, `output.json`, status route |
| `relay` | `~/Tools/DashLLM` | 4000 | — | `relay.db` (+ `-wal`, `-shm`) → `data/databases/` | status route (KPIs) |
| `opencode` | DashLLM's `opencode.service` | 4096 | — | — | none: a manifest-only mod |
| `lcpp` | `~/Models/LLMs` | 7710 | `models/*` → `data/models/llm/` | — (its JSON state stays in `services/lcpp/data/`) | `LCPP_MODELS_DIR`, catalog paths relative to it, downloads register in the hub, memory acquire, status route, `pidfd_open` fallback |
| `comfy` | `~/Models/ComfyUI*` + `~/.local/bin/comfyui` | 5070 (ComfyUI 8199) | `~/Models/ComfyUI/models/*` → `data/models/comfyui/` | — | new adapter mod (§11) |

**Moves are instant:** every source path and AIHub are on the same btrfs subvolume (`/home`), so `mv` is a rename, not a copy. Old paths keep a symlink until everything that uses them has been updated.

## 11. Later pieces

**comfy mod:**
- **The adapter:** a small FastAPI on 5070. Its load starts ComfyUI in the strix-halo toolbox (the existing `comfyui` script, moved into the mod), and its unload calls ComfyUI's `/free`. ComfyUI writes to `outputs/comfy` via `--output-directory` and reads models from `data/models/comfyui` via `extra_model_paths.yaml`.
- **Workflows:** each is `workflows/<name>/workflow.json` (API format) plus an `inputs.toml` that maps friendly inputs (prompt, seed, size, image) to node fields.
- **Running one:** `POST /v1/run {workflow, inputs}` patches the graph, queues it, and reports progress from ComfyUI's websocket.

**Agent-ready API** (Phase 13): `[tools]` sections become `/api/tools` (JSON-schema function definitions). Calls go through `/api/tools/{name}/call`, and tools marked `confirm` wait for an approval that the hub enforces. The same catalog can later be exposed as an MCP server, so Claude Code can drive AIHub too.

**Chat, agent and save states:** §14, built last.

## 12. Risks and gotchas

1. **Python venvs aren't relocatable.** Recreate them (`uv venv` + install) instead of moving them. The heavy engine venvs and CubeArt stay where they are until Phase 12.
2. **`git subtree` brings tracked files only.** Each app's ignored-but-needed state has to be copied separately, and `backend-plan.md` lists it for every app.
3. **Container bind mounts and symlinks:** a symlink inside a mount that points outside it is broken inside the container. Mount real paths, such as `data/models/3d` for gen3d.
4. **The Hugging Face cache uses a shared blob store** (`~/.cache/huggingface/hub/blobs`). Copy repos with `cp -rL` to dereference the links, and leave the originals in place for other projects.
5. **FastAPI's OpenAPI often can't tell audio or file responses apart from JSON.** Use `[api.responses]` overrides.
6. **SSE through the proxy must not be buffered:** stream raw bytes and use no gzip on `/api/s/*` or `/api/events`.
7. **Audio and video seeking need HTTP Range** on output files.
8. **Clients that call a mod's port directly bypass memory management** (§7).
9. **`git clean -x` would delete the models** (§3).
10. **Some UIs use absolute paths:** mods' own UIs keep working on their own ports and are linked as "native UI". AIHub's UI never loads them inside its own pages.
11. **The UI runtime is Claude Design's generated `support.js` (React 18).** Don't edit it. Any change a new export needs goes in `web/PATCHES.md`, and the brief asks Claude Design to fold those changes in on its next pass.
12. **Metric storage grows over time.** Rollups and retention (§13) keep `hub.db` small: roughly 30 series × 10 s for 48 h is about 0.5 M rows, pruned hourly.

## 13. Metrics and charts

**What gets recorded** (`utils/metrics.py`, in `hub.db`):

| Series | Source | How often |
|---|---|---|
| `mem.total`, `mem.used`, `mem.available`, `mem.reserve`, `mem.other`, `gpu.gtt_used` | memory sampler (§7) | 10 s |
| `mem.svc.<id>` | memory sampler, per mod | 10 s |
| `jobs.running` | status polls | on change, then held |
| `svc.<id>.stat.<slug>` | numeric `stats` from each mod's status route (§4.6) | every status poll (2–10 s) |

It also records **events** that charts need besides numbers:
- `service_states` (every state change, for timelines and uptime)
- `load_intervals` (loaded to unloaded)
- `job_history` (start, end, final state, service, label, from `job` events)

Outputs and activity statistics are queried straight from their own tables.

**Storage:**

| Table | Holds | Kept for |
|---|---|---|
| `metrics_raw (series, ts, value)` | 10 s samples | 48 h |
| `metrics_1m` | rollups: avg, min, max | 14 d |
| `metrics_1h` | rollups: avg, min, max | 400 d |

An hourly task rolls up and prunes. `GET /api/metrics` chooses the table from the range:
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
- **Isolated dependencies.** It has its own venv (`langgraph`, `langgraph-checkpoint-sqlite`, `langchain-openai`), so none of that touches the hub. Mango-Tree had pulled LangChain into its core.
- **Model.** `ChatOpenAI(base_url="http://127.0.0.1:4000/v1")`, so every agent call goes through the relay and shows up in its stats. Models are picked from the relay's `/v1/models`.
- **Tools.** Fetched from the hub's `GET /api/tools` (Phase 13) and executed through `POST /api/tools/{name}/call`.
- **Graph.** A LangGraph `StateGraph` with an agent node and a tools node, plus a step cap. When it hits the cap it says so instead of inventing an answer, which was one of Mango-Tree's bugs.
- **Saved state.** The checkpointer is `SqliteSaver` at `data/databases/agent.db`. Each chat is a LangGraph thread, and its state is saved after every step.
- **Code layout.** Graph wiring, node logic, state and prompts are kept apart: `graph.py` only assembles and compiles, `nodes.py` holds node behavior, `state.py` the state schema, `prompts.py` the prompt text. A second agent gets its own `agents/<name>/` folder with the same four files.

### 14.2 Approvals survive restarts
1. A tool marked `confirm` returns `needs_approval` from the hub.
2. The tools node calls LangGraph's `interrupt({approval_id, tool, args})`, and the checkpoint is saved.
3. The Chat UI shows an Approve/Deny card. Answering it calls `POST /api/approvals/{id}`, and the hub executes the tool (or doesn't) and stores the result.
4. The UI then calls the agent's resume route, and the graph continues with `Command(resume=…)`.

Both the checkpoint and the approval are on disk, so a reboot in the middle of step 3 loses nothing.

### 14.3 Save states
- **Chats.** Threads, the step history behind **rewind and branch** (continue from any earlier checkpoint), and titles and search (agent mod's tables in `agent.db`).
- **Sessions.** The hub can **snapshot the current setup**: which mods are running and loaded, lcpp's instances with their launch settings, and ComfyUI's state. Each snapshot is saved under a name in `hub.db`.
  - **Restore** replays a snapshot through the memory manager, so it never overcommits memory.
  - Optionally, the last session is restored at boot.
  - Named setups ("LLM work", "3D work") can be switched with one action.
- **Backups.** `aihub backup` (Phase 12.5) also covers `agent.db` and the session snapshots.

### 14.4 Everything inside the folder
- **Logs.** Each mod's output is also written to `data/logs/<id>.log`, rotated. journald stays as a second copy, and the Logs tab reads the file.
- **Runtime state.** lcpp's instance records move from `$XDG_RUNTIME_DIR/lcpp` to `data/state/lcpp` via `LCPP_STATE_DIR`. Instances are still systemd units, so after a reboot they come back through session restore, not by adoption.
- **What's left outside.** `aihub doctor` then reports only the allowlist: the systemd unit file, podman images, system tools (ffmpeg, blender, podman), and the `~/.local/bin` wrappers.
