# Claude Design Brief: lcpp — llama.cpp Model Launcher UI

> Paste everything below this line into Claude Design (`/design`). Return with the resulting HTML.

---

## 0. What you are building

Design and build a **fully working, interactive single-page web app** called **lcpp**. It is a local control panel for starting, stopping, monitoring and testing llama.cpp model servers (`llama-server`) on one Linux workstation, and for publishing those servers to a local LLM relay called **Relay** (DashLLM).

The page will be served by a small local FastAPI daemon at `http://127.0.0.1:7700/`. **Everything runs on this one machine only.** Nothing is exposed to a network, and there are no user accounts, no login and no multi-user concerns.

The page you deliver must work on its own in the browser **against a built-in mock API** that behaves like the real daemon (Section 7). That way every control can be clicked and every state can be seen now. Later, a single switch changes it to the real API without touching any UI code (Section 6.1).

---

## 1. Hard deliverable constraints

1. **Format**: One self-contained `index.html` with inline `<style>` and `<script type="module">`. Alternatively, `index.html` + `assets/styles.css` + `assets/app.js` (+ `assets/api.js`, `assets/mock.js`). Either is fine. There is **no build step**, so do not use JSX that needs compiling, npm, bundlers or TypeScript.
2. **No framework dependency.** Use vanilla JS (ES2022 modules, `fetch`, `EventSource`, `<template>`, custom elements if helpful). No React, Vue, Tailwind or component libraries.
3. **External requests**: the only allowed ones are Google Fonts for **IBM Plex Sans** and **JetBrains Mono**, with good system fallbacks (`system-ui`, `ui-monospace`). There must be no CDNs, analytics, icon fonts or remote images. Icons are inline SVG.
4. **All data access goes through one `api` object** (Section 6) with exactly the method names listed. UI code never calls `fetch` directly.
5. **Mock mode is the default** in the design environment. Live mode is chosen by `window.LCPP_API_BASE` being set, or by the URL query `?live`. In live mode, `api` calls the endpoints in Section 6 on the same origin.
6. Must work in current Chromium and Firefox at widths from **360 px to 2560 px**.
7. Keep the code readable and sectioned (api / mock / state / views / components). I will split it into files and wire it to the real daemon, so clarity matters more than cleverness.

---

## 2. Visual direction

lcpp is a **sibling of the Relay dashboard** and should feel like the same product family: a dense, calm operator console, dark-first.

**Relay's tokens**: use these as the dark theme and derive a matching light theme. Expose all colors as CSS custom properties on `:root`.

| Token | Dark value | Use |
| --- | --- | --- |
| `--bg` | `#0B0E14` | page |
| `--bg-sidebar` | `#0D1119` | nav / inputs |
| `--bg-card` | `#11151D` | cards |
| `--bg-inset` | `#131926` | inset panels, code |
| `--bg-hover` | `#161C28` | hover |
| `--bg-row` | `#1A2130` | table rows |
| `--border` | `#1D2430` | hairlines |
| `--border-strong` | `#2A3547` | controls |
| `--border-hover` | `#3A4A63` | hover borders |
| `--text` | `#E6EAF2` | primary text |
| `--text-mut` | `#8A94A6` | secondary |
| `--text-dim` | `#525C6E` | tertiary |
| `--accent` | `#FFB224` | amber — primary actions, "starting" |
| `--cyan` | `#58C4DD` | relay / links / info |
| `--green` | `#3FB950` | ready / healthy |
| `--red` | `#F85149` | failed / destructive |
| `--purple` | `#BC8CFF` | router instances / special |

- **Type**: IBM Plex Sans for UI text and JetBrains Mono for numbers, ports, ids, paths, flags and logs. Uppercase section labels are 11 px/600 with `letter-spacing: .07em`.
- **Status dots**: 8 px. A dot pulses while the state is in flux (starting, stopping, relay pending).
- **Toggles, segmented controls and badges** follow Relay's style: 34×18 track toggle, small monospace badges with a 1 px border, and cards with 8 px radius and a 1 px border.
- **Theme**: follow `prefers-color-scheme`, with a manual Light / Dark / System toggle. The choice is saved in `localStorage` inside try/catch, and the page renders fine if storage is unavailable.
- **Motion** is subtle, and all of it respects `prefers-reduced-motion`.
- **Logo**: a simple inline-SVG mark for "lcpp" and a matching favicon (SVG data URI).

