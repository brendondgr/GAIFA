# 3DGenerate — build plan

A chat-style web UI and HTTP API for the Roblox **Cube3D** (text → mesh) and **CubePart**
(mesh → named parts) models already set up in `~/Models/3D/CubeArt`, plus the game rig step
(parts → articulated GLB). Structured like `~/Projects/LocalTTS`: a FastAPI server in a small host
venv, one GPU worker process started on demand and stopped when idle, a no-build web UI served by
the same server, a `gen3d` control command, a systemd user service and an installer.

Each step below ends in a commit. Steps are checked off here as they land.

## Decisions

| Topic | Choice | Why |
|---|---|---|
| Location | `~/Projects/3DGenerate`, private GitHub repo `brendondgr/3DGenerate` | requested |
| Port | **5050** on 127.0.0.1 + [::1] | 5040 = LocalTTS, 4000 = DashLLM, 7070 = llama.cpp, 8199 = ComfyUI |
| Server | FastAPI + uvicorn in `.venv` (uv, Python 3.12) | same as LocalTTS; the server never imports torch |
| GPU work | one **worker** process: `podman run -i` of the kyuz0 ROCm image with the CubeArt venv, JSON lines over stdin/stdout | the only torch stack that works on gfx1151 here; stopping the process frees all GPU memory |
| Model residency | Cube3D and CubePart load lazily inside the worker and stay loaded; the worker stops after `GEN3D_IDLE_UNLOAD_S` (600 s) idle | avoids an 8–20 s reload per job; memory comes back when unused |
| Queue | persistent SQLite (`data/gen3d.db`), one job on the GPU at a time, FIFO | jobs outlive browser reloads and server restarts |
| Pipeline stages | `shape` (Cube3D) → `parts` (CubePart) → `rig` → `preview` (Blender render) — each optional; a job can also start from an uploaded mesh or continue a previous job | covers text→asset, mesh→parts, and "split / rig this one" follow-ups |
| Progress | worker patches `tqdm` in Cube3D/CubePart to emit per-token / per-step events; other stages emit start/end | real progress bars without touching upstream code |
| ETA | per-stage model seeded from the CubeArt benchmarks (`logs/timings.jsonl`), refined by every finished job and by live step rate while running; queue ETA = jobs ahead + own | "tells us when it will be done" |
| Live updates | Server-Sent Events (`/v1/events`, `/v1/jobs/{id}/events`) | one-way, works through plain fetch, no websocket lib |
| Chats | stored server-side (`chats` table); each user message becomes a job linked to its chat | API clients and the UI see the same history |
| Files | `data/jobs/<id>/` — `mesh.glb`, `parts/…`, `parts.glb`, `rigged.glb`, `rig.json`, `preview.png`, `job.json`; zip download | self-contained per job; git-ignored |
| Rig code | vendored copy of CubeArt `scripts/rig.py` in `workers/rig.py` | repo only needs CubeArt's **weights, venv and upstream clone**, not its scripts |
| 3D in the browser | three.js 0.170 (GLTFLoader, OrbitControls) **vendored** under `web/vendor/` | works offline; inline viewer + rig sliders per job |
| Notifications | toast + tab-title badge + optional browser Notification when a job finishes | requested "tells us when it will be done" |
| Tests | pytest with a **fake worker** (`GEN3D_FAKE_WORKER=1`) that simulates stages in seconds | API/queue/ETA/UI can be tested without the GPU; one real GPU run at the end |

## API (target)

```
GET    /health                       service + worker state, queue length
GET    /v1                           info
GET    /v1/options                   every setting with type/default/range/help (drives the UI menu)
GET    /v1/presets                   fast / balanced / quality
POST   /v1/estimate                  ETA breakdown for a request, without queueing
POST   /v1/jobs                      create: {prompt, stages, shape{}, parts{}, rig{}, chat_id, parent_id}
POST   /v1/jobs/upload               create from an uploaded mesh (multipart) → parts/rig
GET    /v1/jobs                      list (?chat_id=&status=&limit=)
GET    /v1/jobs/{id}                 status, stage progress, ETA, files
POST   /v1/jobs/{id}/cancel          cancel queued or running job
POST   /v1/jobs/{id}/retry           re-queue with the same settings (optionally new seed)
DELETE /v1/jobs/{id}                 delete job + files
GET    /v1/jobs/{id}/files/{path}    any output file
GET    /v1/jobs/{id}/download        zip of the job folder
GET    /v1/jobs/{id}/events          SSE for one job
GET    /v1/events                    SSE for everything (UI)
GET|POST /v1/chats, GET|PATCH|DELETE /v1/chats/{id}
POST   /v1/load, /v1/unload          start / stop the GPU worker
GET    /docs                         OpenAPI
```

