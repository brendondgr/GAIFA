# Writing an AIHub mod

A **mod** is a program with an HTTP server on `127.0.0.1`, plus a `service.toml` describing it, in a folder under `services/`. AIHub starts it, watches its health, shows its logs, proxies its API at `/api/s/<id>/…` and builds UI for it. AIHub never imports a mod's code, so a mod can be in any language, and adding one never needs a hub change.

This page is the how-to. The reference is [architecture §4](architecture.md#4-the-mod-contract) (manifest, placeholders, ports, status, outputs).

## 1. The contract

**Required:**
1. A folder `services/<id>/` with a `service.toml`. `<id>` is 2–32 lowercase letters, digits and `-`, starts with a letter, and equals the `id` field. It becomes the URL (`/api/s/<id>/`, `#/s/<id>`), so choose it once.
2. A server on `127.0.0.1:$AIHUB_PORT`. Read the port from the environment; don't hard-code it.
3. A health route that answers 2xx once the mod is ready (`health = "/health"`), or `health = "tcp"` for programs with no HTTP health route.

Deleting the folder removes the mod; run `aihub rescan` (or restart the hub) afterwards.

## 2. The loop

```bash
aihub new my-mod            # copy services/_template, pick a port, install, load it
$EDITOR services/my-mod/server.py services/my-mod/service.toml
aihub restart my-mod        # after code changes
aihub rescan                # after service.toml changes or adding/removing folders
aihub check my-mod          # what's wrong, exactly (add --start if it's stopped)
aihub logs my-mod -f
```

`aihub new` options: `--name "My Mod"`, `--port 5123` (default: the first free port in `config.toml [ports] new_mods`, 5100–5199), `--no-install`. The template's `install.sh` makes `.venv/` with uv (uv-managed Python, so it works on the host and in a toolbox); rerun it with `aihub install my-mod`.

**Done means `aihub check my-mod` prints "all checks passed".** It checks the manifest, the command, the port, health, the OpenAPI, every operation the manifest names, the status shape, each widget's data and the page module.

## 3. `service.toml` in practice

```toml
id = "my-mod"
name = "My Mod"
description = "One line for the tile"
icon = "puzzle"                     # a key from the UI's icon set
version = "0.1.0"

[run]
command = [".venv/bin/python", "server.py"]   # or a string: "bin/server --fast"
port = 5123
health = "/health"                  # or "tcp"
status = "/v1/status"               # optional, §5 below
openapi = "/openapi.json"           # the API tab; set to "" (or remove) if you have none
env = { MY_MOD_OUT = "{outputs}", MY_MOD_PORT = "{port}" }
env_file = ".env"                   # optional secrets, gitignored; not placeholder-expanded
start_timeout_s = 60                # how long health may take after launch
stop_timeout_s = 30                 # SIGTERM → wait → SIGKILL
restart = "on-failure"              # retries after 2/4/8 s, at most 3 per 5 min; or "no"
after = ["relay"]                   # start after these (ordering only)
# installed = ["~/.opencode/bin/opencode", "opencode"]   # optional: what exists once it's set up, any one (default: the command's first word)
```

- **Installed:** until a mod's command exists (its venv, binary), the hub shows it as "not installed" and doesn't autostart it. A mod whose command is a tracked script (opencode's `./run.sh`) names what its setup makes in `installed` (a path, `~/…` or in the mod folder, or a command on the hub's `PATH`; a list means any one). A hub running older code rejects the key as unknown: `aihub restart` after pulling.

- **Paths in `command`:** an executable containing `/` resolves against the mod folder (`.venv/bin/python`); a bare name (`python3`, `node`) comes from `PATH`. Arguments starting with `./` or `../` resolve against the mod folder; others are passed as written and are relative to `cwd`, which is the mod folder by default.
- **Unknown keys are errors**, so a typo like `helth` is reported rather than ignored.
- **Placeholders** in `command`, `cwd` and `env` are `{root}`, `{service_dir}`, `{port}`, `{models}`, `{outputs}`, `{databases}`, `{hf_home}` and `{hub_url}`. An unknown `{name}` is an error.
- **Every mod gets** `AIHUB_PORT`, `AIHUB_OUTPUTS`, `AIHUB_MODELS`, `AIHUB_DATABASES`, `AIHUB_ROOT`, `AIHUB_URL`, `AIHUB_SERVICE_ID`, `HF_HOME` and `PYTHONUNBUFFERED=1`. Later layers win: hub vars → `env_file` → `[run].env` → `config.toml [services.<id>].env`.
- **Users override** `port`, `env`, `enabled`, `autostart`, `idle_unload_s`, `auto_unload` and `priority` in `config.toml` or the mod's Settings tab, without touching your manifest.

## 4. How it runs

- **Where it runs:** each mod is a systemd user unit, `aihub-<id>.service`, so it outlives hub restarts and the hub adopts it again. Logs go to `data/logs/<id>.log` (`aihub logs <id>`). Without systemd (macOS) it's a detached process with a pidfile, adopted the same way (`[hub] backend`, plan 37.1). With `python app.py --dev`, mods are child processes instead and stop with the hub.
- **States:** stopped → starting (health polled every 0.5 s) → ready. Health is then checked every 5 s: 2 misses mean degraded, 5 mean failed. Exiting means failed, and `last_error` holds the last 20 log lines. A failed mod raises an alert and an activity item.
- **Stopping:** SIGTERM goes to the main process. Handle it and exit; after `stop_timeout_s`, everything in the unit gets SIGKILL, child processes included.
- **The port must be free.** If something else holds it, the start fails with `port_in_use` and names the process.
- **External services** (`kind = "external"`, no `command`): something already running elsewhere, such as a container or another machine's tunnel. AIHub only health-checks and proxies it.

## 5. UI: four levels, each optional

**Level 0: nothing.** Every mod gets a page with Overview (health, memory, models, outputs), **API** (built from your OpenAPI: forms for parameters and bodies, the right viewer for audio/image/video/3D/files/streams), Logs and Settings tabs.
- FastAPI apps get this for free.
- For responses FastAPI can't type, add `[api.responses] "POST /v1/speech" = "audio"`.
- Hide routes with `[api] hide = ["GET /ui/*"]`; entries are globs on `"METHOD /path"`.

**Level 1: a status route.** It returns this (architecture §4.6):
```json
{"loaded": null, "busy": false, "idle_s": 12.0,
 "stats": [{"label": "Calls", "value": 3}, {"label": "Notes today", "value": 1, "reset": "daily"}],
 "jobs": [{"id": "j_1", "label": "fox", "progress": 0.4, "state": "running", "route": "#/s/my-mod/jobs"}]}
```
- Up to 4 stats show on the mod's tile, and numeric ones are charted over time automatically.
- `jobs` appear in the header's jobs chip. Report finished jobs with their final state: `done`, `failed` or `cancelled`.
- AIHub polls every 2 s while you're busy, loading or running jobs, otherwise every 10 s.

**Level 2: dashboard widgets.**
```toml
[[ui.widgets]]
id = "calls"
title = "Calls per hour"
kind = "bar"                        # line | area | bar | donut | number | table
source = "GET /v1/widgets/calls"    # gets ?range=24h (the first of `ranges`)
ranges = ["24h", "7d"]
span = 4                            # of 12 grid columns: 3, 4, 6 or 12
```
The source returns `WidgetData`: `{"unit": "calls", "t": [unix…], "series": [{"name": "Calls", "values": [1, null, 3]}]}`.
- Use `categories` instead of `t` for donuts and categorical bars.
- Use `rows: [{…}]` for `table`.
- Each series has one value per point. `aihub check` validates all of this; the Overview dashboard draws widgets from Phase 6.

**A logo.** Put a 24×24 SVG at `ui/logo.svg` (or name another `.svg`, `.png` or `.webp` in `ui/` with `[ui] logo`). The sidebar, the Services page, the Overview tiles and the service header show it, with the mod's state as a dot in the thin rail; a mod without one gets a monogram. Every installed mod has its own (`utils/tests/services/test_logo.py` checks that no two are the same file); `aihub new` copies none.

**Level 3: your own tabs.** `[ui] page = "ui/page.js"`:
```js
export default {
  tabs: [{ id: 'hello', label: 'Hello' }],
  mount(el, ctx) {
    const { ui } = ctx;
    if (ctx.service.state !== 'ready') { el.append(ui.empty('Not running', '', ui.button('Start', () => ctx.api.startService(ctx.service.id), { kind: 'primary' }))); return; }
    const out = ui.h('div');
    el.append(ui.card(ui.button('Call', async () => out.replaceChildren(ui.json((await ctx.call('GET', '/v1/hello', { query: { name: 'you' } })).json)), { kind: 'primary' }), out));
    return () => {};                // optional cleanup (timers, listeners)
  },
};
```
`ctx` provides:

| Field | What it is |
|---|---|
| `service` | this mod's summary, kept fresh |
| `tab`, `params` | the current tab id and the hash parameters |
| `call(method, path, {query, json, form, stream, onEvent, signal})` | your own API through the hub; resolves to `{status, ms, json \| text \| url}` |
| `api` | the whole AIHub API (`startService`, `listOutputs`, …) |
| `ui` | themed DOM helpers: `h`, `text`, `row`, `stack`, `card`, `button(label, onClick, {kind})`, `input`, `textarea`, `select`, `field`, `json`, `badge`, `empty`, `table` |
| `toast(msg, level)`, `confirm({title, body, danger})` | the shell's toasts and confirm dialog |
| `navigate(route)` | change the hash route |
| `on(type, fn)` | AIHub events (`'service'`, `'job'`, `'output'`, … or `'*'`); removed automatically on unmount |

Rules for page modules:
- Never call `fetch`; use `ctx.call`, which also works against the mock.
- Use `ctx.ui` or the theme variables (`var(--card)`, `var(--mut)`, …) rather than raw colors.
- Show a Start button when the mod isn't running.
- Tab ids can't be `overview`, `outputs`, `api`, `logs` or `settings`.

After editing `page.js`, reload the browser tab. A page can also import `/mod-kit.js` (the Start button state, calls that may need memory, a segmented control, panels), `/mod-form.js` (`schemaForm`: a form from a JSON Schema, with file inputs) and `/mod-charts.js` (the dashboard's charts as DOM elements: `chartCard({title, ranges, load, draw})`); `services/tts/ui/page.js` uses both. `/chat/chat-md.js` is the chat's safe Markdown renderer (`renderMarkdown`, `MD_CSS`, `installCopy`); `services/web/ui/page.js` uses it. Pages for the built-in apps can instead be Claude Design components (`ui/Page.dc.html`; brief §5).

## 6. Outputs, memory, models, tools

- **Outputs:** write to `$AIHUB_OUTPUTS/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext>`.
  - Write `<name>.part` first, then rename it.
  - Add an optional `<file>.json` sidecar: `{title, kind, prompt, model, voice, seed, params, source}`.
  - A multi-file output is a folder with `output.json`: write it with `"complete": false` first and set `"complete": true` when done. A folder without `output.json` is just a folder (each file in it is an output).
  - Sidecars may set `created_ts` (unix seconds) for outputs copied in later; the time otherwise comes from the date folder and the `HHMMSS-` prefix.
  - Declare `[outputs] kinds = ["audio"]`. New files appear on the Outputs page within about 2 s, and in the activity feed.
- **Memory:** for mods that hold models in RAM or VRAM, declare:
  ```toml
  [memory]
  estimate_gb = 9.2
  load = "POST /v1/load"
  unload = "POST /v1/unload"
  triggers = ["POST /v1/speech"]
  ```
  - The Load and Unload buttons call these routes. Before a load, AIHub makes room by unloading idle mods (asking first unless `auto_make_room` is on).
  - Report `loaded` in your status (and `memory_estimate_gb` if what you need varies).
  - A proxied call to a `triggers` route while you're unloaded makes room first. `{id}` matches one path segment, a trailing `*` the rest. Without room the caller gets `409 needs_room`, and can retry with `X-AIHub-Make-Room: 1`.
  - If what you load varies (a model picked per request), ask first: `POST $AIHUB_URL/api/memory/acquire` with `{"service": "<id>", "needs_bytes": N, "reason": "gemma-4"}` → `{granted, freed}` or `409 needs_room`. On a machine with a dedicated GPU, put the model's VRAM in `vram_bytes` (and `vram_gb` in `[memory]`), its RAM in `needs_bytes`: each is checked against its own budget (plan 36.2); where the GPU shares the RAM the two add up.
  - Unload yourself when idle: `idle_unload_s = 180` and `idle_unload_env = "MYMOD_IDLE_UNLOAD_S"` in `[memory]`. AIHub passes the user's setting in that variable and in `AIHUB_IDLE_UNLOAD_S`, in seconds, where **0 means never**.
  - Your memory is measured, not declared: PSS (each shared page split between the processes that share it) plus GPU memory of every process in your unit, `extra_units` (globs, e.g. `"lcpp-*.service"`) and `containers`.
- **Models:** keep weights in `data/models/` (`$AIHUB_MODELS`), in the folder for their kind (`llm/`, `tts/`, `comfyui/<role>/`, …; architecture §3).
  - `[models] dirs = ["tts"]` (or deeper, `"comfyui/loras"`) lists the folders you use. Registered models in them show "used by" your mod, appear on its page, and their files can't be deleted while it is loaded or busy (or running at all, if it has no `[memory]`).
  - **Register what you download** so it shows on the Models page with its source: `POST $AIHUB_URL/api/models` with `{"path": "tts/my-model", "name": "My Model", "kind": "tts", "source": {"type": "huggingface", "repo": "org/name", "revision": "<commit>"}}`. The hub finds the files with the scanner's rules (or send `"files": [{"path", "role", "sha256"}]`). A file that's already registered answers `409 model_exists`, so registering again is harmless.
  - Download to `<name>.part` and rename when done; the registry shows a `.part` as downloading, and the scanner skips it.
  - Or let the user find it: `aihub models scan --add`, or **Scan for new files** on the Models page.
- **Tools** (the agent's, plan Phase 13): `[tools] speak = { op = "POST /v1/speech", description = "…", risk = "generate", ask = ["name"] }` exposes an operation as the tool `<mod>_<name>` (a `-` in the id becomes `_`). Its parameters are the operation's path and query parameters plus its JSON or multipart body, merged into one schema from your OpenAPI. Fields:
  - `description`: written for the model: what it does, what to pass, what comes back (else the OpenAPI summary).
  - `risk`: `read` (runs without asking), `write`, `generate`, `network` (reaches the internet), `execute` (runs code or commands) or `destructive`. Each but `read` shows the user a parameter card first; "Use defaults" skips it only for `write` and `generate`. Default: `read` for GET, `destructive` for DELETE or `confirm = true`, else `write`. The full order (deny list, mode, your own limits, grants, lists, risk) is architecture §14.7.
  - `grant_key`: what one "Allow in this chat" or "Always allow" covers (plan 25.2): `"url:host"` (the host of the `url` argument: allowing github.com doesn't allow example.com), `"arg:<name>"` (that argument as is, e.g. a folder) or `"const:<word>"` (every call, e.g. `"const:search"`). Without one, a grant covers every call of the tool. `aihub check` reports a key that names a parameter the tool doesn't have.
  - `dry_run = true`: in a dry run (the agent eval), the call still goes to your mod, which sees `"dry_run": true` in the `X-AIHub-Origin` header's JSON and answers without its side effects (the web mod answers from its fake web). Without it, a dry run of a `write`, `network` or `destructive` tool returns a stand-in success and never reaches the mod; `generate` tools get a stand-in output.
  - `cap_kb`: results are kept whole for the model up to this many KB (1–256, default 8); larger ones are cut to a preview the agent pages through. Reading tools that return text (the workspace mod's `read`, 64) raise it.
  - `ask = ["voice", …]`: the inputs the user should choose; they're editable on the card even when the model filled them in.
  - `examples = [{…}]`: one or two example argument sets (they raise accuracy on complex parameters).
  - `core = true`: always loaded in the chat; other tools are listed by name and loaded on demand.
  - `hide = ["stream"]` keeps a parameter from the model (your default applies); `fixed = { stream = false }` always sends a value.
  - `job = true` with `job_status = "GET /v1/jobs/{id}"` (and optionally `job_cancel`): the call returns a job id, and the hub follows the job until its `state`/`status` is done, failed or cancelled, then returns its outputs. A `progress` (0–1) or `stages` field becomes the card's progress bar. Of the finished job's body the model sees `id`, `state`/`status`, `title`/`label`, `error`, `outputs`, `files`, `dir`, `seconds`, `peak_gb` and `transcript` (stt's text with `[mm:ss]` marks); put anything else it needs in one of those.
  - **Results:** any path under `outputs/` in your JSON (absolute, `<mod>/<date>/…` or `<date>/…`) becomes an output reference (`output:<id>`) the agent can chain. For a binary response, send the saved file's path in an `X-AIHub-Output` header; otherwise the hub saves the bytes itself.
  - **File inputs:** a schema property with `format: "aihub-file"` (a JSON value) or `format: "binary"` (multipart) gets `x-kind` (image, video, audio, mesh), and takes `output:<id>`: JSON bodies get the string, multipart bodies get the file.
  - **Choices that depend on the inputs:** put `x-options` on an `enum` property (in your pydantic model, `json_schema_extra={"x-options": {…}}`), one entry per value: `needs` / `excludes` (parameters that must or mustn't be given for it), `default` (used when the model leaves it out, among the choices that fit), `label`, `good_for`, `speed`, `kind`, and `allows: {"preset": […]}` for a property that says `"x-depends-on": "engine"`. The hub fills the default, refuses a choice that doesn't fit with a `fix` naming the ones that do, renders the choices into the description the model reads, and the parameter card lists only the ones that fit. `aihub check` reports unknown values, unknown parameters and two defaults that fit the same inputs. Shape: brief §11.12.
  - **Your own fix:** a 4xx body with `fix` (at the top, under `data`, or in a dict `detail`: `{"detail": {"detail": "…", "fix": "…"}}`) reaches the model as the call's `fix`; `problems: [{field, detail, fix}]` too.

  A mod whose tools change while it runs (comfy's grow with its workflow packs) lists them from a route instead: `[agent] tools_source = "GET /v1/tools"`, returning `{"tools": [{"type": "function", "function": {name, description, parameters}, "op": "POST /v1/tools/<name>/call", "job": {"status": "GET /v1/jobs/{job_id}", "cancel": "…"} | null, "risk": …, "ask": […], "examples": […], "core": …, "grant_key": …}]}`. ComfyUI workflows are themselves modular: see [workflows.md](workflows.md).
  A mod whose tools act on things with their own permissions (the workspace mod's folders) adds a **preflight**: `[agent] limits = "POST /v1/limits"`. Before deciding any of its calls the hub posts `{tool, arguments, origin}` there and reads `{action, folder?, level?, allow_bypass?, key?, once?, preview?, refuse?}`: `action` is one of `read`, `edit`, `delete`, `commit`, `command`, `network`, `host`, `remote` and the chat's mode decides it by architecture §14.7's table; `refuse: {code, detail, fix}` ends the call in every mode; `key` replaces the grant key; `once` means it asks every time (no grants); `preview` (`{summary, diff}` or `{command, where, network}`) is shown on the card. A preflight that fails or doesn't answer refuses the call. The mod still checks its own limits when the call arrives.

**Variants: one mod, several accelerators** (plan 38). A mod that runs on more than one kind of GPU declares a `[[variants]]` entry per accel in its setup doc (§9). The hub then passes the one installed as `AIHUB_ACCEL` and `AIHUB_DEVICE`. In Python, `device()` from `services/_template/device.py` gives the torch device (falling back to whatever torch reaches), and `torch_index.py <accel>` the PyTorch wheel index; the template's `install.sh --accel <accel>` installs `requirements-torch.txt` from it. Set per-variant env in `service.toml` with `[run.variants.<accel>] env = {…}`.

**Containers with the GPU** (plan 37.4): a mod that runs its engine in podman or docker copies `services/_template/containers.py` unchanged and builds its command as `[runtime(), "run", *gpu_args(hardware(), runtime()), image, …]`. `gpu_args` gives each vendor's flags from `GET /api/system/hardware`: AMD's `/dev/kfd` and `/dev/dri`, NVIDIA's CDI device (podman) or `--gpus` (docker), Intel's `/dev/dri`, WSL2's `/dev/dxg`, and SELinux's `label=disable` only where it's enforcing. It narrows to `AIHUB_GPU_INDEX` when the hub picked a GPU, and is empty on macOS and without a GPU. `runtime()` reads `AIHUB_CONTAINER_RUNTIME`, which comes from `[containers] runtime` (default auto: podman, else docker).

**Taking the GPU** (plan 31): add `[gpu] class = "job"` (or `interactive`, `background`; `group` to share the slot with your own other requests) and copy `services/_template/gpu_slot.py` into your package unchanged. Wrap the GPU work: `async with gpu_slot(label, est_s=…, on_wait=…) as lease:`, slot first, then `/api/memory/acquire`. While it waits, show the job as `state: "queued", stage: "waiting_gpu", ahead, eta_s` (from `on_wait`) in your job route and `/v1/status`. A job mod answers its submit at once and waits in the background; Cancel cancels the waiting task (the client releases). Pass `lease.headers` to a mod you hand part of the work to; the receiver passes `lease_from(request.headers)` as `parent=`. Long background work takes one short lease per batch, never a second lease while holding one. `GpuCancelled` means the queue's Cancel dropped it. Without a hub, the work runs at once. `aihub check` warns about a `[memory]` mod without `[gpu]`.

## 7. Bringing in an existing app

1. **Pick the id and port.** Existing apps keep their ports (architecture §2); new ones use 5100–5199.
2. **Make it read its port** (and output folder) from the environment, mapping in `env`: `env = { APP_PORT = "{port}", APP_OUT = "{outputs}" }`. If it can't, write `{port}` into its arguments in `command`.
3. **Health:** use any cheap route that answers 2xx when it's ready, or `"tcp"`.
4. **Python apps:** create a venv inside the mod folder (an `install.sh` like the template's). Point `command` at `.venv/bin/python`, and don't resolve or copy that symlink.
5. **Already running elsewhere** (a container, ComfyUI in a toolbox): use `kind = "external"` with just `port` and `health`, or write a small adapter mod in front of it, like `comfy`.
6. **Check it:** `aihub rescan`, then `aihub check <id> --start`.

## 8. When `aihub check` fails

| It says | Fix |
|---|---|
| `[run].helth: unknown key` | a typo; compare with §3 |
| `[run].port … already used by X` | pick another port, or override it in `config.toml [services.<id>] port` |
| `.venv/bin/python not found (run aihub install <id>?)` | `aihub install <id>` |
| `unknown placeholder {output}` | the placeholders are `{outputs}`, `{models}` … (§3) |
| `port 5123 is in use by <process>` | stop that process, or change the port |
| `not healthy after 60s (/health HTTP 503)` | the app is slow or broken: `aihub logs <id>`; raise `start_timeout_s` if it is just slow |
| `exited with status 1 while starting` | the traceback is in the check output and in `aihub logs <id>` |
| `operations: not in the OpenAPI: [tools].x: POST /v1/x` | the route doesn't exist (or isn't in `/openapi.json`) |
| `tools: x: engine: 2 defaults (a, b) fit when image is given` | give each input combination one `default` in `x-options` (§6, Tools) |
| `status: stats[0] needs a non-empty label` | fix the status body (§5, level 1) |
| `widget calls: series[0] (Calls): 23 values for 24 points` | one value per point in `t` |
| `page: no mount(el, ctx)` | the module must `export default { tabs, mount }` |

## 9. Setup docs

Every environment a mod needs (a venv with GPU wheels, a container image, a binary) gets a setup doc in the mod: `services/<id>/setup/<env>.md`. A mod whose only environment is the venv `install.sh` makes needs one short doc too. Copy `services/_template/setup/env.md`. Deleting the mod removes its docs. The guide that links them all is [docs/setup/](setup/README.md), and `aihub setup` reads them to install the mods a person picks (plan 23.9).

A setup doc is about **the mod**, not one machine's models: say what kind of model it runs and how to add any of them; this machine's models are examples, never requirements.

The doc starts with a TOML block in an HTML comment (GitHub doesn't show it). Only `id` and `title` are required; `aihub setup` lists a doc only when it has a `summary`:

```markdown
<!-- aihub-setup
id = "tts-kokoro"
title = "Kokoro-82M (Speech)"
models = ["hf-cache/hub/models--hexgrad--Kokoro-82M"]
scan = []
summary = "Speech: fast English voices"     # one line, shown when choosing mods
gpu = true                                  # needs the GPU (and so host.md's GPU parts)
disk_gb = 14                                # the environment alone; images and models are extra
images = { "docker.io/org/image" = 15.1 }   # container images it pulls, in GB: two setups sharing one count it once
needs = ["podman", "espeak-ng"]             # host commands that must exist
after = ["tts"]                             # setup ids to do first
check = "aihub check tts"                   # proves it works
smoke = "scripts/smoke.sh"                  # version 3: real work (one clip spoken); run by `aihub setup --smoke` and the field test

[[steps]]                                   # run in order, with bash, in the mod's folder
run = "scripts/install-runtime.sh"
what = "builds the engine venvs from locks/ (about 14 GB, 10 min)"
ask = ""                                    # a yes/no question first, such as a licence; "no" skips this setup
interactive = false                         # true: it prompts (a login), so under --json the person runs it
skip_if = ""                                # a command: exit 0 means nothing to do (logged in already), so it's done
optional = false                            # with an ask: a "no" skips only this step, not the setup
next = ""                                   # what's left to do by hand once it has run (it joins the report)

[[suggest]]                                 # optional starter models (1–3)
name = "Kokoro 82M"
repo = "hexgrad/Kokoro-82M"                 # a Hugging Face repo, downloaded into dest…
revision = "f3ff3571791e39611d31c381e3a41a3af07b4987"
files = []                                  # empty: the whole repo
dest = "hf-cache"                           # "hf-cache", or a folder under data/models/
size_gb = 0.34
good_for = "fast English voices"
licence = "Apache-2.0"
required = true                             # the engine can't run without it
gated = false                               # true: accept the repo's terms on Hugging Face first
next = ""                                   # what's left to do once it's chosen (it joins the report)
skip_if = ""                                # a command: exit 0 means it's on disk already (a step fetched it): registered, not downloaded
# start_op = "POST /api/instances"          # a mod route run after the download (launching it), with
# start_body = { model_id = "qwen3-8b" }    # its body

[[variants]]                                # version 3 (plan 38): one per accelerator it runs on, in your order of preference
accel = "rocm"                              # rocm | cuda | xpu | mps | vulkan | cpu (what `aihub hardware` lists)
os = ["linux"]                              # linux (native) | wsl | darwin
tested = true                               # where it has run for real: true (all its os), false, or a list of os
env = { MYMOD_DEVICE = "cuda" }             # for its steps, check and smoke, and the mod itself
# steps = [ { run = "./install.sh --accel rocm", what = "…" } ]   # its own steps instead of the block's
# check = "…"                               # its own check; smoke = "…" its own smoke
# note = "slow on the CPU"                  # one line shown in the plan
-->
```

- `id`: unique across all mods; `<mod>` or `<mod>-<env>`.
- `models`: globs relative to `data/models/` for the models this environment runs (`comfyui/**`); the local model inventory (`aihub docs`) uses them to say which setup doc runs a model.
- `scan`: tracked files in the mod (globs relative to its folder, e.g. `workflows/*/workflow.json`) whose mentions of a model's file name or Hugging Face repo are listed in its inventory doc as "referenced by".
- `[[suggest]]` can name a mod route instead of a repo, for mods with their own downloader: `op = "POST /v1/load"` and `body = { preset = "balanced" }` (no `dest`, `files` or `revision`). Mark weights an engine can't run without `required = true`; everything else is optional, and the default is to download nothing. A route that refuses because an earlier run's download is still going (a Ctrl-C) is waited out, and the suggestion's `skip_if` then decides; give such suggestions one (lcpp's check its catalog).
- `[[config]]` asks for a setting after install, when its choices exist: `key` (`services.<id>.env.<VAR>` or `agent.judge.model`, written to `config.toml`), `text`, `choices` (`"relay-models"`, the relay's chat models then, without its `auto` router and OpenCode's `agent`; `"folder"`, an absolute folder outside AIHub, made if missing; or a list), `required`, `restart` (mod ids, or `"hub"`, restarted in order once it's set; `"opencode relay"`). Values are saved through the hub, which applies them at once; the questions about the relay's models come after the others, since a folder or list value can bring the relay new models. The agent's doc asks for its model this way; an agent answers with `--set "<id or key>=<value>"`, and can add a hosted provider first (`"providers"` in `--answers`).
- `[[variants]]` (version 3, plan 38): `aihub setup` picks the first whose `accel` this machine has (`aihub hardware`) and whose `os` matches, runs its steps (or the block's) with its `env`, and records the choice. A setup with no fitting variant is "not available on this machine". One that isn't `tested` on this kind of machine is named as untested in the plan. A block without variants is one: `cpu` on every system for `gpu = false`, `rocm` on Linux for `gpu = true`. The mods index's "Runs on" column comes from them.
- Unknown keys are errors, at the top and inside `[[steps]]`, `[[suggest]]`, `[[config]]` and `[[variants]]`; `aihub docs --check` reports them.
- `aihub setup` runs `[[steps]]` and `check` in the mod's folder, asks every `ask` question and every model choice before it runs anything (the hub stage included); a "no" skips that setup and every chosen setup whose `after` names it, and the report lists them. An `interactive` step runs in the terminal for a person; under `--json` the run stops with its command, the person runs it, and `--done <step id>` continues. A `[[suggest]]` with an `op` is followed until the job it starts ends (the mod's jobs in `GET /api/services/<id>`), and a failed job fails the step. The wizard downloads the chosen `[[suggest]]` models after the steps (a step may fetch weights its installer needs offline first: the wizard's download then finds them and only registers them). A `repo` suggestion in `hf-cache` pinned to a commit also gets `refs/main` pointed at it, for engines that load by `main`.

Then these sections, in this order. Leave a section out only when it has nothing to say:

1. **What it is**: one paragraph: what runs here and which features need it.
2. **Tested with**: the versions this machine runs, read from the machine: image digest, Python, torch and ROCm builds (from the lock files), upstream commits, binaries. A reference for when something breaks, not a requirement.
3. **Prerequisites**: other environments, host packages ([host.md](setup/host.md)), accounts, licences.
4. **Install**: commands in order, one per block, each followed by what it does, what it downloads and from where, how big and how long.
5. **Choosing models**: what kind of model the mod runs, where the files go, and how to add your own (the mod's page, its downloader, or a command); the suggestions with their sizes and licences; weights an engine needs, if any.
6. **Configuration**: `.env` and `service.toml` keys, marked required or optional.
7. **Check it works**: commands and the output to expect.
8. **What to look for**: what's specific to each variant (`gfx1151`, CUDA versions, …), known errors and their fixes, what breaks quietly.
9. **Known gaps**: steps no script does yet.