---

## 3. Layout & navigation

**Desktop (≥ 1024 px)**: left sidebar with main content.
**Tablet and phone**: top bar with a menu button, content in one column, and dialogs that become full-screen sheets.

**Sidebar / nav items**:
1. **Instances** (default view)
2. **Models**
3. **Playground**
4. **Relay**
5. **Settings**

The sidebar footer shows the daemon status dot + version and a link: "Open Relay dashboard ↗" (`relay.dashboard_url`).

**Persistent header** (all views):
- Memory meter: system RAM used / total, with GPU memory (GTT) used / total below it. It turns amber above 80% and red above 92%.
- Count of running instances.
- Relay reachability pill: `Relay ● connected` or `Relay ○ unreachable`.
- **[+ Launch]**: the primary button, amber. It opens the Launch dialog from anywhere.
- **[Stop all]**: destructive. It is only enabled when at least one instance is running, and it asks for confirmation.

A **toast area** sits in the bottom-right corner (bottom-center on phones) for success and error messages. Errors stay until dismissed; successes auto-hide after 4 s.

The **URL hash reflects the view** (`#/instances`, `#/models`, `#/playground?instance=…`, `#/relay`, `#/settings`, `#/instances/<name>/logs`), so reloading keeps your place and the browser Back button works.

---

## 4. Views and their requirements

### 4.1 Instances view (home)

A grid of **instance cards** (a list or table layout on toggle) for every running, starting, stopping or failed instance.

**Each card shows**:
- Status dot + state label: `starting` (amber, pulsing, with elapsed seconds), `ready` (green), `stopping` (amber, pulsing), or `failed` (red).
- **Name** (e.g. `minicpm-7071`) and **kind badge**: `single` or `router` (purple).
- **Model**: display name + nickname. For routers, a list of the models it serves, with a per-model loaded/unloaded dot.
- **Endpoint**: `http://127.0.0.1:<port>/v1`, with a copy button.
- **Uptime**, **memory (RSS)**, and **PID** (dim, monospace).
- **Key params** as small badges: ctx size, KV cache types, "vision" when an mmproj is attached, and "spec-decode" when a draft model is attached.
- **Relay status**: one of `off`, `pending` (amber pulse, "relay unreachable, retrying"), `registered` (cyan, showing alias and relay health), or `error` (red, with message). It includes a publish/unpublish toggle and an alias chip.
- **Last error** (failed state): the message plus the last 5 log lines inline, with **[View logs]**, **[Retry]** and **[Dismiss]**.

**Card actions**:
- **Logs**: opens the logs drawer.
- **Try it**: opens the Playground with this instance selected.
- **Restart**, which asks for confirmation.
- **Stop**, which asks for confirmation. The dialog shows the name and port, and warns when the instance is published to Relay: "It will also be removed from Relay."
- **Copy command**: copies the full llama-server command line.
- A **"…" menu** with: Copy endpoint URL, Copy curl example, Show details (full effective params and argv in a read-only panel), and Open in Relay (only when registered).
- **Router cards only**: per-model **Load / Unload** buttons.

**Empty state**: a friendly message ("No models running. lcpp is idle and using almost nothing."), the idle daemon memory figure, a big **[Launch a model]** button, and quick-launch chips for the three most recently launched configurations (from `api.getRecent()`).

**Daemon unreachable state** (live mode): a full-width banner reading "lcpp daemon not responding at 127.0.0.1:7700". It shows the retry countdown and the hint text `lcpp service start`, and it clears automatically when the daemon comes back.

### 4.2 Launch dialog (modal; full-screen sheet on phones)

