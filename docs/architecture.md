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
| Chat, agent, save states | **Built last** (backend-plan Stage D): the agent is a mod with **its own loop, modelled on Claude Code** (no agent framework): tools load on demand, it asks for choices with question and parameter cards, threads are an append-only event log in SQLite; sessions can be saved and restored; logs and runtime state move inside the folder | requested: do these once everything else is built. Research: [agent-architecture.md](agent-architecture.md). A framework (LangGraph) was the earlier plan; a hand-written loop gives the control a local model needs (thinking fields, leaked tool calls, tool loading) |
| Git history | The existing repos are merged in with `git subtree` | keeps every app's history |
| Heavy runtimes (engine venvs, CubeArt, the ROCm image) | Referenced where they are first, moved inside later | Python venvs can't be moved, so they must be recreated; don't break working GPU stacks while migrating |
| Mod ids | `relay`, `opencode`, `lcpp`, `tts`, `gen3d`, `comfy` | They become URLs (`/api/s/tts/…`, `#/s/tts`), so they are fixed once chosen. |
| Ports | Keep 4000 / 4096 / 7710 / 5040 / 5050. comfy adapter 5070 (ComfyUI itself on 8199). New mods use 5100–5199: `web` 5102, `embed` 5104, `stt` 5105. | clients such as video-maker keep working |

## 3. Directory layout

```
AIHub/
├── CLAUDE.md                short, only rules that are true today
├── app.py                   `python app.py` starts the hub (same as `aihub serve`)
├── config.toml              your settings: hub, paths, memory rules, per-mod overrides
├── pyproject.toml, uv.lock  hub dependencies (uv); the hub's venv is the hidden `.venv/`
├── bin/
│   ├── aihub                the command: start · stop · status · logs · new · install · doctor · backup …
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
│   ├── proxy.py             /api/s/<id>/* passthrough (streaming, SSE, uploads, WebSockets)
│   ├── operations.py        mod OpenAPI → Operation[]
│   ├── memory/              memory sampling, plans to make room, reservations, triggers, acquire
│   ├── proc.py              meminfo, AMD GPU sysfs/fdinfo, per-process memory (from lcpp)
│   ├── registry/            models registry: storage, status, scan, verify, add, delete
│   ├── outputs/             outputs index: what counts, rows, media details and previews, watcher, trash
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
│   │   ├── stt/             <model>/ (faster-whisper: small/, large-v3-turbo/, …)
│   │   ├── voices/          <slug>/reference.wav + voice.json
│   │   ├── 3d/              cube3d-v0.5/, cubepart/, Qwen3-VL-4B-Instruct/, clip-vit-large-patch14/
│   │   ├── comfyui/         ComfyUI's own layout: diffusion_models/, text_encoders/, vae/, loras/, unet/, …
│   │   └── hf-cache/        HF_HOME for every mod
│   ├── databases/           hub.db, relay.db, gen3d.db (+ agent.db in Stage D)
│   ├── logs/                Stage D: per-mod logs (until then: journald)
│   └── state/               Stage D: runtime state, e.g. lcpp's instance records (until then: $XDG_RUNTIME_DIR)
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
containers = []                     # podman containers counted as this mod's memory (globs allowed)
idle_unload_s = 180                 # the mod's default; config.toml may override (0 = never)
idle_unload_env = "LOCALTTS_IDLE_UNLOAD_S"   # the variable the mod reads it from (AIHUB_IDLE_UNLOAD_S is always set too)

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
hide = ["GET /ui/{path}"]              # globs on "METHOD /path", e.g. "* /admin/*"
[api.responses]                     # response kinds FastAPI can't infer
"POST /v1/speech" = "audio"
"POST /v1/audio/speech" = "audio"

[tools]                             # the agent's tools (plan 13.1): <mod>_<name>, schema from the OpenAPI
speak = { op = "POST /v1/speech", description = "Speak text in a saved voice", risk = "generate", ask = ["name"], hide = ["stream"] }
delete_voice = { op = "DELETE /v1/voices/{name}", confirm = true }
# fetch = { op = "POST /v1/fetch", risk = "network", grant_key = "url:host" }   # grant_key: url:host | arg:<name> | const:<x> (§14.7)
# risk: read | write | generate | network | execute | destructive (default: read for GET, destructive for DELETE/confirm, else write; §14.7)
# ask = [...] inputs the user chooses (parameter card) · examples = [{...}] · core = true (always loaded)
# hide = [...] / fixed = {...}: parameters kept from the model / always sent
# job = true + job_status = "GET /v1/jobs/{id}" (+ job_cancel): the hub follows the job to its outputs

[agent]                             # optional: tools the mod lists at runtime (comfy: one per task)
tools_source = "GET /v1/tools"      # → {"tools": [{"type": "function", "function": {name, description, parameters}, "op": "POST …", "job": {…}|null, "risk", "ask", "examples", "core", "grant_key"}]}
skills = "skills"                   # optional: skills/<name>/SKILL.md for the agent (plan 14.9)
```