## Steps

### Phase 0 — scaffold
- [x] 0.1 Create repo dir, `git init`, `.gitignore`, this plan, README stub, `requirements.txt`, `gen3d.env.example`
- [x] 0.2 Create the private GitHub repo and push → **commit: "Plan and scaffold"**

### Phase 1 — service skeleton (mirrors LocalTTS)
- [x] 1.1 `gen3d/config.py` (env settings), `gen3d/__main__.py` (uvicorn on 127.0.0.1 + ::1, long keep-alive)
- [x] 1.2 `gen3d/server.py` with `/`, `/v1`, `/health`, static `/ui`, CORS for loopback origins
- [x] 1.3 `bin/gen3d` (start/stop/restart/status/logs/enable/disable/ui/url/serve), `systemd/gen3d.service`, `install.sh`
- [x] 1.4 Verify: `gen3d serve` answers `/health` → **commit: "Service skeleton, CLI and systemd unit"**

### Phase 2 — jobs, queue, ETA (fake worker)
- [x] 2.1 `gen3d/options.py`: request schema (pydantic), option catalogue, presets, validation (≤ 8 parts, ranges)
- [x] 2.2 `gen3d/store.py`: SQLite jobs + chats + timings, job folders
- [x] 2.3 `gen3d/eta.py`: per-stage estimator (seeded from CubeArt timings, learns from finished jobs, live rate)
- [x] 2.4 `gen3d/queue.py` + `gen3d/events.py`: FIFO runner task, cancel, SSE broadcast
- [x] 2.5 `gen3d/worker_fake.py` + all job/chat/estimate/file endpoints
- [x] 2.6 `tests/` for options, ETA, store and the API → **commit: "Job queue, ETA estimator, API and tests"**

### Phase 3 — real GPU worker
- [x] 3.1 `workers/cube_worker.py`: JSON protocol, lazy Cube3D/CubePart load, tqdm progress hooks, shape/parts/rig stages
- [x] 3.2 `workers/rig.py` (vendored) ; `gen3d/worker.py`: podman launch, ready handshake, idle unload, cancel = restart
- [x] 3.3 `gen3d/preview.py`: Blender 4-view render on the host (skipped if Blender is missing)
- [x] 3.4 Verify one real shape job and one parts job through the API → **commit: "GPU worker for Cube3D, CubePart and rigging"**

### Phase 4 — web UI
- [x] 4.1 Layout: sidebar (chats), thread, composer, top bar with worker state + queue
- [x] 4.2 Settings menu: stage toggles, presets, every Cube3D / CubePart / rig option, parts chip editor, bounding box, mesh upload
- [x] 4.3 Job cards: queue position, per-stage progress, ETA + "done at", cancel/retry/continue, notifications
- [x] 4.4 Inline 3D viewer (three.js, vendored) with part colours and rig motor sliders; downloads
- [ ] 4.5 Settings dialog: worker load/unload, idle note, notifications, delete history
- [ ] 4.6 Verify in the browser against the fake worker → **commit: "Web UI"**

### Phase 5 — end-to-end on the GPU
- [ ] 5.1 Full chat run: prompt → shape → parts → rig → preview; compare ETA with the actual times, tune
- [ ] 5.2 Follow-up (split / rig an existing result), cancel mid-run, restart server mid-queue
- [ ] 5.3 Fix what breaks → **commit: "End-to-end fixes"**

### Phase 6 — docs and install
- [ ] 6.1 README: UI tour, API reference with curl + Python, CLI, config, performance, troubleshooting
- [ ] 6.2 Run `install.sh` (venv, `gen3d` command, service), final check → **commit: "Docs and installer"**, push