**Fields**:
1. **Mode** segmented control: `Single model` or `Router (many models, load on demand)`.
2. **Model** (single mode): a searchable picker listing the catalog. Each row shows id, nicknames, total size, "vision" / "spec-decode" badges, and how many instances already run it. Models with missing files are disabled and show the reason. Router mode shows a multi-select checklist of models, all selected by default, plus **Max loaded at once** (a number, default 1).
3. **Port**: a number input, pre-filled with `suggested_port`. It is checked live through `api.preflight()` with a 300 ms debounce, and shows ✓ free, ✗ "in use by <process>", or ✗ "reserved (lcpp daemon / Relay)". A **[Use next free]** link sits beside it.
4. **Name**: optional. The placeholder is the auto name `<nickname>-<port>`. It must be unique and match `^[a-z0-9][a-z0-9-]{0,47}$`, validated live.
5. **Context size**: a select with presets (4k, 8k, 16k, 32k, 64k, 128k, 256k) plus custom. It defaults to the model's configured value.
6. **Publish to Relay**: a toggle, defaulting from settings (`relay.auto_register`), plus an **Alias** text field that defaults to the model's first nickname. The toggle is disabled with a tooltip when Relay is unreachable ("will register when Relay comes back" if left on).
7. **Advanced** (collapsed):
   - Common overrides as proper controls, each showing the model default as placeholder text:
     - `n-gpu-layers` (number)
     - `cache-type-k` / `cache-type-v` (select: f16, q8_0, q4_0)
     - `flash-attn` (toggle)
     - `batch-size` / `ubatch-size` (number)
     - `parallel` (number of slots)
     - `threads` (number)
   - Free-form **extra flags**: a key/value row editor with add and remove. Values may be empty for boolean flags.
   - **Save as preset** checkbox + name field, which saves this configuration to recent/presets.
8. **Preflight summary box**: estimated memory needed (model files + a KV estimate), available memory, and any warnings such as "Estimated 38.2 GB needed, 31.0 GB available. Loading may fail or swap." Warnings never block launch; errors (port taken, name taken, missing file) do.
9. **Command preview**: a read-only monospace block showing the exact llama-server command that will run. It updates live as fields change and has a copy button.

**Buttons**: **[Cancel]** and **[Launch]**. Launch is disabled while there are errors, and it shows a spinner while the request is in flight. On success the dialog closes, a toast says "Starting minicpm-7071…", and the new card appears at once in the `starting` state.

**Keyboard**: `Esc` closes the dialog, `Ctrl/Cmd+Enter` launches, focus is trapped while open, and focus returns to the trigger when it closes.

### 4.3 Logs drawer

- A right-side drawer (a bottom sheet on phones) titled with the instance name and state.
- It shows a live tail through `api.streamLogs()`. Lines are monospace. Lines containing `error` or `failed` are highlighted red, and `warn` lines amber.
- **Controls**:
  - **Follow** toggle (auto-scroll). It switches off automatically when the user scrolls up, and a "↓ Jump to latest (N new)" pill appears.
  - **Filter** text box.
  - **Wrap** toggle.
  - **Copy all** and **Download .log** buttons.
  - Line-count select: 200 / 1000 / 5000.
- The stream closes when the drawer closes. The drawer can stay open while instances change state.

### 4.4 Models view (catalog)

**Table of configured models**, with these columns:
- id
- nicknames (chips)
- location (`models/` or external path)
- total size
- files (a count; expanding the row shows each file with its role — `model`, `split 2/3`, `mmproj`, `draft` — plus its size and an exists ✓ / missing ✗ mark)
- capability badges (vision, spec-decode, split)
- configured context size
- running count
- actions: **Launch** (opens the Launch dialog pre-filled), **Edit**, **Delete**

Delete is disabled while an instance is running the model, and it asks for confirmation that says the files stay on disk.

**Model defaults card**: the shared defaults applied to every model (`ctx-size`, `cache-type-k`/`v`, `n-gpu-layers`, `flash-attn`, `no-mmap`, `batch-size`, `ubatch-size`) in an editable form with Save and Revert.