`config.toml` may override `port`, `env` (merged), `enabled`, `autostart`, `idle_unload_s`, `auto_unload` and `priority` per mod.

**Parsing rules** (`utils/manifest.py`):
- Only `id` and `[run].port` are required, plus `[run].command` for `kind = "process"`. `name` defaults to the id, `icon` to `box`.
- Unknown keys are errors, so a typo is reported rather than ignored. Each problem becomes one entry in the mod's `manifest_errors`; a broken mod is still listed (by folder name) and never stops the hub.
- `command` is a list, or a string split like a shell would. The executable resolves against the mod folder when it contains a `/` (`.venv/bin/python`); a bare name (`python3`) is looked up on `PATH`. Other arguments starting with `./` or `../` also resolve against the mod folder; the rest are passed as written (relative to `cwd`).
- Numbers and booleans in `env` become strings (`2` → `"2"`, `false` → `"false"`).
- Operations (`[memory]`, `[[ui.widgets]].source`, `[tools]`, `[api.responses]` keys) are written `"METHOD /path"`.
- `[ui].page` must be inside the mod's `ui/` folder.
- Two mods can't share a port, and no mod may use the hub's port.
- Mods not mentioned in `config.toml` are enabled and autostart.

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

**Environment every mod gets:** `AIHUB_URL`, `AIHUB_SERVICE_ID`, `AIHUB_PORT`, `AIHUB_ROOT`, `AIHUB_MODELS`, `AIHUB_OUTPUTS`, `AIHUB_DATABASES`, `HF_HOME` (unless the mod sets its own) and `PYTHONUNBUFFERED=1`. A mod with `[memory]` also gets `AIHUB_IDLE_UNLOAD_S` (seconds, `0` = never) and the same value under its `idle_unload_env` name, after `[run].env` and before `config.toml`'s env.

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
- **Polling:** every 2 s while loading, busy or running jobs, otherwise every 10 s, only while the mod is ready. Invalid parts of the body are ignored (`aihub check` lists them).
- **`jobs`**: each `{id, label, progress (0–1 or null), state, route?}`, with `state` one of queued, running, done, failed, cancelled. Report finished jobs with their final state; a job that just disappears is shown as `done`.
- **`stats`**: at most 4 entries. **Numeric `value`s are recorded** each time status is polled, as the series `svc.<id>.stat.<slug(label)>`. That powers tile sparklines and the mod's charts with no extra work. Counters that reset ("… today") should say so with `"reset": "daily"`, so charts don't show the reset as a drop.

### 4.7 Output conventions
- **Where:** write into `{outputs}/<YYYY-MM-DD>/`.
- **File outputs:** name them `<HHMMSS>-<slug>.<ext>`. Write to `<name>.part` first, then rename; the watcher ignores `*.part` and dotfiles.
- **Folder outputs** (e.g. a 3D job): a folder `<id>-<slug>/`. Write `output.json` with `"complete": false` when you create it and set `"complete": true` when the job is done: a folder with `output.json` is indexed as one output, and only once it is complete. A folder **without** `output.json` is just a folder: each file in it is its own output (so a mod's own subfolders, like ComfyUI's, work as they are).
- **Sidecar:** `<file>.json` next to a file output (`<stem>.json` works too), or `output.json` inside a folder output. Every field is optional. `title`, `kind`, `main`, `preview`, `complete` and `created_ts` (unix seconds, for outputs copied in later) steer the index; everything else is shown as the output's metadata:

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
- **Text** (plan 24.2): the hub extracts the text of text and document outputs (`utils/outputs/text.py`: PDFs with `pypdfium2`, each page starting `--- page N ---`; docx, odt, epub, HTML and notebooks with the standard library; pptx and xlsx are left to the workspace sandbox) with page offsets, an outline (bookmarks, heading styles, `#` lines), a token estimate (chars / 4) and the PDF pages without a text layer. It is cached in `{outputs}/.text/<id>.json` (rebuilt when the file changes, warmed when the output is indexed) and cut at 4 M characters.
- **Deleting** an output from the UI moves it, with its sidecar and preview, to `outputs/.trash/<YYYY-MM-DD>/` (its cached text and page images are deleted); the hub empties trash days older than 30 days. Dotfiles and dot-folders are never indexed.

