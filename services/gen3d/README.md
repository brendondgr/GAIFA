# 3DGenerate

A chat-style web UI and HTTP API for local 3D asset generation on **http://127.0.0.1:5050**:

- **Cube3D v0.5** (Roblox): text prompt → 3D mesh
- **CubePart** (Roblox): mesh → up to 8 separate, named part meshes
- **Rig**: parts → a game-ready GLB with a motor joint and a telescoping slide per limb
- **Preview**: a Blender 4-view render of the result
- **From a picture** (plan 17): **Hunyuan3D 2.1** and **SAM 3D Objects** in gen3d's own worker,
  **TRELLIS.2** and **SAM 3D Body** through AIHub's Images & Video mod (ComfyUI). See [Image to 3D](#image-to-3d).

Jobs queue up and run one at a time on the GPU. Every job reports live progress, its place in
the queue and **when it will be done**, and keeps its files on the server. It runs in the
background as a systemd user service, and keeps nothing on the GPU while unused: the worker
stops after **10 minutes** without a job and starts again on the next one.

**Web UI: http://127.0.0.1:5050**: open it from the **3DGenerate** app launcher (it starts the service if
needed) or `gen3d open` · API docs: http://127.0.0.1:5050/docs

Built for an AMD Strix Halo (Radeon 8060S, gfx1151, ROCm) with the models set up in
`runtime/CubeArt` (see [Models](#models)).

## Web UI

A chat: describe an object, get a model back. Everything the API does is in it.

- **Generator control** (top right): always says whether the generator (the GPU worker holding
  Cube3D and CubePart) is **off**, **starting** (with a timer), **ready** (models loaded, and when it
  will stop on its own) or **generating**. **Start generator** loads the models now so the next job
  begins at once (~40 s the first time); **Stop** frees the GPU. You do not have to start it: the
  first job does. If the service itself stops answering, a red banner says so and the page
  reconnects when it is back.
- **Composer**: the prompt, then **stage toggles** (Shape · Parts · Rig · Preview), the **Parts**
  editor (up to 8 names, with templates: Chair, Character, Vehicle, Weapon, Creature), a **preset** (Low-poly · Fast · Balanced · Quality · Custom), the paperclip to **upload a mesh**
  (or drop one on the composer) and the sliders button, which holds **every setting**: Cube3D
  resolution, top-p / deterministic, seed, guidance, bounding box (with Cube / Tall / Wide /
  Chair / Flat aspects), graph engine; CubePart steps, resolution, guidance, seed, scheduler,
  timeshift, surface samples; rig height and faces per part. The parts editor and the settings
  menu stay open until you close them (× or Esc). The composer shows the estimate before you send
  ("≈ 5m 40s · ~18:12").
- **Job cards**: queue position and "starts in", then a countdown to **done at HH:MM**, one row per
  stage with a progress bar (GPT tokens 412/1024, diffusion step 31/50…) and the current
  substage. When done: the preview (click to enlarge), an **inline 3D viewer** (Rigged / Parts /
  Mesh tabs, wireframe, part chips that hide and show parts), the **motor panel** for rigged
  results (swing / lift / extend per limb, head, recline, poses, a "cycle motors" animation),
  stage timings, and downloads (each GLB, rig.json, or everything as a zip).
- **Follow-ups** on a card: **Split into parts** or **Rig it** continue from that result without
  regenerating it, **Re-split** tries other part names, **New seed** re-runs with the next seed,
  **Edit & resend** loads the request back into the composer.
- **Sidebar**: chats (kept on the server, so the API sees them too; click the title to rename),
  the **Queue** (every active job with start and done times; cancel from there), **Settings**,
  and the worker pill (GPU idle / Worker starting / Loaded: Cube3D + CubePart / Generating…).
- **Settings**: load or unload the models (unload frees the GPU at once), desktop notifications
  when a job finishes, auto-opening the viewer on the newest result, an API example, and deleting
  all history.

When a job finishes you get a toast, a `(1)` in the tab title if the tab is in the background,
and a desktop notification if you turned those on.

## Control

```
gen3d start | stop | restart     # manage the background service
gen3d status                     # service, GPU worker (models, idle timer) and queue
gen3d logs [-f] [N]              # service log (journalctl), worker lines included
gen3d enable | disable           # start at boot (enabled by install.sh)
gen3d load | unload              # start the worker and load both models now / free the GPU now
gen3d make "prompt" [opts]       # queue a job from the terminal (below)
gen3d jobs [N]                   # recent jobs with status and ETA
gen3d cancel ID                  # cancel a queued or running job
gen3d open [--load]              # start the service if needed and open the UI (--load: start the generator too)
gen3d launcher                   # (re)install the "3DGenerate" app-menu launcher (install.sh does this)
gen3d ui | url                   # open the web UI / print the base URL
```

The **3DGenerate** launcher in the app menu runs `gen3d open`; right-click it for *Start generator
(load models)*, *Stop generator (free the GPU)* and *Stop 3DGenerate*.

```bash
gen3d make "sci-fi loot crate with a hinged lid" --parts "lid, box, handles" --preset fast --wait
gen3d make "stylized knight in a T-pose" --parts "head, torso, left arm, right arm, left leg, right leg" --rig --wait
```

`make` options: `--parts "a, b"`, `--rig`, `--preset fast|balanced|quality`, `--seed N`,
`--res 7..9`, `--steps N`, `--bbox W H D`, `--deterministic`, `--chat ID`, `--no-preview`, `--wait`.

## API

Every job is a pipeline of optional stages that run in order:

| Stage | What | Needs |
|---|---|---|
| `shape` | Cube3D v0.5: prompt → `mesh.glb` | `prompt` |
| `parts` | CubePart: mesh → `parts/part_XX_<name>.glb`, `parts.glb` (coloured scene) | a mesh (this job's shape, the parent job's, or an upload) and `parts.parts` (1–8 names) |
| `rig` | parts → `rigged.glb` + `rig.json` | parts: this job's or the parent's |
| `preview` | Blender render of the newest result → `preview.png` | anything above |

### Create a job

`POST /v1/jobs` with JSON (every field and range: `GET /v1/options`):

| Field | Default | |
|---|---|---|
| `prompt` | `""` | what to make; required with the `shape` stage |
| `stages` | `["shape", "preview"]` | any of `shape`, `parts`, `rig`, `preview` |
| `preset` | none | `lowpoly` / `fast` / `balanced` / `quality`, applied under explicit values |
| `shape.resolution_base` | 8.0 | 5–9.5; mesh decode grid 2^n. 5–7 ≈ 1–3 s, 8 ≈ 25 s, 9 ≈ 200 s of decoding |
| `shape.target_faces` | none | decimate the mesh to about this many faces (e.g. 1000); none = full detail |
| `shape.top_p` | 0.9 | nucleus sampling; `null` = deterministic (the seed then does nothing) |
| `shape.seed`, `shape.guidance_scale` | 0, 3.0 | |
| `shape.bbox` | none | aspect `[W, H, D]`, Y up, e.g. `[1, 2, 1]` for something tall |
| `shape.fast_engine` | false | HIP-graph engine: same mesh, 2× memory, not faster on gfx1151 |
| `parts.parts` | `[]` | 1–8 names; left/right is the object's own (it faces +Z) |
| `parts.steps` | 50 | diffusion steps, ~2.45 s each (the same for 1 or 8 parts) |
| `parts.resolution_base` | 8.5 | 6–9.5; part mesh resolution (8.0 ≈ 55 s, 8.5 ≈ 72 s, 9.0 ≈ 94 s for 8 parts). 6 breaks thin-walled objects up; 7 is a safe low end |
| `parts.target_faces` | none | one budget for all parts together, split by surface area (every part keeps ≥ 24) |
| `parts.guidance_scale`, `parts.seed`, `parts.scheduler`, `parts.timeshift`, `parts.num_samples` | 7.5, 0, `dpm_solver`, 4.0, 128000 | |
| `rig.height_m` | 1.8 | scale the rigged model to this height; `null` keeps the mesh's units |
| `rig.faces_per_part` | 12000 | decimation cap per part |
| `rig.target_faces` | none | budget for the whole rigged asset (the limb split and rails add a few hundred faces) |
| `chat_id` | none | add to a chat; `"new"` starts one titled from the prompt |
| `parent_id` | none | continue from that job's mesh / parts |

The reply is the job (`201`), including `eta`:
`{queue_position, starts_in_s, eta_s, done_at, by_stage}`.

```bash
# text -> mesh -> 5 parts -> preview, in a new chat
curl http://127.0.0.1:5050/v1/jobs -H 'content-type: application/json' -d '{
  "prompt": "futuristic hover motorcycle with twin jet thrusters", "chat_id": "new",
  "stages": ["shape", "parts", "preview"], "shape": {"bbox": [0.8, 0.9, 2.0]},
  "parts": {"parts": ["main body", "front thruster", "rear thruster", "seat", "handlebars"]}}'

# split and rig an earlier result without regenerating it
curl http://127.0.0.1:5050/v1/jobs -H 'content-type: application/json' -d '{
  "parent_id": "j_1feb1d0d4b", "stages": ["parts", "rig", "preview"],
  "parts": {"parts": ["body", "left arm", "right arm", "left leg", "right leg"]}}'

# your own mesh (.glb .gltf .obj .ply .stl .off, up to 300 MB)
curl -F mesh=@chair.glb -F 'job={"stages": ["parts", "rig"], "parts": {"parts": ["seat", "backrest", "legs"]}}' \
     http://127.0.0.1:5050/v1/jobs/upload

# how long would it take right now (queue wait + its own stages), without queueing
curl http://127.0.0.1:5050/v1/estimate -H 'content-type: application/json' \
     -d '{"prompt": "x", "stages": ["shape", "parts"], "parts": {"parts": ["a"]}}'
```

### Track it

```bash
curl http://127.0.0.1:5050/v1/jobs/<id>                 # status, stages{state, sub, step, total, seconds}, eta, files
curl -N http://127.0.0.1:5050/v1/jobs/<id>/events       # Server-Sent Events: the job on every change
curl -N http://127.0.0.1:5050/v1/events                 # everything: job, worker, chat, deleted
curl 'http://127.0.0.1:5050/v1/jobs?status=queued,running'
```

Job `status`: `queued` → `running` → `done` | `failed` | `canceled`. Each stage has `state`
(`pending`, `running`, `done`, `failed`, `canceled`, `skipped`); a running one also has `sub`
(`worker.start`, `load.shape`, `shape.gpt`, `shape.decode`, `shape.post`, `load.parts`,
`parts.encode`, `parts.diffusion`, `parts.decode`, `rig`, `preview`) and `step`/`total` where
there are steps.

### Files and the rest

```bash
curl -O http://127.0.0.1:5050/v1/jobs/<id>/files/rigged.glb     # any file listed in job.files
curl -OJ http://127.0.0.1:5050/v1/jobs/<id>/download            # the whole job folder as a zip (+ job.json)
curl -X POST http://127.0.0.1:5050/v1/jobs/<id>/cancel          # queued or running; replies with the final state
curl -X POST http://127.0.0.1:5050/v1/jobs/<id>/retry -H 'content-type: application/json' -d '{"new_seed": true}'
curl -X DELETE http://127.0.0.1:5050/v1/jobs/<id>               # permanent (no trash)
curl http://127.0.0.1:5050/v1/chats                             # also POST, GET/PATCH/DELETE /v1/chats/<id>
curl -X POST 'http://127.0.0.1:5050/v1/load?models=shape,parts' # warm the models up
curl -X POST http://127.0.0.1:5050/v1/unload                    # free the GPU (?force=true cancels a running job)
curl http://127.0.0.1:5050/health
curl http://127.0.0.1:5050/v1/settings                          # PUT {"preview_device": "cpu"|"gpu"}: see Preview renders
```

Python:

```python
import requests, time
B = "http://127.0.0.1:5050"
job = requests.post(f"{B}/v1/jobs", json={
    "prompt": "ornate brass hanging lantern", "stages": ["shape", "parts", "preview"],
    "parts": {"parts": ["cap", "glass panels", "frame", "ring"]}}).json()
print("done at", time.strftime("%H:%M", time.localtime(job["eta"]["done_at"])))
while job["status"] not in ("done", "failed", "canceled"):
    time.sleep(5)
    job = requests.get(f"{B}/v1/jobs/{job['id']}").json()
open("lantern_parts.glb", "wb").write(requests.get(f"{B}/v1/jobs/{job['id']}/files/parts.glb").content)
```

### The rig

`rigged.glb` has a node chain per limb, so an engine script can drive each motor on its own:

```
asset_root
  base
  recline_joint                       rotate local X
    back                              torso / body (and anything that is not a limb or the head)
    head_joint -> head                rotate local X
    arm_L_joint -> arm_L_slide        joint: swing = local Z, lift = local X · slide: translate local +Y
    arm_R_joint, leg_L_joint, leg_R_joint (same)
```

Set `joint.rotation = rest * rotZ(swing) * rotX(lift)` and `slide.position.y = extend`. Axes, pivots
and limits are in each node's glTF `extras` and in `rig.json`. Limbs are found by part name
(`left arm …`, `right leg …`, `head …`, `strap …`, `base …`); a strap follows the limb it sits
on. The rig is built for limbed objects (chairs, characters, creatures); other parts ride on the body.

### Low-poly assets

Generated meshes are dense (Cube3D ~10–35k faces, CubePart hundreds of thousands per part set)
because they are carved from a 256–512³ grid. For game-ready low-poly assets, set a **face budget**:
the mesh is carved as usual, then collapsed (quadric edge collapse) to the budget while keeping its
silhouette. The **Low-poly** preset does it for the whole pipeline: resolution 7, 25 CubePart
steps, 1,000-face budgets for shape, parts and the rigged model.

Measured: a rigged 6-part character at 999 (shape) / 996 (parts) / 956 (rigged) faces in 3m 40s;
decimation itself takes 0.2–6 s. About 500 faces still reads well; around 250 shapes fall apart.
Lowering `resolution_base` is not a substitute (it is a power of two: 1–2 would be a 2–4³ grid),
but low values make decoding much faster: Cube3D at 5 still looks clean.

## Image to 3D

A job with `engine` set to an image engine makes its `shape` stage's mesh from one picture instead of a
prompt; parts, rig and preview then work as for Cube3D. The picture is an AIHub output (`"image":
"output:<id>"`, fetched from the hub) or a file sent to `POST /v1/jobs/image`. The job folder keeps it as
`input.png`, plus the cut-out every engine reads, `input_rgba.png`: alpha from the picture, else
everything that isn't near-white. A transparent or plain white background works best.

| Engine | Best for | Fast preset (the default) | Base preset | Runs in |
|---|---|---|---|---|
| `hunyuan21` | characters: the cleanest, watertight surface | 30 steps + FlashVDM: ~85 s warm, 110 s cold | 50 steps: ~320 s | gen3d (`runtime/img3d`) |
| `trellis2` | objects: the most faithful detail | shape 12 + refine 6: ~75 s character, ~235 s round object | 20 + 12 steps; `draft` = 512 only, ~30–55 s | comfy pack `trellis2-*` |
| `sam3d_objects` | the quickest full shape, rougher | distilled: ~50 s warm (objects only: characters lose detail) | Meta's 25 + 25 steps | gen3d (`runtime/sam3do`) |
| `sam3d_body` | a person's body (no clothes) as a rigged mesh | ~10 s | + hand refinement | comfy pack `sam3d-body` |

TRELLIS.2's time follows the object's surface area: a round vase has 3x the tokens of a thin character,
and its refine stage costs ~5x per step (`runtime/lab/RESULTS.md` §5).

**Fewer polygons:** `target_faces` in the engine's options (0 = the raw mesh, which is the default) writes
the reduced mesh as `mesh.glb` and keeps the raw one as `mesh_raw.glb`. Hunyuan3D and SAM 3D Objects
use quadric decimation (fast-simplification, < 1 s; 50k faces keeps the shape). TRELLIS.2 uses its
own remesh (512) + decimate (10–24 s, clean down to 50k); its raw mesh is too broken for a decimator
alone. SAM 3D Body's mesh is fixed (36,874 faces, rigged).

```bash
# a picture already in AIHub's outputs, the fast preset, 50k faces
curl -s localhost:5050/v1/jobs -H 'content-type: application/json' \
  -d '{"engine": "trellis2", "image": "output:<id>", "trellis2": {"target_faces": 50000}}'
# a picture from disk
curl -s localhost:5050/v1/jobs/image -F image=@vase.png -F 'job={"engine": "hunyuan21", "preset": "base"}'
```

`GET /v1/options` lists every engine with its presets and settings (`engines`). The local engines run
one container at a time with Cube3D's (`gen3d-worker-<family>-…`; switching stops the other) and ask
AIHub for their memory first (Hunyuan3D 14 GB, SAM 3D Objects 22 GB). TRELLIS.2 and SAM 3D Body stop
gen3d's worker, then run their pack in the comfy mod through the hub (`gen3d/comfy_engine.py`); comfy's
copies of the meshes go to the hub's trash, so each job shows once on the Outputs page. The engines
were measured on this machine first: `runtime/lab/` (gitignored; `RESULTS.md`, `report/`).

## How it works

```
browser / curl ──HTTP──> gen3d (FastAPI, .venv)  ──stdin/stdout JSON──> podman: cube_worker.py
                           │  SQLite queue, ETA,                        (ROCm image + CubeArt venv,
                           │  SSE, job files                             Cube3D + CubePart resident)
                           └── Blender (host) for previews
```

- **One worker**, started on the first job: `podman run -i` of `docker.io/kyuz0/amd-strix-halo-comfyui`
  (the same torch 2.13 / ROCm 7.14 build ComfyUI uses) with `runtime/CubeArt/.venv` layered
  on top. It loads Cube3D and CubePart when first needed and keeps them while jobs keep coming.
  **Unload = stop the container**, which returns every byte of GPU memory; it happens after
  `GEN3D_IDLE_UNLOAD_S` (600) without a job, on `gen3d unload`, or when a running job is canceled
  (a GPU call cannot be interrupted any other way). A stale worker left by a crash is removed at start.
- **Progress** comes from the worker replacing Cube3D's and CubePart's `tqdm` with a reporter,
  so there is a real step count for GPT tokens and diffusion steps.
- **ETA**: each stage is a list of substages. Their durations start from measurements on this
  machine, are replaced by the median of the last finished runs with the same settings, and a
  running substage uses its live step rate. Model loads count only when the model is not
  resident. Queued jobs add up the jobs ahead of them. In testing, a 5m 40s job finished 18 s
  after the time shown when it was sent.
- **Queue**: SQLite (`data/gen3d.db`), one job on the GPU at a time. A job interrupted by a
  restart goes back to the front and resumes at the stage it was in (finished stages are kept).
- **The GPU slot** (AIHub plan 31.3): a job takes AIHub's GPU slot (`gen3d/gpu_slot.py`) before its
  first stage and holds it across all its stages, the Blender preview included; memory is asked for
  after it. While another mod holds the slot the job stays `queued` with `stage: "waiting_gpu"`,
  `ahead` and `eta_s`, and Cancel stops the wait. TRELLIS.2 and SAM 3D Body get the job's lease in
  `X-AIHub-GPU-Lease`, so comfy runs them under it. Without AIHub the slot is skipped.
- **Files**: `data/jobs/<id>/` (`mesh.glb`, `parts/`, `parts.glb`, `rigged.glb`, `rig.json`,
  `preview.png`, `input.*`). Deletes are permanent.

## Performance (Radeon 8060S, gfx1151)

| Step | Time | Peak GPU memory |
|---|---|---|
| worker start | ~2 s | |
| load Cube3D / CubePart | ~11 s / ~20 s (+~25 s compile on the first CubePart run) | |
| shape, resolution 7 / 8 / 9 | ~62 s / ~86–100 s / ~270 s (GPT ~58 s at ~18 tokens/s, then decoding) | 10.5 GB |
| parts, 50 steps, 8 parts, resolution 8.5 | ~3.2–3.7 min (diffusion ~2 min, decoding ~70 s) | 37–46 GB (52 GB at 9.0) |
| parts, 25–30 steps, resolution 8.0–8.5 | ~2.2–2.8 min | ~37 GB |
| rig / preview | ~5–9 s / ~1–3 s | CPU |
| full pipeline (shape + 8 parts + rig + preview, cold worker) | **5m 40s** | |

Decoding runs marching cubes on the CPU (NVIDIA Warp has no ROCm backend), which is why higher
resolutions cost so much more. Fewer parts do not make CubePart's diffusion faster; it always
fills 8 slots.

## Models

3DGenerate uses what `runtime/CubeArt` holds (`GEN3D_CUBEART`; `scripts/install-runtime.sh` builds it, with the
exact packages in `locks/cubeart.txt`):

- `weights/`: `cube3d-v0.5/` (shape_gpt, shape_tokenizer), `clip-vit-large-patch14/`,
  `cubepart/` (multi_part_dit, vae), `Qwen3-VL-4B-Instruct/`, `Qwen-Image/transformer/config.json`
- `cube/`: the github.com/Roblox/cube clone (Cube3D and CubePart code)
- `.venv/`: Python packages layered on the ROCm image's torch (transformers 4.57.x, trimesh, …)

`python -m gen3d.doctor` (run by `install.sh`) checks all of it, plus podman, the image and Blender.
Nothing in this repo modifies them; `workers/rig.py` and `scripts/render_blender.py` are vendored
copies of CubeArt's scripts (the preview script since changed: see Preview renders).

## Install / reinstall

> **Under AIHub** this is the `gen3d` mod: `aihub install gen3d`, `podman pull` the ROCm image, `scripts/install-runtime.sh`, then the weights. Setup: [setup/cubeart.md](setup/cubeart.md), [setup/img3d.md](setup/img3d.md), [setup/sam3do.md](setup/sam3do.md). The steps below are the old standalone 3DGenerate install.

```bash
git clone git@github.com:brendondgr/3DGenerate.git ~/Projects/3DGenerate && cd ~/Projects/3DGenerate
./install.sh                # server venv + `gen3d` command + app launcher + boot service, then starts it
./install.sh --no-service   # no boot service (`gen3d start` runs it in the background)
```

Requirements: `uv`, `podman` with the ROCm image pulled, the CubeArt models, and optionally
Blender (for previews). Run the tests with `.venv/bin/python -m pytest` (they use a fake worker,
no GPU needed). `GEN3D_FAKE_WORKER=1` runs the whole service against the fake worker for UI work.

## Configuration

Edit `~/.config/gen3d/gen3d.env`, then `gen3d restart`:

| Variable | Default | |
|---|---|---|
| `GEN3D_PORT` | 5050 | |
| `GEN3D_HOST` | 127.0.0.1 | `0.0.0.0` exposes it to the network; there is **no auth** |
| `GEN3D_DATA` | `<repo>/data` | jobs database and job folders |
| `GEN3D_IDLE_UNLOAD_S` | 600 | idle seconds before the worker (and its GPU memory) goes away |
| `GEN3D_PRELOAD` | empty | `1` = start the worker and load both models when the service starts |
| `GEN3D_CUBEART` | `runtime/CubeArt` | weights, venv and upstream code |
| `GEN3D_IMAGE` | `docker.io/kyuz0/amd-strix-halo-comfyui:latest` | the ROCm image the worker runs in |
| `GEN3D_BLENDER` | `blender` | empty disables previews |
| `GEN3D_PREVIEW_DEVICE` | `cpu` | `cpu` renders previews with Mesa's software rasterizer (llvmpipe), `gpu` on the GPU (faster); a choice saved on the page wins; see below |
| `GEN3D_STATE_DIR` | `GEN3D_DATA` | where the page's settings live (`settings.json`); AIHub sets `data/state/gen3d` |
| `GEN3D_PREVIEW_MAX_FACES` | 300000 | meshes above this are simplified for the preview only (the saved mesh is untouched); 0 = never |
| `GEN3D_PREVIEW_TIMEOUT_S` | 180 | a preview render that runs longer is killed and the stage fails |
| `GEN3D_KEEP_ALIVE_S` | 330 | HTTP keep-alive; keep it above the browser's |
| `GEN3D_FAKE_WORKER` / `GEN3D_FAKE_SPEED` | empty / 20 | simulate the GPU, N× faster than real |

### Preview renders

`scripts/render_blender.py` draws the 4-view sheet with Blender's Workbench at 384 px a view (768 px
sheet; at most 512 a view), flat shading, no shadows or cavity. Workbench draws through OpenGL, so
**it uses the GPU even with `blender -b`** (`gpu`). With `cpu`, the default, Blender starts with
`LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe --gpu-backend opengl`, and the script refuses to render unless the GL context is llvmpipe/softpipe, so it never falls back to the GPU.
The switch is on AIHub's 3D Generate page, Create tab (**Preview renders: CPU (safer) / GPU
(faster)**), and in the API:
`curl -X PUT http://127.0.0.1:5050/v1/settings -H 'content-type: application/json' -d '{"preview_device": "gpu"}'`
(`GET` shows it; `null` forgets the choice). It is saved in `settings.json` in `GEN3D_STATE_DIR`
(`data/state/gen3d/` under AIHub, so `aihub backup` keeps it) and read for each preview, so it applies to
the next one without a restart: the saved choice, else `GEN3D_PREVIEW_DEVICE`, else `cpu`. The mod's
status shows it as **Previews**.
Meshes over `GEN3D_PREVIEW_MAX_FACES` are simplified in memory by vertex clustering (a Weld modifier at
diagonal/2000, /1000, /500, /250, the first that fits; /250 is about a pixel of a tile). Timings on
llvmpipe here (32 threads): a cube 1.3 s, 400k triangles 3.7 s, 1.3M 3.2 s, a 24.7M-triangle TRELLIS
mesh (370 MB) 54 s, down to 263k triangles (149 s without the clustering).
Blender runs with `--factory-startup --disable-autoexec` and imports only `.glb`, `.obj` and `.ply`;
a GLB whose buffers or images point at outside files (anything but `data:` URIs) is refused, as are
`.gltf`, `.stl` and `.off` uploads (split them with the parts stage first; its output is previewed).

## Troubleshooting

- **A job fails with "worker exited"**: the traceback is in `gen3d logs` (worker lines are there
  too). Out of memory is the usual cause when ComfyUI or an LLM is holding the unified memory at
  the same time: `comfyui stop`, `llamacpp-stop`, or lower `parts.resolution_base`.
- **The first CubePart job is slower** than the ETA said: torch.compile builds its kernels once
  (~25 s); the cache in `runtime/CubeArt/.cache` keeps them for later runs.
- **A part came back empty** (the card says "No geometry for …"): CubePart found nothing matching
  that name. Try another seed (**New seed**) or a more literal name; name only parts that exist.
- **"straps" (or another generic name) swallowed a frame or platform**: generic names absorb
  nearby thin structures. Rename, or split them into more specific parts.
- **The GPU stays busy after a job**: the worker keeps the models loaded for the idle window;
  `gen3d unload` (or Settings → Unload) frees it at once.
- **Port 5050 already in use**: set `GEN3D_PORT` in `~/.config/gen3d/gen3d.env`.