**Discovered GGUFs section**: files found in the scan directories that are not in the catalog. Each shows path, size and a suggested id, with **[Add to catalog]**. That opens the Model editor pre-filled.

**Model editor** (modal):
- id (unique slug) and nicknames (a chip input)
- model file path (a text field with a picker listing discovered files)
- optional mmproj file and draft model file
- speculative type (select: none, `draft-mtp`, `draft`)
- per-model param overrides (key/value editor with the same common controls as Launch → Advanced)

The editor checks paths live through `api.validateModel()`, showing ✓ exists and the size, or ✗ not found, and it detects split GGUFs ("split 1 of 3 — all parts present").

### 4.5 Playground

Choose freely, or test a server's endpoint before relying on it.

- **Target** selector: any `ready` instance (direct, `127.0.0.1:<port>`), **or** "via Relay", which picks from the relay's routable model names. The second option tests the full relay path.
- A **chat panel**: a system prompt field (collapsible), then a message list and composer. Responses stream token by token. There is a **Stop** button while generating and a **Clear** button.
- **Sampling controls** (side panel on desktop, collapsible on phones): temperature, top_p, max_tokens, and a reasoning on/off toggle. When the model returns `reasoning_content`, it appears in a collapsible "Thinking" block above the answer.
- **Per-response metrics** under each reply: time to first token, tokens/s, prompt and completion token counts, and total time.
- **Code snippet** tab: curl, Python (`openai` SDK) and JS (`fetch`) snippets for the current target and settings, with a copy button.
- If the target instance stops mid-stream, show an inline error in the reply rather than a crash.

### 4.6 Relay view

- A **connection card** with the relay URL, reachability, latency and relay version (if available), plus a **[Test connection]** button and a link to the Relay dashboard.
- A **Registrations managed by lcpp** table, with these columns:
  - key (`lcpp:<port>`)
  - instance name
  - alias
  - advertised models
  - relay health (`healthy`, `degraded`, `failed` or `unknown`)
  - registered time
  - actions: **Unpublish**, **Change alias** (inline edit)
- **Orphans** (registrations whose instance no longer exists) are flagged amber with a **[Remove]** button and a **[Clean up all orphans]** bulk action.
- An **Other relay endpoints** table (read-only, dimmed): endpoints lcpp does not own (e.g. `skynet`, `opencode`), so the whole routing picture is visible. Each row shows name, alias, server type, health and base URL.
- A **Publish an instance** control: a select of ready, unpublished instances, an alias field and a **[Publish]** button.

### 4.7 Settings view

These map to `data/lcpp.json`. There is one form with **Save** and **Revert**, and a "restart required" note on the fields that need it.
- **Daemon**: port (7700), with a note: "Bound to 127.0.0.1 — this machine only". The port field needs a restart.
- **llama.cpp**: binary path (read-only display + validation ✓), build (read-only, e.g. `b9692`), environment variables (key/value editor, e.g. `AMD_VULKAN_ICD=RADV`, `GPU_MAX_HW_QUEUES=8`), and server params applied to every instance (key/value editor, e.g. `jinja: true`, `reasoning: auto`, `reasoning-format: deepseek`, `reasoning-budget: -1`).
- **Ports**: automatic port range start/end (7071–7199).
- **Relay**: URL (`http://127.0.0.1:4000`), dashboard URL, and auto-publish new instances (toggle). **[Test]** button.
- **Scan directories** for model discovery: a list with add and remove (`models/`, `~/Models`).
- **Interface**: theme (System/Light/Dark), default instances layout (grid/list), and poll interval (read-only info).
- An **About** block with the lcpp version, daemon PID, uptime, daemon memory, and the CLI equivalents for common actions (`lcpp status`, `lcpp start <model> --port N`, `lcpp stop <name|port|all>`, `lcpp logs <name> -f`).

---

## 5. Global interaction rules