### 4.8 Adding a mod
1. Run `aihub new <id>`. It copies `services/_template/`, fills in the id, name and a free port, runs its `install.sh`, and asks the running hub to pick it up (`POST /api/services/rescan`). The mod appears in the sidebar, with an Overview tile, a working API tab and its Hello tab, and starts.
2. Edit `services/<id>/server.py` and `service.toml`, then `aihub restart <id>` (a code change) or `aihub rescan` (a manifest change, applied at the mod's next start).
3. A mod copied in by hand, or a folder deleted, is picked up the same way with `aihub rescan` (or a hub restart).

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
6. outputs (watch `outputs/`, with a background rescan of what changed while the hub was down)
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
aihub-stt.service                    stt (faster-whisper)     :5105  (+ its model's worker process)
```

`Ctrl+C` on `python app.py` stops only the hub; mods keep running. `aihub stop all` stops everything.

**Service states** (`utils/services.py`): `stopped → starting → ready ⇄ degraded`, with `failed` and `stopping`.
- **starting:** health is polled every 0.5 s up to `start_timeout_s`. A mod that exits, or never gets healthy (it is then stopped), goes to `failed` with the last 20 log lines in `last_error`.
- **ready:** health every 5 s. 2 misses → `degraded`; 5 misses → stopped and `failed`; the process exiting → `failed`.
- **failed:** `restart = "on-failure"` retries after 2 / 4 / 8 s, at most 3 times in 5 minutes, then gives up. A failure raises an alert and an activity item.
- **On boot:** running `aihub-*` units started from this root are adopted (`starting` until healthy); one whose folder is gone is stopped. Then enabled mods with autostart start in the background, each after the mods in its `after` list.
- **Settings changes while running:** a new port or env applies at the mod's next start. Until then, health checks and the proxy keep using the port the process was started with.
- **External mods** (`kind = "external"`): health only. Never reachable = `stopped`; reachable = `ready`; lost = `degraded`, then `failed`. Start and stop are refused (`external_service`).
- `python app.py --dev` runs mods as child processes instead of units; they stop with the hub.

## 6. Hub API

The UI-facing contract is **Section 6 of [design-brief-ui.md](design-brief-ui.md)**. These routes are backend-only additions:

| Route | Purpose |
|---|---|
| `GET /config.js` | sets `window.AIHUB_API_BASE = ""` and `window.AIHUB_LIVE_AREAS = [...]` (the areas whose backend exists), so the served UI is live area by area |
| `GET /` | `web/Hub.dc.html`, with `vendor/react*.js` and `/config.js` script tags added before `support.js` as it's served, so a fresh export works unchanged |
| `GET /ui/services/{id}/{path}`, `GET /Mod_<id>.dc.html` | a mod's `ui/` folder (page modules), and its `Page.dc.html` under a name `dc-import` can find |
| `GET /api/metrics`, `/api/metrics/series`, `/api/timeline`, `/api/outputs/stats`, `/api/activity/stats`, `/api/jobs/stats`, `/api/widgets`, `/api/widgets/{service}/{id}` | chart data; shapes in UI brief §11.7 |
| `POST /api/outputs/upload?name=` | a file sent as the body (image, video, audio, text or document, ≤ 64 MB) saved to `outputs/uploads/<date>/` and indexed; returns the `Output` (Chat's Upload, plan chat-uploads U.4) |
| `GET /api/outputs/{id}/file` | an output's main file (supports Range, for audio/video seeking) |
| `GET /api/outputs/{id}/files/{path}` | a file inside a folder output |
| `GET /api/outputs/{id}/preview` | thumbnail or poster |
| `GET /api/outputs/{id}/text?offset=&limit=&page=&pages=` | a window of a text or document output's extracted text, with its outline, page count and scanned pages (plan 24.3; `not_text` 409, `no_page` 404) |
| `GET /api/outputs/{id}/search?q=&limit=` | hits in that text: words in one line or paragraph, a `"phrase"`, or a `/regex/` run in a separate Python with a 1 s limit (`search_timeout`) |
| `GET /api/outputs/{id}/page/{n}.png?width=` | page `n` of a PDF, rendered by `pypdfium2`, cached under `outputs/.previews/<id>/` |
| `GET /api/events/recent?limit=` | recent activity, current alerts and running jobs (the activity, alerts and jobs parts of `GET /api/overview`, with a larger `limit`) |
| `GET /api/services/{id}/check[?start=1]` | the mod self-test behind `aihub check`: `{ok, checks: [{name, status: ok\|fail\|warn\|skip, ok, detail}]}` |
| `GET /api/doctor` | the checks behind `aihub doctor` and Settings → About → Doctor (plan 12.4): models on disk, manifests, paths outside the project (allowlist: `/usr`, `~/.config/tts-engines`, `~/.local/bin`, podman images; Stage D items are notes), ports, units, disk, offline mods. Shape: UI brief §11.7 `Doctor` |
| `POST /api/services/rescan` | pick up added, removed and edited mod folders without restarting the hub: `{added, removed, changed}`; new mods autostart |
| `POST /api/memory/acquire[?make_room=1]` | a mod asks for memory: `{service, needs_bytes, reason}` → `200 {granted, freed[], plan}` or `409 needs_room {plan}`. `make_room=1` (or `X-AIHub-Make-Room: 1`, or `auto_make_room`) unloads first; the grant is reserved for 120 s |
| `GET /api/tools[?q=][?names=]`, `GET /api/tools/index` | the agent's tool catalog (plan 13.1): every mod's `[tools]` and `tools_source` functions plus the hub's own `hub_*` tools, with risk, `ask` fields, examples and `core`; a stopped mod's tools stay listed (`available: false`; a call starts it) |
| `POST /api/tools/{name}/call {arguments, origin, mode}?wait=`, `GET /api/tools/calls/{id}[/result]`, `POST …/cancel` | a tool call (plan 13.2): validated (errors name the field and the fix), checked in §14.7's order (deny list → thread mode → the mod's own limits → grants → ask/allow lists → risk default), run as a hub task (jobs followed to the end; outputs mapped to `output:<id>`; JSON capped at 8 KB). Shapes: UI brief §11.12 |
| `GET /api/approvals`, `GET/POST /api/approvals/{id} {approve, arguments?, remember?, confirm?, grant_hours?}` | approvals (plan 13.2): a call that must ask is stored in `approvals` (hub.db) and runs nothing; the decision may carry edited arguments, which are validated and are what runs; `remember: thread \| always` also writes a grant (plan 25.2, §14.7) |
| `GET /api/grants[?thread=][?tool=]`, `DELETE /api/grants/{id}`, `DELETE /api/grants?thread=` | grants (plan 25.2, §14.7): what the user allowed in a chat or always, with revoke; the agent ends a chat's grants when it deletes the chat |
| `GET/POST /api/sessions`, `PUT/DELETE /api/sessions/{id}`, `POST /api/sessions/{id}/restore?dry_run=1`, `GET /api/sessions/state` | sessions (plan Phase 15): named snapshots, the restore plan (steps and memory) and its run through the memory manager; `state` reports an unclean last shutdown |
| `GET /api/skills`, `GET /api/skills/{mod}/{name}` | the mods' agent skills (plan 14.9) |
| `GET/POST /api/prefs`, `PATCH/DELETE /api/prefs/{id}`, `POST /api/prefs/{id}/approve\|reject` | preferences (plan 21.2, §14.5): saved only when they fit the tool's schema and choices; applied to every caller's card |
| `GET /api/doctor/inventory` | every path outside the project that anything uses, with its reason (plan 16.3) |
| `POST /mcp` | the agent's tools over MCP (plan 13.4; streamable HTTP, stateless, JSON responses; 2026-07-28 per-request `_meta` plus the 2025 `initialize` era). Annotations from `risk`; `ask` calls return `input_required` (an elicitation form of the ask fields) to clients that declare elicitation, else an explanation with `_meta["aihub/approval"]`; the MCP-only tool `aihub_wait_approval` waits for a decision (never approves). `GET`/`DELETE` → 405; a non-loopback `Origin` → 403. Claude Code: `claude mcp add --transport http aihub http://127.0.0.1:7000/mcp` |

**Alerts** (plan 6.4) are the banner items above the Overview grid. Each has a stable id, so it is raised once and cleared when its cause goes away:

| Alert id | Level | Raised when | Cleared when |
|---|---|---|---|
| `manifest-<id>` | error | a mod's `service.toml` is invalid, or its `config.toml` override clashes (found at boot, rescan or a settings save) | the manifest is fixed and rescanned, or the folder is removed |
| `svc-<id>` | error | a mod failed (crashed, failed to start, or stopped answering its health check) | it starts again, or is stopped |
| `models-missing`, `models-partial`, `registry-invalid`, `sum-<model id>` (a checksum mismatch) | warn/error | registry problems (§8) | the registry watcher sees them fixed |
| `disk-low` | warn (error under 10 GB) | the project's disk has under 50 GB free (checked every 10 s) | 55 GB or more is free |
| `memory-high` | warn | memory is over 92% used | it drops under 90% |
| `outputs-watch` | error | the outputs watcher stopped | it recovers |

**Error envelope:** every hub error is `{"detail": str, "code": str, "data"?: object}`, sent with an `X-AIHub-Error: <code>` header. Responses proxied from a mod are passed through unchanged (no header), which is how the UI tells a mod's error from the hub's. The proxy adds `X-Forwarded-Prefix: /api/s/<id>` (plus `X-Forwarded-Host` / `-Proto`) to each request, and rewrites a `Location` that points at the mod so redirects stay inside `/api/s/<id>`. The hub only produces `service_not_running` (503) or `upstream_error` (502) when it can't reach the mod at all. **WebSockets** pass through the same path (plan 29.2): messages both ways until either side closes, the mod's close code included. A page from another origin is refused at the handshake (403); otherwise a missing, stopped or unreachable mod is reported as a close code the browser can read (4404, 4503, 4502). An open socket counts as a request in flight.

## 7. Memory manager

**Sampling** (every 2 s):
- **System:** `/proc/meminfo` (`MemTotal`, `MemAvailable`).
- **GPU:** AMD sysfs `mem_info_gtt_*` / `mem_info_vram_*`.
- **Per mod:** the processes in its unit's cgroup, plus its `extra_units` and `containers`. A container's processes are its main pid plus everything in its `libpod-*` cgroup: `podman exec` processes (how a toolbox runs ComfyUI) aren't children of the main pid, and toolbox containers share the host's PID namespace. For each process, count PSS (from `smaps_rollup`, so pages shared by forked workers count once; RSS if it can't be read) plus GPU memory from DRM fdinfo (`drm-memory-gtt` / `vram`). This logic comes from lcpp's `proc.py`.
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

**Reservations:** planning and unloading happen under one lock, which isn't held while a mod loads (that can take minutes). Instead, each grant reserves its bytes, and other plans subtract what's still reserved. A reservation shrinks as the mod's measured use grows, and ends shortly after the load finishes (or when the mod unloads, or after 30 min / 120 s for acquire / 300 s for a trigger).

**Proxy triggers:** a trigger in `[memory] triggers` is `"METHOD /path"`, where `{name}` matches one path segment and a trailing `*` matches the rest. A matching call to an unloaded mod makes room first, then goes through (the mod loads itself). Without room it returns `409 needs_room` with the plan, and the caller retries with `X-AIHub-Make-Room: 1`.

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
- **`status`** (`ok` / `missing` / `partial` / `unverified` / `checksum_mismatch` / `verifying`) is computed when the registry is read, not stored:
  - `missing`: none of the files exists.
  - `partial`: some file is missing, has a different size than recorded, or is still downloading (`<file>.part`).
  - `checksum_mismatch`: verify found a file whose sha256 differs from the recorded one (it stores the new hash as `actual_sha256`).
  - `ok`: every file has a recorded sha256 and hasn't been modified since its `verified_at`.
  - `unverified`: anything else (no checksum yet, or changed since verification).
  - `verifying`: queued or being hashed; the Model then carries `progress` (0–1).
- **Robustness:** the hub reloads `registry.json` when it changes on disk. An entry it can't validate is reported and saved back unchanged; a file it can't read at all makes the registry read-only (`registry_invalid`) rather than being overwritten.
- **Deleting files** removes only the recorded files inside `data/models` (a symlink's target too when it lies inside the model's own folder, as hf-cache blobs do), then any folders left empty. It is refused with `model_in_use` while a mod using the model is running and loading, loaded, unloading or busy; a running mod with no `[memory]` section counts as loaded.
- **Who registers models:**
  - the scanner suggests entries and you confirm them
  - mods can register what they download (`POST /api/models` with their source)
  - lcpp's Hugging Face downloader does this first

## 9. `config.toml`

Sizes in GB (`reserve_gb`, a manifest's `estimate_gb`, a status's `memory_estimate_gb`) are decimal: 1 GB = 10⁹ bytes, as the UI and `aihub` show them.

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
density = "compact"         # or "comfortable"

[ui.dashboard]              # the Overview dashboard's Customize choices (written by the UI)
order = ["kpi", "memory-time", "memory-now"]
hidden = ["heatmap"]
ranges = { memory-time = "6h" }

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

[learning]               # plan 21–22: preferences on the cards, and the learner; Settings → Learning
enabled = true
nightly_at = "03:00"     # the learner's nightly run; it also runs after idle_min minutes without a chat
idle_min = 60
infer_after = 2          # an inferred preference is proposed after this many times, in as many chats
fade_days = 60           # inferred preferences unused this long fade out; stated ones never do
```

## 10. The existing apps as mods

| Mod | From | Port | Models | Databases | Changes inside the app |
|---|---|---|---|---|---|
| `tts` | `~/Projects/LocalTTS` | 5040 | `~/models/breeze-tts-2` → `data/models/tts/`; Kokoro and Whisper → `data/models/hf-cache` (copied); voices → `data/models/voices/` | — | status route, dated outputs + sidecars, `LOCALTTS_VOICES_DIR`, `save_dir` kept under outputs |
| `gen3d` | `~/Projects/3DGenerate` | 5050 | `~/Models/3D/CubeArt/weights/*` → `data/models/3d/` | `gen3d.db` → `data/databases/` | `GEN3D_DB`, `GEN3D_OUTPUTS`, `GEN3D_WEIGHTS` (+ container mount), per-job folder column, `output.json`, status route; image to 3D (plan 17): Hunyuan3D 2.1 and SAM 3D Objects in its own worker containers (one family at a time, memory acquired per engine), TRELLIS.2 and SAM 3D Body as `comfy` packs it runs through the hub |
| `relay` | `~/Tools/DashLLM` | 4000 | — | `relay.db` (+ `-wal`, `-shm`) → `data/databases/` | status route (KPIs) |
| `opencode` | DashLLM's `opencode.service` | 4096 | — | — | none: a manifest-only mod |
| `lcpp` | `~/Models/LLMs` | 7710 | `models/*` → `data/models/llm/` | — (its JSON state stays in `services/lcpp/data/`) | `LCPP_MODELS_DIR`, catalog paths relative to it, downloads register in the hub, memory acquire, status route, `pidfd_open` fallback |
| `comfy` | `~/Models/ComfyUI*` + `~/.local/bin/comfyui` | 5070 (ComfyUI 8199) | `~/Models/ComfyUI/models/*` → `data/models/comfyui/` | — | new adapter mod (§11) |
| `web` | new (plan Phase 26); searches through the SearXNG on 8080 that runs outside AIHub (`SEARXNG_URL`) | 5102 | — | — | new mod: `POST /v1/search`, `POST /v1/fetch` (pages → markdown `text` outputs, PDFs → `document` outputs, with sidecars); fetches only public http(s) addresses, checked after DNS and on every redirect, 10 MB / 20 s, `robots.txt`; tools `web_search` and `web_fetch` (risk `network`) |

**Moves are instant:** every source path and AIHub are on the same btrfs subvolume (`/home`), so `mv` is a rename, not a copy. Old paths keep a symlink until everything that uses them has been updated.

## 11. Later pieces

**comfy mod:**
- **The adapter:** a small FastAPI on 5070. Its load starts ComfyUI in the strix-halo toolbox (the existing `comfyui` script, moved into the mod), and its unload calls ComfyUI's `/free`. ComfyUI writes to `outputs/comfy` via `--output-directory` and reads models from `data/models/comfyui` via `extra_model_paths.yaml`.
- **Workflow packs:** each workflow is a folder `services/comfy/workflows/<id>/`, built the way mods are. It holds the ComfyUI editor file `workflow.json`, an optional exact API graph `workflow.api.json`, and an optional `workflow.toml` that names its task, its inputs (shared names such as `prompt`, `image`, `seed`, mapped to node fields) and presets. Adding, editing or deleting the folder applies without a restart. ComfyUI's workflows folder holds a symlink per pack (the adapter keeps them, and carries saves made in ComfyUI back into the pack), so packs open in ComfyUI, and workflows saved there under a new name become drafts. Plan Phase 11 has the format.
- **Not hand-exported:** the adapter converts editor files to API graphs itself using ComfyUI's `/object_info` (cached, so packs can be checked while ComfyUI is down). It drafts the inputs by tracing the graph, and checks for missing nodes and model files. Imports also take API JSON, ComfyUI history, and PNG/WebP/MP4 files with embedded workflows.
- **Running one:** `POST /v1/run {workflow, inputs}` acquires memory, patches the graph (including dated `filename_prefix` values), queues it, reports progress from ComfyUI's websocket, and writes a sidecar per result. Cancelling interrupts ComfyUI; an interrupt only lands between steps, so if the prompt is still running 90 s later the adapter unloads ComfyUI as stuck, and the next job starts it fresh.
- **Tasks:** `tasks.toml` defines tasks such as `text-to-image` and `image-to-video`. The agent gets one tool per task (`generate_image`, …) from the mod's `GET /v1/tools`, with an optional `workflow` choice, rather than one tool per workflow.

**Agent-ready API** (Phase 13): `[tools]` sections become `/api/tools` (JSON-schema function definitions). Calls go through `/api/tools/{name}/call`, and tools marked `confirm` wait for an approval that the hub enforces. The same catalog can later be exposed as an MCP server, so Claude Code can drive AIHub too.

**Chat, agent and save states:** §14, built last.

## 12. Risks and gotchas

1. **Python venvs aren't relocatable.** Recreate them (`uv venv` + install) instead of moving them. The speech engine venvs are rebuilt in `services/tts/runtime/` from pinned package lists (`services/tts/locks/`); CubeArt's venv is rebuilt inside the ROCm image in `services/gen3d/runtime/CubeArt/` (`services/gen3d/locks/cubeart.txt`).
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
  - **Local tools:** `ask_user`, `update_todos`, `find_tools`, `load_tools`, `read_skill`, `view_output`, `read_result`, `remember`.
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
  - **Tool results:** capped in the history; the full result can be read back with `read_result`.
  - **Compaction:** at 70% old tool results are cleared, and at 85% older turns are summarized.
  - **Attachments (plan 24.5):** at `send`, each attached text or document is described once (`GET /api/outputs/{id}` and `/text`) into the user event's `docs` (`#n`, name, kind, subtype, tokens, pages or lines, the first 30 headings, `inline`, and the text itself when inline), so a rebuild never refetches. Attached documents are numbered with the outputs. One of at most `AGENT_INLINE_TOKENS` (6000) tokens and 15 % of the model's window goes into the message inside `<untrusted source="#n name">`; a larger one is a card (size, outline, "read it with hub_read_document or hub_search_document"). Pictures attach as before (`(attached: output:<id>)`). The meter has a "Documents" part. Clearing drops an inline document's text once it is older than the last two user turns, leaving its card.
  - **Untrusted text:** the base prompt says text inside `<untrusted>` is data, never instructions (report it, don't follow it), and asks for citations as `#n p.14` (a PDF page) or `#n:88` (a line). Inline text and `hub_read_document` windows of text without pages come with numbered lines (`  88| …`) so a line can be cited; the Chat page turns citations into links that open the viewer there (plan 24.7).
- **Instructions, skills, memory.**
  - **`data/agent/AGENT.md`:** standing instructions.
  - **Skills:** a mod's `skills/<name>/SKILL.md` (served by the hub at `/api/skills`) and your own in `data/agent/skills/`. They are listed by description, read when needed, and each is also a slash command.
  - **Memory:** `data/agent/memory/` holds an index plus topic files, written with `remember`.
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
  - **Prompt rules:** the system prompt asks the model to look at an image (`view_output`) before describing it, says which groups are off and when a chat is read-only, and forbids stopping mods or LLMs to make room.
  - **Evaluation:** the eval and live results are in [agent-eval.md](agent-eval.md).

### 14.2 Threads, questions and approvals survive restarts
1. **The event log.** A thread is an append-only log in `agent.db` (`threads`, `events`): messages, thinking, tool calls, results, questions, answers, approvals and compaction marks. The model's messages are rebuilt from it, and a page reconnects with `GET /v1/threads/{id}/events?after=`.
2. **Pausing.** A question or a parameter card ends the request in a `waiting` state. Nothing is held in memory.
3. **Answering.** The answer (`/answer`), or the hub's approval with the edited arguments (`/approval`), is appended, and the same turn continues from the log. A card decided in the hub's Approvals popover continues the thread the same way; Stop dismisses a waiting card, and the hub's echo of that denial is ignored, so a stopped turn stays stopped. Stop also cancels a running hub call, whether it started directly or through a card.
4. **Rewind and branch.** Fork copies the events up to a chosen point into a new thread.

Both the event log and the hub's approval are on disk, so a reboot between steps 2 and 3 loses nothing.

### 14.3 Save states
- **Chats.** Threads, the step history behind **rewind and branch** (continue from any earlier checkpoint), and titles and search (agent mod's tables in `agent.db`).
- **Sessions.** The hub can **snapshot the current setup**: which mods are running and loaded, lcpp's instances with their launch settings, and ComfyUI's state. Each snapshot is saved under a name in `hub.db`.
  - **Restore** replays a snapshot through the memory manager, so it never overcommits memory.
  - Optionally, the last session is restored at boot. At each start the previous run's auto-saved "Last session" is copied to "Before restart", which the auto-save never overwrites; the boot restore and the unclean-shutdown offer use that copy (before this, an auto-save five minutes after a reboot replaced the setup worth restoring).
  - Named setups ("LLM work", "3D work") can be switched with one action.
- **Backups.** `aihub backup` (Phase 12.5) also covers `agent.db` and the session snapshots.

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
  5. gate on the eval (the area's tasks plus a core set; the full suite for always-on changes);
  6. adopt;
  7. keep one lesson per round in that area's library, which only the improver reads.
- **Who adopts what:** tool notes, skills and hooks are adopted automatically once the gate passes; prompt and guardrail changes wait for the user.
- **When it runs:** nightly, after `[learning] idle_min` without a chat, or on Learn now. It pauses while you chat.
- **Dry runs change nothing:** generating tools make stand-ins, and write and destructive tools return a stand-in success.

### 14.7 Permissions: risks, the order, grants (plan Phase 25)
- **Risks.** Every tool has one: `read`, `write`, `generate`, `network` (reaches the internet), `execute` (runs code or commands) or `destructive`. A mod declares it in `[tools]` (`risk = …`) or its `tools_source`.
- **The order** in which a call is decided is fixed (`utils/tools/approvals.py` `decide`); the first that answers wins:
  1. the **deny** list of `[agent.permissions]`;
  2. the thread's **mode**: `read_only` denies everything but `read`;
  3. a **mod's own limits** (a workspace folder's level, Phase 27): the mod enforces them when the call reaches it, so nothing below lifts them;
  4. a **grant** that covers the call allows it;
  5. the **ask** list, then the **allow** list (`execute` ignores the allow list: only a grant skips its card);
  6. the **risk default**: `read` runs; `write` and `generate` ask, or run in `auto` mode ("Use defaults"); `network`, `execute` and `destructive` ask in every mode.
- **Grants** (`utils/tools/grants.py`, table `grants`, migration 009): one answer that covers more than one call. Deciding an approval with `remember: "thread"` ("Allow in this chat") or `"always"` writes a grant `{tool, key, scope, thread, expires_ts}`; `once` (the default) writes none. `always` for `execute` and `destructive` needs a second confirm (`confirm: true`, else 422 `confirm_needed`); `thread` needs a call from a chat (else 422 `no_thread`).
  - **Keys.** A tool may declare `grant_key` in `[tools]` (or its `tools_source` item): `url:host` takes the host of its `url` argument (exact: `api.github.com` is not `github.com`), `arg:<name>` takes that argument as is (a folder), `const:<x>` is always `x` (every search). A grant covers a call of its tool whose key equals the grant's; a tool without a grant key gets grants that cover every call.
  - **Who.** A `thread` grant covers calls whose `origin.thread` is that chat; MCP and API calls have no thread, so only `always` grants apply to them. A call run by a grant carries `origin.grant`. `GET /api/grants` lists the live ones (Settings → Agent → Permissions, with revoke); expired ones are dropped; `thread` grants end when the agent deletes the chat (`DELETE /api/grants?thread=`).

### 14.4 Everything inside the folder
- **Logs.** Each mod's output is also written to `data/logs/<id>.log`, rotated. journald stays as a second copy, and the Logs tab reads the file.
- **Runtime state.** lcpp's instance records move from `$XDG_RUNTIME_DIR/lcpp` to `data/state/lcpp` via `LCPP_STATE_DIR`. Instances are still systemd units, so after a reboot they come back through session restore, not by adoption.
- **What's left outside.** `aihub doctor` then reports only the allowlist: the systemd unit file, podman images, system tools (ffmpeg, blender, podman), and the `~/.local/bin` wrappers.
- **As built (plan 16):** a shipper per mod follows the backend into `data/logs/<id>.log` (rotated 10 MB × 5) and the hub logs to `data/logs/aihub.log`; the Logs tab and `aihub logs` read the files. lcpp runs with `LCPP_STATE_DIR=data/state/lcpp` and forgets records from before the last boot. `aihub doctor --inventory` lists every outside path with its reason.