1. **Polling**: poll `api.getOverview()` **only while the tab is visible** (`document.visibilityState`). Poll every **2 s** while any instance is `starting` or `stopping`, or any relay registration is `pending`; otherwise every **10 s**. Poll once as soon as the tab becomes visible again. Never poll while hidden, because the daemon must stay idle when no one is looking.
2. **Optimistic updates** for launch, stop, restart, publish and unpublish. The UI updates immediately, then reconciles with the server response. On an error, roll back and show a toast with the server's `detail` message.
3. **Every destructive action is confirmed**: Stop, Stop all, Restart, Delete model, Unpublish, Remove orphan. The confirm dialog names exactly what will happen.
4. **Errors**: API errors arrive as `{ "detail": string, "code": string }`. Show `detail` verbatim. Map known `code`s to field-level errors in forms (Section 6.3).
5. **Accessibility**:
   - WCAG 2.1 AA contrast in both themes.
   - Full keyboard operation with visible focus rings.
   - Real `<button>`/`<input>`/`<dialog>` semantics.
   - `aria-live="polite"` for status changes and toasts.
   - Status is never conveyed by color alone; always pair it with a label or icon.
   - Minimum touch target 40 px on phones.
6. **Keyboard shortcuts** (shown in a `?` help overlay):
   - `n` — Launch
   - `g i` / `g m` / `g p` / `g r` / `g s` — switch views
   - `/` — focus search in the Models view
   - `l` — logs for the focused card
7. **Numbers**: bytes are shown in GB with one decimal (binary GiB, labelled "GB"). Durations look like `3h 12m` or `45s`. Ports and PIDs are never comma-formatted.
8. **No blocking spinners on the whole page.** Use skeletons on first load, then show the last known data while refreshing.

---

## 6. The `api` object (exact contract)

Implement `api` with **exactly** these methods. In live mode each one maps to the HTTP call shown. All methods return Promises resolving to the documented JSON, or reject with an `ApiError { status, detail, code }`.

### 6.1 Mode switch
```
const LIVE = !!window.LCPP_API_BASE || new URLSearchParams(location.search).has('live');
const BASE = window.LCPP_API_BASE || '';   // same origin in live mode
export const api = LIVE ? createHttpApi(BASE) : createMockApi();
```
Show a small `MOCK` badge in the sidebar footer when mock mode is active.

### 6.2 Methods → endpoints

| Method | HTTP | Returns |
| --- | --- | --- |
| `getOverview()` | `GET /api/overview` | `{ instances: Instance[], system: System, relay: RelayStatus }` |
| `listInstances()` | `GET /api/instances` | `Instance[]` |
| `getInstance(name)` | `GET /api/instances/{name}` | `Instance` |
| `preflight(spec)` | `POST /api/instances/preflight` body `LaunchSpec` | `Preflight` |
| `launch(spec)` | `POST /api/instances` body `LaunchSpec` | `201 { instance: Instance, warnings: string[] }` |
| `stop(name)` | `DELETE /api/instances/{name}` | `202 Instance` (state `stopping`) |
| `stopAll()` | `POST /api/instances/stop-all` | `202 { stopping: string[] }` |
| `restart(name)` | `POST /api/instances/{name}/restart` | `202 Instance` |
| `dismiss(name)` | `DELETE /api/instances/{name}?dismiss=1` | `204` (removes a `failed` card) |
| `routerLoad(name, modelId)` | `POST /api/instances/{name}/models/{modelId}/load` | `Instance` |
| `routerUnload(name, modelId)` | `POST /api/instances/{name}/models/{modelId}/unload` | `Instance` |
| `getLogs(name, lines)` | `GET /api/instances/{name}/logs?lines=N` | `{ lines: LogLine[] }` |
| `streamLogs(name, onLine)` | `EventSource GET /api/instances/{name}/logs/stream` | returns `{ close() }`; each SSE `data:` is a `LogLine` JSON |
| `publish(name, alias)` | `POST /api/instances/{name}/relay` body `{ alias }` | `Instance` |
| `unpublish(name)` | `DELETE /api/instances/{name}/relay` | `Instance` |
| `chat(target, body, onDelta, signal)` | `POST /api/chat` body `{ target: ChatTarget, request: <OpenAI chat body, stream:true> }` → SSE of OpenAI `chat.completion.chunk` + final `{"lcpp_metrics": Metrics}` event | resolves `Metrics` |
| `listModels()` | `GET /api/models` | `{ defaults: Params, models: Model[] }` |
| `saveModel(model)` | `PUT /api/models/{id}` body `ModelInput` | `Model` |
| `deleteModel(id)` | `DELETE /api/models/{id}` | `204` |
| `saveDefaults(params)` | `PUT /api/models/defaults` body `Params` | `Params` |
| `validateModel(input)` | `POST /api/models/validate` body `ModelInput` | `{ ok, files: ModelFile[], errors: string[] }` |
| `listDiscovered()` | `GET /api/models/discovered` | `Discovered[]` |
| `getRelay()` | `GET /api/relay` | `{ status: RelayStatus, owned: Registration[], others: RelayEndpoint[], routable_models: string[] }` |
| `testRelay()` | `POST /api/relay/test` | `RelayStatus` |
| `removeRegistration(key)` | `DELETE /api/relay/registrations/{key}` | `204` |
| `cleanupOrphans()` | `POST /api/relay/cleanup` | `{ removed: string[] }` |
| `getSettings()` | `GET /api/settings` | `Settings` |
| `saveSettings(s)` | `PUT /api/settings` | `{ settings: Settings, restart_required: boolean }` |
| `getRecent()` | `GET /api/recent` | `LaunchSpec[]` (max 5, newest first) |
| `suggestPort()` | `GET /api/ports/suggest` | `{ port: number }` |

### 6.3 Error codes to handle
`port_in_use`, `port_reserved`, `name_taken`, `invalid_name`, `model_not_found`, `model_files_missing`, `model_in_use`, `instance_not_found`, `alias_conflict`, `relay_unreachable`, `invalid_param`, `daemon_error`.

### 6.4 Types (JSON shapes)

```ts
type State = "starting" | "ready" | "stopping" | "failed";
type RelayState = "off" | "pending" | "registered" | "error";
type Health = "healthy" | "degraded" | "failed" | "unknown";

interface Instance {
  name: string;                 // "minicpm-7071"
  kind: "single" | "router";
  model_id: string | null;      // null for router
  models: { id: string; loaded: boolean }[];  // router only; [] for single
  host: "127.0.0.1";
  port: number;
  url: string;                  // "http://127.0.0.1:7071/v1"
  state: State;
  pid: number | null;
  started_ts: number;           // unix seconds
  ready_ts: number | null;
  rss_bytes: number | null;
  params: Params;               // effective params
  argv: string[];               // full command line
  capabilities: { vision: boolean; speculative: boolean };
  relay: { state: RelayState; key: string | null; alias: string | null;
           health: Health | null; error: string | null };
  last_error: string | null;
  last_log_lines: string[];     // last ≤5, populated when failed/starting
}

type Params = Record<string, string | number | boolean | null>;

interface LaunchSpec {
  kind: "single" | "router";
  model_id?: string;            // single
  model_ids?: string[];         // router; omitted = all
  models_max?: number;          // router
  port?: number;                // omitted = auto
  name?: string;                // omitted = auto
  params?: Params;              // overrides (ctx-size, etc.)
  relay?: { enabled: boolean; alias?: string };
  save_preset?: string | null;
}

interface Preflight {
  port: number; port_ok: boolean; port_reason: string | null;  // "in use by python3 (pid 5816)"
  suggested_port: number;
  name: string; name_ok: boolean; name_reason: string | null;
  estimated_bytes: number; available_bytes: number;
  warnings: string[]; errors: { code: string; detail: string; field: string }[];
  argv: string[];               // command preview
}

interface ModelFile { role: "model" | "split" | "mmproj" | "draft"; path: string;
                      size_bytes: number | null; exists: boolean; part?: string /* "2/3" */ }

interface Model {
  id: string; nicknames: string[]; path: string;
  location: "models" | "external";
  files: ModelFile[]; size_bytes: number; ok: boolean; problems: string[];
  capabilities: { vision: boolean; speculative: boolean; split: boolean };
  overrides: Params;            // per-model params
  effective: Params;            // defaults + overrides
  running: string[];            // instance names
}
type ModelInput = Pick<Model, "id" | "nicknames" | "path" | "overrides"> &
                  { mmproj?: string | null; draft?: string | null; spec_type?: string | null };

interface Discovered { path: string; size_bytes: number; suggested_id: string; dir: string }

interface System {
  memory: { total_bytes: number; used_bytes: number; available_bytes: number };
  gpu: { name: string; vram_total_bytes: number; vram_used_bytes: number;
         gtt_total_bytes: number; gtt_used_bytes: number } | null;
  daemon: { version: string; pid: number; rss_bytes: number; uptime_s: number; port: number };
  llama: { build: string; binary: string; binary_ok: boolean };
}

interface RelayStatus { url: string; dashboard_url: string; reachable: boolean;
                        latency_ms: number | null; error: string | null }

interface Registration { key: string; instance: string | null; alias: string | null;
                         models: string[]; health: Health; registered_ts: number;
                         orphan: boolean; endpoint_id: string }

interface RelayEndpoint { name: string; alias: string | null; server_type: string;
                          health: Health; base_url: string }

type ChatTarget = { type: "instance"; name: string } | { type: "relay"; model: string };
interface Metrics { ttft_ms: number; tokens_per_s: number; prompt_tokens: number;
                    completion_tokens: number; total_ms: number }

interface LogLine { ts: number; text: string; stream: "stdout" | "stderr" }

interface Settings {
  daemon: { port: number };
  llama: { binary: string; environment: Record<string,string>; server_params: Params };
  ports: { start: number; end: number };
  relay: { url: string; dashboard_url: string; auto_register: boolean };
  scan_dirs: string[];
}
```

---

## 7. Mock API requirements (must feel real)

The mock keeps in-memory state, applies the same validation rules, and simulates time.

**Seed data**: this is the real machine. Use it exactly.

- **System**: 121 GB RAM total (~36 GB used). GPU "AMD Radeon 8060S (Strix Halo)" with 4.0 GB VRAM and 121.5 GB GTT (unified memory). llama.cpp build `b9692`. Daemon version `0.1.0`, RSS ~48 MB.
- **Model defaults**: `ctx-size 262144`, `cache-type-k q8_0`, `cache-type-v q8_0`, `n-gpu-layers 999`, `flash-attn true`, `no-mmap false`, `batch-size 2048`, `ubatch-size 512`.
- **Catalog**:

  | id | nicknames | files (bytes) | notes |
  | --- | --- | --- | --- |
  | `gemma-4-26B-it` | gemma4-26B | model 16,796,015,520 · mmproj 1,194,827,776 · draft 251,937,728 | vision + spec-decode (`draft-mtp`) |
  | `gemma-4-19B-it` | gemma4-19B | model 12,291,399,776 | |
  | `gemma-4-E4B-it` | gemma4-E4B | model 11,302,792,672 | |
  | `ornith1-35B` | ornith1-35B | model 21,166,757,408 | |
  | `minicpm-5-2B` | MiniCPM5-2B | model 2,679,710,688 | override `ctx-size 131072` |
  | `nemotron-3-super` | nemotron3-super | 3 splits: 7,872,576 · 49,932,117,344 · 32,601,178,560 | external (`~/Models/Nemotron3Super/`), split |

  Model paths look like `models/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf` and `models/MiniCPM5-2B/MiniCPM5-2B-Q8_0.gguf`.
- **Discovered** (in `~/Models`):
  - `Qwen3.6-27B-Q4KM.gguf` (17,106,773,120)
  - `Serenity-12B-Q4_K_M.gguf` (7,381,382,208)
  - `Serenity-26B-A4B-Q4_K_M.gguf` (16,796,016,576)
- **Relay** at `http://127.0.0.1:4000`, reachable. Other endpoints:
  - `skynet` (vLLM, failed, `http://127.0.0.1:9090/v1`)
  - `opencode` (alias `agent`, opencode, healthy, `http://127.0.0.1:4096`)
- **Initially running**: one instance, `gemma4-26B-7071` (single, ready, published as alias `gemma4-26B`, relay healthy, RSS ~18.6 GB).
- **Ports in use by other processes** (the preflight must reject them): 4000 (Relay), 4096 (opencode), 5432 (postgres), 6379 (redis), 7700 (lcpp daemon).

**Simulated behavior**:
- **Launch → `starting`**, then `ready` after `2 s + 0.4 s per GB` of model size. While starting, stream realistic llama.cpp log lines to the logs stream (`load_tensors: offloading 999 layers to GPU`, `llama_context: n_ctx = 131072`, `srv  load_model: loading model…`, `main: server is listening on http://127.0.0.1:7072`). The RSS figure grows as it loads.
- **Relay registration** goes `pending → registered` about 1 s after `ready`. When the mock relay is "unreachable", it stays `pending`.
- **Stop → `stopping`**, and the instance disappears after 1.5 s. Registration is removed at the same time.
- **Chat** streams a plausible reply word by word at ~40 tokens/s after a 300–900 ms TTFT. It includes a short `reasoning_content` preamble when reasoning is on, and resolves with metrics. The request can be aborted through `signal`.
- **Router instances** support load and unload. Loading takes 3 s and only `models_max` models can be loaded at once; loading another model unloads the oldest.
- **Failure paths** are reachable from the UI:
  - **Port taken**: launching on 4000 fails preflight (`port_reserved`), and 5432 fails with `port_in_use`.
  - **Mid-load failure**: launching `ornith1-35B` while `gemma-4-26B` is running *and* another large model is running goes to `failed`, with `last_error = "failed to allocate buffer: out of device memory"` and matching log lines.
  - **Missing file**: a model entry saved with a path that does not exist is shown `ok: false`, with a problem message.
- **Mock scenario switcher**: a small dev panel, shown only in mock mode and opened with `Shift+D`, that can:
  - toggle **Relay reachable**
  - toggle **Daemon down** (every call rejects with a network error, which shows the banner)
  - reset to **Seed**, **Empty** (nothing running), or **Busy** (4 instances including a router and one failed)
  - set speed ×1 / ×5

---

## 8. States checklist (each must be designed and reachable)

- First load: skeleton, then data.
- Instances: empty, one ready, many (≥ 6, the grid must not break), starting, stopping, failed, router with mixed loaded/unloaded models.
- Relay: every state — off, pending, registered, error — and Relay unreachable globally.
- Daemon down banner, and its recovery.
- Launch dialog: default, port conflict, name conflict, memory warning, missing-model disabled row, router mode, advanced expanded, submitting.
- Logs: streaming, paused follow with "N new", filtered with no matches, empty.
- Models: expanded split model, discovered list, editor with validation errors, delete blocked because the model is in use.
- Playground: no ready instances (empty state with a Launch button), streaming, stopped mid-stream, target died, metrics shown.
- Settings: dirty with an unsaved-changes guard on navigation, saved with the restart-required note, invalid value.
- Phone width (360 px) for every view, and both themes for every view.

---

## 9. Acceptance criteria

1. Opening `index.html` directly (or from any static server) shows the seeded app in mock mode, and every button does something real against the mock.
2. Setting `window.LCPP_API_BASE = ''` before load (or adding `?live`) switches to HTTP calls against the Section 6 endpoints, with no other code changes.
3. No console errors in normal use. No horizontal page scroll at 360 px.
4. Dark and light themes both pass WCAG AA contrast.
5. There is no polling while the tab is hidden, which can be confirmed by adding `console.debug` in the poller.
6. All Section 8 states are reachable through normal use or the `Shift+D` mock panel.
7. The code is organized into clearly labelled sections: `api (http)`, `api (mock)`, `state/store`, `router (hash)`, `views/*`, `components/*`, `utils`.

## 10. What to return

- The final `index.html` (and any `assets/*` files if split).
- A short list of any API changes you found necessary, such as extra fields, as a diff against Section 6.
- Any open design questions.
