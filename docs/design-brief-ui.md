# Claude Design Brief: AIHub — one control panel for every local AI service

> Companion docs: [architecture.md](architecture.md) (how AIHub works) and [backend-plan.md](backend-plan.md) (backend build steps). Section 6 of this brief, plus the additions in Section 11.7, is the authoritative contract for the UI-facing API.
>
> **Status (2026-10-04):** **Part A v1 is delivered.** Claude Design exported it in its `.dc.html` format; the reference copy is in [reference/ui-export-2026-10-04/](reference/ui-export-2026-10-04/README.md). It is the visual and structural baseline for everything else.
> - **Part A revision 2** (Section 11) was built by hand in this repo (backend-plan 6.5, 2026-10-05); what differs from Section 11 is under §11.11. `web/` is now the baseline.
> - **Next Claude Design pass:** the Part B pages, one per mod as each one is moved in (backend-plan Phases 7–11). Give Claude Design the current `web/` folder and `web/PATCHES.md` with the Part B section.
>
> Paste everything below the line into Claude Design (`/design`). Attach these three files from the lcpp project as the starting design system: `~/Models/LLMs/web/assets/tokens.css`, `components.css` and `components.js`.
> **Build Part A first.** Part B (the service-specific pages) is built afterwards, one page per pass, against the contract defined in Part A.

---

## 0. What you are building

AIHub is a **fully working, interactive single-page web app**. It is the one control panel for every AI service on one Linux workstation: a relay with an analytics dashboard for language models, a llama.cpp model launcher, a text-to-speech server with voice cloning, a 3D asset generator, and later ComfyUI for image and video generation, plus a chat agent that drives all of them.

Each service is a **mod**: a folder in `services/` that runs as its own local HTTP server. The AIHub backend (`app.py`, at `http://127.0.0.1:7000/`) discovers the mods, starts and stops them, proxies their APIs, tracks memory, indexes everything they produce, and serves this UI. **Anyone can add a mod by dropping a folder into `services/`.** The UI must therefore work for services it has never heard of. That is the most important design requirement in this brief.

**Everything runs on this one machine.** The AIHub binds to 127.0.0.1 only. There is no login, no accounts and no multi-user handling.

The page must work on its own in the browser **against a built-in mock API** that behaves like the real AIHub (Section 7). One switch (Section 6.1) changes it to the real API without touching any UI code.

---

## 1. Hard deliverable constraints

1. **No build step.** Plain HTML, CSS and ES2022 modules. No npm, no bundlers, no TypeScript, no JSX.
2. **No framework.** Vanilla JS (`fetch`, `EventSource`, `<template>`, `<dialog>`, custom elements where helpful). No React, Vue, Tailwind or component libraries.
3. **External requests**: only Google Fonts (**IBM Plex Sans**, **JetBrains Mono**), with good system fallbacks. No CDNs, no analytics, no icon fonts, no remote images. Icons are inline SVG.
4. **All data access goes through one `api` object** (Section 6) with exactly the listed method names. UI code never calls `fetch` directly.
5. **Mock mode is the default** in the design environment. Live mode is chosen by `window.AIHUB_API_BASE` being set, or by the URL query `?live`.
6. Works in current Chromium and Firefox from **360 px to 2560 px** wide.
7. **File layout** (exactly this; it becomes the project's `web/` folder):

```
web/
├── index.html
├── css/
│   ├── tokens.css        colors, type, spacing, radii (dark + light themes)
│   ├── base.css          reset, typography, focus rings, scrollbars
│   ├── components.css    styles for every component in components.js
│   └── layout.css        shell: sidebar, header, page frame, drawers, responsive rules
├── js/
│   ├── app.js            boot, shell, hash router, shortcuts, command palette
│   ├── api.js            ApiError + createHttpApi(base): the contract in Section 6
│   ├── mock.js           createMockApi(): in-memory AIHub + services with simulated time
│   ├── store.js          state, SSE subscription, polling fallback
│   ├── components.js     the design system (ES module exporting DOM factories)
│   ├── charts.js         dependency-free SVG charts
│   ├── utils.js          formatting (bytes, durations, dates), debounce, etc.
│   └── pages/
│       ├── overview.js
│       ├── service.js    the service page frame + the generic tabs (Section 4.2)
│       ├── models.js
│       ├── outputs.js
│       └── settings.js
├── assets/
│   └── logo.svg
└── (Part A also delivers) services/_template/ui/page.js — the example page module (Section 5)
```

8. **Code clarity matters more than cleverness.** I will wire this to a real backend and other people will write mods against it.

### 1.1 The delivered format (accepted; replaces items 1, 2 and 7 from revision 2 on)

Claude Design delivers its own `.dc.html` format:
- a template with `{{ }}` bindings, `sc-if` and `sc-for`
- one `class Component extends DCLogic` per file
- shared components loaded with `<dc-import name="X">` from `./X.dc.html`
- the generated runtime `support.js`, which renders through React 18

We keep this format as the **source of truth**, so Claude Design can keep iterating on the real UI rather than on a hand-port. The rules that still apply:
- **React and ReactDOM load from `web/vendor/`.** AIHub serves `Hub.dc.html` with local `react` and `react-dom` scripts placed before `support.js`; the runtime then skips its unpkg download. No other CDN is allowed, and nothing needs `.jsx`/`.tsx` (so no Babel).
- **All data goes through the `api` object** (Section 6).
- **`mock.js` stays a plain ES module** exporting `createMockApi()`.
- **New shared components go in their own `X.dc.html` files,** like `OutputCard` and `JsonView`. This includes every chart in Section 11.6.
- **Don't edit `support.js`.** If something needs a runtime change, say so in "What to return".

---

## 2. Visual direction

AIHub belongs to the same product family as the existing Relay dashboard and lcpp: a **dense, calm operator console, dark-first**. Use the attached lcpp `tokens.css` / `components.css` / `components.js` as the starting point. Keep the token names, convert `components.js` to an ES module, and add the new components listed in Section 2.1.

| Token | Dark | Use |
| --- | --- | --- |
| `--bg` | `#0B0E14` | page |
| `--bg-sidebar` | `#0D1119` | nav, inputs |
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
| `--accent` | `#FFB224` | amber: primary actions, "starting", "loading" |
| `--cyan` | `#58C4DD` | info, links, "loaded" |
| `--green` | `#3FB950` | ready, healthy |
| `--red` | `#F85149` | failed, destructive |
| `--purple` | `#BC8CFF` | mods/plugins, agent-exposed tools |

- **Light theme**: keep lcpp's `[data-theme="light"]`. Follow `prefers-color-scheme`, with a manual System / Light / Dark toggle saved in `localStorage` (wrapped in try/catch).
- **Type**: IBM Plex Sans for UI. JetBrains Mono for numbers, ports, ids, paths, sizes and logs. Section labels are uppercase 11 px/600 with `.07em` letter-spacing.
- **No per-page colors.** Every page, including mods, uses only tokens and components. This keeps mods visually consistent for free.
- **Motion** is subtle, and all of it respects `prefers-reduced-motion`.

### 2.1 Components to add to the design system

Keep lcpp's set (Button, Badge, Chip, StatusDot, Toggle, Segmented, Field, MemoryMeter, Toast, Banner, Card, Table, Tabs, Kbd, Skeleton, EmptyState, LogLine, NavItem, Dialog) and add:

| Component | Purpose |
| --- | --- |
| `ServiceTile` | Overview tile: icon, name, state, load state, port, memory, up to 4 stats, quick actions |
| `MemoryBar` | Horizontal stacked bar: one segment per service + "other" + free + reserve marker |
| `AudioPlayer` | Play/pause, scrubber, time, download. Optional word-timing hook for karaoke-style highlight (Part B) |
| `ImageView` | Thumbnail and full view with zoom-to-fit |
| `VideoPlayer` | Native `<video>` with poster |
| `Viewer3D` | Interface `Viewer3D({ src, poster })`. In Part A, render the poster with a "3D" badge and a placeholder canvas. A vendored three.js viewer is wired in later, so keep the interface stable |
| `OutputCard` | Kind-aware preview + title + service + time + size |
| `JsonView` | Collapsible, syntax-tinted JSON tree with copy |
| `SchemaForm` | Builds a form from JSON Schema: string, number/integer (min/max), boolean, enum, string arrays (chip input), nested objects (fieldset), binary (file input → multipart). Shows `description` as help text and validates `required` |
| `KeyValueEditor` | Rows of key/value with add/remove |
| `Drawer` | Right-side drawer (bottom sheet on phones) |
| `Menu` / `Popover` | "…" menus and the header popovers |
| `CommandPalette` | `Ctrl/Cmd+K`: fuzzy-jump to any page, service, model or output; run quick actions (start/stop/load/unload) |
| `ConfirmDialog` | States exactly what will happen; destructive variant in red |
| `FilterChips` | Multi-select filter row with counts |
| `Chart` (in `charts.js`) | `line`, `bar`, `stackedBar`, `sparkline`, `donut`. Plain SVG, themable through tokens, with tooltips. **From revision 2 on, this is replaced by the separate `.dc.html` chart components in Section 11.6.** |

---

## 3. Layout and navigation

**Desktop (≥ 1024 px)**: left sidebar + main content. **Tablet and phone**: top bar with a menu button, one-column content, dialogs become full-screen sheets.

**Sidebar**, top to bottom:
1. Logo + "AIHub"
2. **Overview** (default view)
3. **Chat**: present but **disabled** with a "Coming later" tooltip. The shell must leave room for a full-height chat view with a right-hand side panel later, without a redesign.
4. Section label **SERVICES**: **one nav item per service, generated from `api.listServices()`**, in the configured order. Each item has the service icon, its name and a status dot. Mods that failed to load show a red dot and still appear.
5. Section label **LIBRARY**: **Models**, **Outputs**
6. **Settings**
7. Footer: AIHub status dot + version, and a `MOCK` badge in mock mode.

**Persistent header** (every view):
- **Memory meter**: unified memory used / total (this machine shares one memory pool between CPU and GPU). It turns amber above 80% and red above 92%. Clicking it opens a popover with the `MemoryBar` broken down by service.
- **Running jobs chip** ("2 running"), shown only when a service reports jobs. Clicking opens a popover listing them with progress and links.
- **Activity bell**: an unread count, and a popover with the last 30 activity items.
- **Search** button that opens the CommandPalette (`Ctrl/Cmd+K`).

**Toasts** sit bottom-right (bottom-center on phones). Errors stay until dismissed; successes auto-hide after 4 s.

**Hash routes** (reload keeps your place; Back works):
`#/overview`, `#/s/<serviceId>`, `#/s/<serviceId>/<tabId>`, `#/models`, `#/models/<modelId>`, `#/outputs`, `#/outputs/<outputId>`, `#/settings`, `#/settings/<section>`.

---

## 4. Views (Part A)

### 4.1 Overview (home)

- **Alerts strip** (only when present): for example "2 models have missing files", "Mod `broken` has a manifest error", "Speech failed to start". Each has an action link.
- **Services grid**: one `ServiceTile` per service.
  - State: `stopped`, `starting` (amber pulse), `ready` (green), `degraded` (amber), `stopping`, `failed` (red).
  - Load state for services that hold models in memory: `unloaded`, `loading` (amber pulse), `loaded` (cyan), `unloading`. It shows `n/a` for services with no models.
  - Port (mono), memory used (or "~52 GB when loaded" from the estimate), and idle time ("idle 12m").
  - Up to 4 **stats** supplied by the service (e.g. "Voices 3", "Requests today 1,284").
  - Quick actions: Start/Stop, Load/Unload, Open. Destructive actions confirm.
  - A tile for a mod with a manifest error shows the error and a "Show details" link instead of actions.
- **Memory panel**: `MemoryBar` (services + other + free, with the reserve marked), a total line ("33.1 / 121.0 GB · 12 GB reserved"), and a table of services sorted by memory with used, estimate, idle time and whether the AIHub may auto-unload them.
- **Recent outputs**: horizontal strip of the 8 newest `OutputCard`s, plus "View all".
- **Activity**: the latest 15 activity items (time, service icon, text, link).

### 4.2 Service page (frame used by every service, built-in or mod)

**Page header**: icon, name, description, state + load state, port (mono, with copy), version, memory (used / estimate).
- Buttons: **Start/Stop**, **Restart**, **Load/Unload** (only when the service supports it).
- A "…" menu: Copy base URL, Open the service's own API docs ↗ (`<url>/docs`), Open native UI ↗ (only when the service has one, e.g. ComfyUI), Show manifest.

**Tabs**, in order:
1. **Custom tabs** from the service's page module (Section 5), when it has one (`has_page: true`).
2. **Overview**: only when the service has **no** custom page. Shows health (ok + latency + `JsonView` of the health body), stats, memory, the models it uses (links to Models), and its recent outputs.
3. **Outputs**: only when the service has an outputs folder. It reuses the Outputs view with the service filter fixed.
4. **API**: the generic control surface that makes every mod usable with zero UI work.
   - Operations come from `api.listOperations(id)`, grouped by tag, with a filter box. Each row shows the method badge, path (mono) and summary. It also shows a purple **tool** badge when the operation is exposed to the future agent, and a red **destructive** badge.
   - Selecting an operation opens a panel: description, a `SchemaForm` for path/query params and the body, and a **Send** button (destructive operations confirm first).
   - The **response viewer** is chosen by `response` kind: `json` → `JsonView`, `audio` → `AudioPlayer`, `image` → `ImageView`, `video` → `VideoPlayer`, `model3d` → `Viewer3D`, `file` → download link, `stream` → a live log of SSE lines with a Stop button, `empty` → status only. It always shows the HTTP status and timing.
   - A **Copy as curl** button for the request, using the AIHub URL `http://127.0.0.1:7000/api/s/<id><path>`.
5. **Logs**: a live tail with the same behavior as lcpp's logs drawer. Follow toggle (auto-off when the user scrolls up, with a "↓ N new" pill), filter, wrap, copy, download, and a line-count select (200/1000/5000). Lines containing `error`/`failed` are red and `warn` lines are amber.
6. **Settings**: a form for this service's section of `config.toml`.
   - Enabled, autostart, port, idle-unload seconds (or "never"), "AIHub may auto-unload this service to make room", priority (lower is unloaded first), environment overrides (`KeyValueEditor`).
   - Save and Revert, with a "restart required" note where relevant.
   - A read-only **Manifest** card shows the parsed `service.toml` and any manifest errors.

**Service unreachable** (AIHub up, service down): an inline banner on the page ("Speech is not responding on 127.0.0.1:5040") with Start/Restart and a link to Logs. Custom tabs show their own empty state rather than crashing.

**Make room dialog**: when `loadService` is rejected with `needs_room`, show the `plan`. Example: "Loading **3D Generate** needs ~52 GB, 31 GB available. AIHub will unload: **Speech** (frees 9.2 GB, idle 12m) and **Images & Video** (frees 24.0 GB, idle 40m)."
- Buttons: [Cancel] and [Unload & continue].
- If `enough` is false, explain what is still missing and offer only [Cancel].

### 4.3 Models (the registry)

Everything in `data/models/`, from every service, in one place.

- **Summary bar**: total size, a `stackedBar` of size by kind, and disk free.
- **Filter chips** by kind (LLM, TTS, STT, Voice, 3D, Image, Video, Text encoder, VAE, LoRA, Vision, Upscale, Other) with counts. Also filters by service and status, plus a search box (`/` focuses it).
- **Table** columns:
  - name + id (mono)
  - kind badge
  - format (gguf, safetensors, hf-dir, wav)
  - used by (service chips)
  - size
  - status: `ok` (green), `missing` (red), `partial` (amber), `unverified` (dim), `checksum mismatch` (red), `verifying` (amber pulse)
  - source (e.g. `hf: org/repo@rev`)
  - actions: Verify, Edit, Delete
- **Delete** asks whether to remove only the registry entry or the files too. Deleting files is disabled while a running service is using the model.
- **Model drawer** (`#/models/<id>`):
  - files table: role, relative path, size, exists, sha256 (truncated, with copy), verified
  - source / provenance
  - which services use it
  - tags and notes, editable
- **Discovered files**: "Scan for new files" lists files in `data/models/` that are not in the registry. Each shows path, size and a suggested kind/name, with **[Add to registry]**, which opens a small form.

### 4.4 Outputs (everything any service ever produced)

The real backend indexes `outputs/<service>/<YYYY-MM-DD>/…`. This page is the cross-service gallery.

- **Toolbar**:
  - grid/list toggle
  - filter chips by kind (Audio, Image, Video, 3D, Text, Other) and by service, with counts
  - date range: Today / 7 days / 30 days / All / custom
  - search over title and prompt
  - a total line: "412 items · 3.8 GB"
- **Grid**: grouped by day with sticky day headers. Infinite scroll with cursor paging (60 per page).
  - `OutputCard` previews: images show a thumbnail; audio shows a waveform-style bar with an inline play button; 3D shows `preview.png` with a "3D" badge; video shows a poster with duration; text shows the first lines.
  - New outputs arrive live (an `output` event) at the top with a subtle highlight.
- **Detail drawer** (`#/outputs/<id>`):
  - a large preview with the right viewer
  - metadata: service, model, voice, prompt (expandable), seed, params (`JsonView`), created, size, path (mono, copy)
  - the file list for folder outputs, such as a 3D job's `mesh.glb`, `parts/…`, `rigged.glb` and `preview.png`
  - actions: Download, Copy path, Open in service (deep link to that service's page), Delete (confirm; "files are removed from disk")
  - arrow keys move to the previous/next output

### 4.5 Settings

One page with sections (hash `#/settings/<section>`), Save and Revert, an unsaved-changes guard, and restart-required notes:

- **General**:
  - AIHub port (default 7000), with the note "Bound to 127.0.0.1 — this machine only"
  - AIHub version, PID, uptime and memory
- **Paths** (read-only, with sizes and disk free): project root, `data/models`, `data/databases`, `outputs`.
- **Memory**:
  - reserve (GB kept free)
  - "Automatically make room when a service needs memory" toggle; when off, the Make-room dialog asks
  - "Never auto-unload" service multi-select
  - a priority list of services, reordered with up/down buttons (lower is unloaded first)
- **Services**:
  - every folder found in `services/`, including broken mods with their errors
  - per service: enabled toggle, autostart toggle, and sidebar order (up/down)
  - an **"Add a mod"** card explaining the three steps (`bin/aihub new <id>`, edit `services/<id>/service.toml`, restart the AIHub), with a link to the template
- **Interface**: theme (System/Light/Dark), density (Comfortable/Compact).
- **About**: versions, and the CLI equivalents `bin/aihub status`, `bin/aihub start <id>`, `bin/aihub logs <id> -f`, `bin/aihub new <id>`. A **Doctor** panel (plan 12.4) runs `getDoctor()`: the counts, then the warn and fail checks with their fixes, the rest folded; a Run again button. `aihub doctor` prints the same report.

---

## 5. The page-module contract (how a service brings its own UI)

A service may ship `services/<id>/ui/page.js`. The real AIHub serves it at `/ui/services/<id>/page.js`, and the shell loads it with a dynamic `import()` when `has_page` is true. A page module is plain ES and imports the design system from the AIHub:

```js
// services/<id>/ui/page.js
import { Button, Card, Field, AudioPlayer /* … */ } from '/js/components.js';

export default {
  // Shown before the generic Outputs / API / Logs / Settings tabs.
  tabs: [{ id: 'speak', label: 'Speak', icon: 'wave' }, { id: 'voices', label: 'Voices', icon: 'user' }],

  // Render tab ctx.tab into el. May return a cleanup function.
  mount(el, ctx) { /* … */ },
};
```

`ctx` provides:

| Field | What it is |
| --- | --- |
| `ctx.service` | the current `ServiceDetail` (kept fresh by the shell) |
| `ctx.tab`, `ctx.params` | current tab id and hash query params (`#/s/tts/voices?edit=hope`) |
| `ctx.call(method, path, opts)` | shorthand for `api.callService(ctx.service.id, method, path, opts)` |
| `ctx.api` | the full AIHub `api` object (e.g. to list outputs or models) |
| `ctx.ui` | the components module |
| `ctx.toast(msg, level)`, `ctx.confirm({title, body, danger})` | shell helpers |
| `ctx.navigate(route)` | change the hash route |
| `ctx.on(eventType, fn)` | subscribe to AIHub events; returns an unsubscribe function; auto-cleaned on unmount |

Rules: a page module never calls `fetch` directly, never styles with raw colors, and handles "service not running" by showing an `EmptyState` with a Start button.

**As built (plan 2.9).** In the `.dc.html` shell, `web/ModPage.dc.html` hosts every page module: it `import()`s `ServiceSummary.page_url` and calls `mount(el, ctx)` on its own element, remounting when the mod, the tab, the hash params or the running state change. `ctx.ui` is `web/mod-ui.js`, plain DOM helpers that use the theme variables, because the export has no importable `components.js`: `h(tag, attrs, ...children)`, `text`, `row`, `stack`, `card`, `button(label, onClick, {kind})`, `input`, `textarea`, `select`, `field(label, control, hint)`, `json(value)`, `badge(label, tone)`, `empty(title, body, action)` and `table(rows)`. `ctx.on('*', fn)` receives every event. Tab ids can't reuse the generic ones (`overview`, `outputs`, `api`, `logs`, `settings`). If `mount` throws, ModPage shows the error and the other tabs keep working.

**As built (plan 7.7).** The Part B pages are built by hand as `ui/page.js` modules, like revision 2. Two shared modules help: `web/mod-kit.js` (the not-running state, `callRoom` for calls that may need make-room, a segmented control, panels) and `web/mod-charts.js` (mounts the §11.6 chart components into a page module's DOM: `chartCard`, `chart`, `waveform`). In `?mock`, the built-in mods show their real page modules and `mock.js` answers their native API.

**In the `.dc.html` shell (from revision 2 on), a mod's page can come in either of two formats.** Either way, it lives in the mod's own folder.

| Format | Who uses it | How it loads |
|---|---|---|
| **`ui/page.js`**, the ES module above | any mod, with no Claude Design needed | The shell hosts it in a `ModPage.dc.html` component, which calls `mount(el, ctx)` on a ref and runs the cleanup on unmount. |
| **`ui/Page.dc.html`**, a dc component | the built-in mods, whose pages Claude Design draws in Part B | AIHub serves `services/<id>/ui/Page.dc.html` at `./Mod_<id>.dc.html`, and the shell's `<dc-import>` loads it like any other component. backend-plan step 2.9 checks whether `dc-import` accepts a dynamic name. If it doesn't, the shell keeps a small static list of built-in pages. |

The Example mod's **Hello** tab, which v1 built into `Hub.dc.html`, moves out to `services/_template/ui/page.js` as the reference `page.js` module.

**Part A delivers one example module**, `services/_template/ui/page.js`, for the mock service **Example** (Section 7). It has one tab, **Hello**: a name field, a call to `GET /v1/hello?name=…`, and the JSON result in a `Card`. It also shows a toast on errors. This file becomes the template that `bin/aihub new` copies, so keep it short and commented.

---

## 6. The `api` object (exact contract)

These are also the real AIHub's HTTP routes. All methods return Promises that resolve to the documented JSON, or reject with `ApiError { status, detail, code, data }`.

### 6.1 Mode switch

```js
const LIVE = !!window.AIHUB_API_BASE || new URLSearchParams(location.search).has('live');
const BASE = window.AIHUB_API_BASE || '';
export const api = LIVE ? createHttpApi(BASE) : createMockApi();
```

**Updated for progressive wiring (supersedes the block above from revision 2 on).** The backend goes live one area at a time, so the UI uses a **hybrid** API. `web/api.js` is written by us, not by Claude Design, and exports `createApi`:

```js
import { createMockApi } from './mock.js';
import { createApi } from './api.js';
// The real AIHub serves /config.js, which sets AIHUB_API_BASE and AIHUB_LIVE_AREAS.
const areas = window.AIHUB_LIVE_AREAS || [];      // e.g. ['system','services','logs','operations','proxy','events']
const forceMock = new URLSearchParams(location.search).has('mock');
export const api = createApi({ base: window.AIHUB_API_BASE ?? null, liveAreas: forceMock ? [] : areas, mock: createMockApi() });
```

- **Methods in a live area** call HTTP. Everything else answers from the mock.
- **`subscribe`** merges live events for live areas with mock events for the rest.
- **`api.liveAreas`** says which areas are live, so each page section can show a small **MOCK** badge while its area is still mocked. `api.isLive(area)` answers the same for one area.
- **Errors in `callService`:** a non-2xx from the mod rejects with `upstream_error` (`detail` = the mod's message, `data.body` = its body). Hub errors carry an `X-AIHub-Error` header and reject with their own code.

Areas: `system`, `services`, `logs`, `operations`, `proxy` (`callService`), `memory`, `models`, `outputs`, `settings`, `events`, `metrics` (Section 11.7), `widgets` (Section 11.7) and `tools`. The hub also lists `overview` once `GET /api/overview` exists (`getOverview` uses it then).

### 6.2 Methods → endpoints

| Method | HTTP | Returns |
| --- | --- | --- |
| `getOverview()` | `GET /api/overview` | `Overview` |
| `getSystem()` | `GET /api/system` | `System` |
| `listServices()` | `GET /api/services` | `ServiceSummary[]` |
| `getService(id)` | `GET /api/services/{id}` | `ServiceDetail` |
| `startService(id)` | `POST /api/services/{id}/start` | `202 ServiceSummary` (add `?wait=1` to answer once the mod is ready or failed; start/stop/restart all accept it) |
| `stopService(id)` | `POST /api/services/{id}/stop` | `202 ServiceSummary` |
| `restartService(id)` | `POST /api/services/{id}/restart` | `202 ServiceSummary` |
| `loadService(id, {makeRoom})` | `POST /api/services/{id}/load[?make_room=1]` | `202 ServiceSummary`, or `409 {code:"needs_room", detail, data:{plan: MakeRoomPlan}}` |
| `unloadService(id)` | `POST /api/services/{id}/unload` | `202 ServiceSummary` |
| `getServiceLogs(id, lines)` | `GET /api/services/{id}/logs?lines=N` | `{ lines: LogLine[] }` |
| `streamServiceLogs(id, onLine)` | `EventSource /api/services/{id}/logs/stream` | `{ close() }`; each `data:` is a `LogLine` |
| `listOperations(id)` | `GET /api/services/{id}/operations` | `Operation[]` |
| `callService(id, method, path, opts)` | `ANY /api/s/{id}{path}` | `ServiceResponse` (opts: `{ query, json, form, signal, stream, onEvent }`) |
| `saveServiceConfig(id, cfg)` | `PUT /api/services/{id}/config` | `{ config: ServiceConfig, restart_required: boolean }` (send the whole form or a subset; a value equal to the mod's default removes its override, so config.toml only holds real changes) |
| `getMemory()` | `GET /api/memory` | `Memory` |
| `planRoom(id, needsBytes)` | `POST /api/memory/plan` body `{service, needs_bytes}` | `MakeRoomPlan` (`needs_bytes` optional: the mod's estimate or learned peak) |
| `listModels(filter)` | `GET /api/models?kind=&service=&status=&q=` | `{ models: Model[], totals: Totals, disk: Disk }` |
| `getModel(id)` | `GET /api/models/{id}` | `Model` |
| `saveModel(id, patch)` | `PUT /api/models/{id}` body `ModelPatch` | `Model` |
| `verifyModel(id)` | `POST /api/models/{id}/verify[?reset=1]` | `202 Model` (status `verifying`, with `progress`; `model` events update it about once a second; `reset=1` records new checksums instead of comparing) |
| `deleteModel(id, {files})` | `DELETE /api/models/{id}?files=0\|1` | `204` |
| `scanModels()` | `POST /api/models/scan` | `{ discovered: Discovered[] }` |
| `addModel(input)` | `POST /api/models` body `ModelInput` | `201 Model` |
| `listOutputs(filter)` | `GET /api/outputs?service=&kind=&q=&from=&to=&cursor=&limit=` | `OutputPage` (`service` and `kind` are comma-separated lists; `q` matches every word; `limit` 1–500, default 60) |
| `getOutput(id)` | `GET /api/outputs/{id}` | `Output` |
| `deleteOutput(id)` | `DELETE /api/outputs/{id}` | `204`; the output moves to `outputs/.trash/`, emptied after 30 days |
| `uploadOutput(file)` | `POST /api/outputs/upload?name=` (the file as the body) | `Output` (`201`); `upload_type` 415, `upload_too_large` 413 (64 MB), `upload_empty` 400 |
| `getSettings()` | `GET /api/settings` | `Settings` (`services.order` and `memory.priority` list every installed mod: the configured ids first, then the rest in sidebar order) |
| `saveSettings(s)` | `PUT /api/settings` | `{ settings: Settings, restart_required: boolean }` (send the whole form or any part; what is left out stays as it is, and only changed values are written. A bad value is `422 invalid_config` with `data.field`, e.g. `"hub.port"` for a port a mod uses; nothing is written) |
| `subscribe(onEvent)` | `EventSource /api/events` | `{ close() }`; each `data:` is a `HubEvent` |

File and preview URLs (`Output.url`, `Output.preview`) are plain GETs used directly in `<img>`, `<audio>`, `<video>` and download links.

### 6.3 Error codes to handle

`service_not_found`, `service_not_running`, `service_failed`, `service_disabled` (start on a disabled mod), `external_service` (start/stop on a `kind = "external"` mod), `manifest_invalid`, `port_in_use`, `needs_room`, `not_unloadable`, `model_not_found`, `model_in_use`, `model_exists` (adding a model whose id or files are already registered), `model_files_missing` (verify on a model with no files on disk), `registry_invalid` (registry.json can't be read; changes are refused until it is fixed), `output_not_found`, `output_not_deletable` (the output resolves outside `outputs/`, e.g. through a symlinked folder), `invalid_config` (422: a settings save that would break config.toml, e.g. a port clash; nothing is written), `upstream_error` (the service itself returned an error; `detail` carries its message), `widget_not_found`, `widget_invalid` (a mod's widget data doesn't match `WidgetData`), `hub_error`. Generic HTTP errors use `not_found` (404), `method_not_allowed` (405) and `invalid_request` (422, a request body or query that fails validation; `data.errors` lists `{loc, msg}`).

### 6.4 Types

```ts
type ServiceState = "stopped" | "starting" | "ready" | "degraded" | "stopping" | "failed";
type LoadState = "unloaded" | "loading" | "loaded" | "unloading" | "n/a";

interface Stat { label: string; value: number | string; unit?: string; hint?: string;
                reset?: "daily";        // a counter that starts again each day ("… today")
                series?: string }       // numeric stats: the metric it is recorded as (svc.<id>.stat.<slug>), for sparklines

interface ServiceSummary {
  id: string;                    // folder name under services/, e.g. "tts"
  name: string;                  // "Speech"
  description: string;
  icon: string;                  // icon key from components.js
  version: string | null;
  kind: "process" | "external";  // external = AIHub does not launch it; it only health-checks and proxies it
  port: number;
  url: string;                   // "http://127.0.0.1:5040"
  state: ServiceState;
  state_since: number;           // unix seconds
  load: LoadState;
  idle_s: number | null;
  busy: boolean;                 // from the mod's status route; false without one
  memory: { used_bytes: number; estimate_bytes: number | null; peak_bytes: number | null };
  stats: Stat[];                 // ≤ 4
  has_page: boolean;
  page_url: string | null;       // where the shell loads the page: /ui/services/<id>/page.js or /Mod_<id>.dc.html
  has_outputs: boolean;
  native_ui: string | null;      // URL of the service's own UI, if any
  enabled: boolean;
  autostart: boolean;
  last_error: string | null;
  manifest_errors: string[];     // non-empty → state "failed", not startable
}

interface ServiceDetail extends ServiceSummary {
  pid: number | null;
  started_ts: number | null;
  command: string[];
  folder: string;                // "services/tts"
  outputs_dir: string | null;    // "outputs/tts"
  models: string[];              // registry ids
  health: { ok: boolean; latency_ms: number | null; body: unknown; status?: number } | null;  // status = HTTP code (absent for tcp checks)
  manifest: Record<string, unknown>;   // parsed service.toml
  config: ServiceConfig;
  jobs: Job[];                   // from the status route
  in_flight: number;             // proxied requests in progress
  last_request_ts: number | null;
}

interface ServiceConfig {
  enabled: boolean; autostart: boolean; port: number;
  idle_unload_s: number | null;  // null = never
  auto_unload: boolean;          // AIHub may unload it to make room
  priority: number;              // lower = unloaded first
  env: Record<string, string>;
}

interface Operation {
  id: string;                    // "post_v1_speech"
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;                  // native path, e.g. "/v1/speech"
  summary: string; description: string; tag: string;
  params: { name: string; in: "path" | "query"; required: boolean; schema: object; description?: string }[];
  body: { content_type: "application/json" | "multipart/form-data"; schema: object } | null;
  response: "json" | "audio" | "image" | "video" | "model3d" | "file" | "stream" | "empty";
  destructive: boolean;
  tool: { name: string; confirm: boolean } | null;   // exposed to the future agent
}

interface ServiceResponse {
  status: number; ok: boolean; ms: number; content_type: string;
  json?: unknown; text?: string; blob?: Blob; url?: string;   // url = object URL for media blobs
}

interface Memory {
  total_bytes: number; used_bytes: number; available_bytes: number; reserve_bytes: number;
  gpu: { name: string; vram_total_bytes: number; vram_used_bytes: number;
         gtt_total_bytes: number; gtt_used_bytes: number } | null;
  by_service: { id: string; used_bytes: number; estimate_bytes: number | null; load: LoadState;
                idle_s: number | null; auto_unload: boolean; priority: number }[];
  other_bytes: number;           // OS, desktop, browser — anything the AIHub does not own
}

interface MakeRoomPlan {
  service: string; needs_bytes: number; available_bytes: number;   // available = MemAvailable − reserve − other loads' reservations
  unload: { id: string; frees_bytes: number; reason: string }[];  // reason: "priority 1, idle 12m"
  enough: boolean;
}

type ModelKind = "llm" | "tts" | "stt" | "voice" | "3d" | "image" | "video" | "text-encoder"
               | "vae" | "lora" | "vision" | "upscale" | "other";
type ModelStatus = "ok" | "missing" | "partial" | "unverified" | "checksum_mismatch" | "verifying";

interface Model {
  id: string; name: string; kind: ModelKind; format: string;
  services: string[];
  path: string;                  // relative to data/models/
  files: { path: string; role: string; size_bytes: number | null; exists: boolean;
           sha256: string | null; verified: boolean }[];
  size_bytes: number;
  status: ModelStatus; problems: string[];
  source: { type: "huggingface" | "url" | "local" | "created";
            repo?: string; revision?: string; url?: string; note?: string } | null;
  added_ts: number; tags: string[]; notes: string;
  progress?: number;             // 0–1, only while status is "verifying"
}
type ModelPatch = Partial<Pick<Model, "name" | "kind" | "services" | "source" | "tags" | "notes">>;
interface ModelInput { path: string; kind: ModelKind; name: string; services?: string[]; source?: Model["source"];
                      id?: string; files?: { path: string; role: string; sha256?: string }[]; format?: string; tags?: string[]; notes?: string }
interface Discovered { path: string; size_bytes: number; suggested_kind: ModelKind; suggested_name: string;
                       suggested_id: string; format: string; files: { path: string; role: string; size_bytes: number | null }[]; source?: Model["source"] }
interface Totals { size_bytes: number; count: number; by_kind: Record<string, { count: number; size_bytes: number }> }
interface Disk { free_bytes: number; total_bytes: number }

type OutputKind = "audio" | "image" | "video" | "model3d" | "text" | "archive" | "other";
interface Output {
  id: string;
  service: string;
  kind: OutputKind;
  title: string;
  path: string;                  // "outputs/tts/2026-10-04/143012-good-morning.wav" (file or folder)
  files: { path: string; kind: OutputKind; size_bytes: number; role?: string }[];
  url: string;                   // main file
  preview: string | null;        // thumbnail / poster
  size_bytes: number;
  created_ts: number;
  duration_s?: number;
  dims?: { w: number; h: number };
  meta: { prompt?: string; model?: string; voice?: string; seed?: number;
          params?: Record<string, unknown>;
          excerpt?: string;          // text outputs without a prompt: their first lines, for the card
          [k: string]: unknown };
}
interface OutputPage {
  items: Output[]; next_cursor: string | null;
  totals: { count: number; size_bytes: number;
            by_kind: Record<OutputKind, number>;      // counts with every filter except kind
            by_service: Record<string, number> };     // counts with every filter except service
}

interface Activity { id: string; ts: number; service: string | null;
                     level: "info" | "warn" | "error"; text: string; route?: string }
interface Alert { id: string; level: "warn" | "error"; text: string; service?: string;
                  action?: { label: string; route: string } }
interface Job { id: string; service: string; label: string; progress: number | null;  // 0..1
                state: "queued" | "running" | "done" | "failed" | "cancelled"; route?: string }

interface System {
  hub: { version: string; pid: number; uptime_s: number; rss_bytes: number; port: number };
  paths: { root: string; models: string; databases: string; outputs: string; logs: string; state: string };   // logs, state: data/logs, data/state (Phase 16)
  usage: { models_bytes: number; databases_bytes: number; outputs_bytes: number; logs_bytes: number; state_bytes: number };
  disk: Disk;
}

interface Overview {
  services: ServiceSummary[]; memory: Memory; recent_outputs: Output[];
  activity: Activity[]; alerts: Alert[]; jobs: Job[]; system: System;
}

interface Settings {
  hub: { port: number };          // 1024–65535; a change applies after AIHub restarts (restart_required)
  memory: { reserve_gb: number; auto_make_room: boolean; never_unload: string[]; priority: string[] };
  services: { order: string[]; enabled: Record<string, boolean>; autostart: Record<string, boolean> };
  ui: { theme: "system" | "light" | "dark"; density: "comfortable" | "compact";   // compact is the default
        dashboard: { order: string[]; hidden: string[]; ranges: Record<string, string> } };   // Customize (§11.5), saved in config.toml
  learning: { enabled: boolean;   // plan 21: preferences on the cards and the learner; off = nothing filled or learned
              nightly_at: string; idle_min: number; infer_after: number; fade_days: number };
}

type HubEvent =
  | { type: "service"; service: ServiceSummary }
  | { type: "memory"; memory: Memory }
  | { type: "output"; output: Output }
  | { type: "output_deleted"; id: string }
  | { type: "model"; model: Model }
  | { type: "model_deleted"; id: string }
  | { type: "activity"; item: Activity }
  | { type: "job"; job: Job }
  | { type: "alert"; alert: Alert }
  | { type: "alert_cleared"; id: string }
  | { type: "resync" };            // events were dropped (slow client): refetch everything

interface LogLine { ts: number; text: string; stream: "stdout" | "stderr" }
```

---

## 7. Mock API requirements (must feel real)

The mock keeps in-memory state, applies the same validation rules, emits `HubEvent`s through `subscribe`, and simulates time. **The seed data is this real machine; use it.**

**System**: AMD Ryzen AI MAX+ 395. Unified memory 121.0 GB total (~33 GB used at start). GPU "AMD Radeon 8060S (Strix Halo)": VRAM 4.0 GB, GTT 121.5 GB. Disk 952 GB with 450 GB free. AIHub v0.1.0 on port 7000, RSS ~90 MB.

**Services** (sidebar order as listed):

| id | name | port | kind | initial state | load | memory | stats | page |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `relay` | LLM Relay | 4000 | process | ready | n/a | 0.2 GB | Requests today 1,284 · Tokens today 3.1 M · p50 TTFT 412 ms · Endpoints 2/3 healthy | `false` in Part A |
| `lcpp` | LLM Launcher | 7710 | process | ready | loaded | 18.6 GB (one instance, `gemma4-26B-7071`) | Running 1 · Catalog 4 · On disk 20.9 GB | `false` in Part A |
| `tts` | Speech | 5040 | process | ready | unloaded | est. 9.2 GB | Voices 3 · Engines 2 · Clips today 12 | `false` in Part A |
| `gen3d` | 3D Generate | 5050 | process | ready | unloaded | est. 52 GB peak | Jobs 17 · Queue 0 | `false` in Part A |
| `comfy` | Images & Video | 5070 | process | ready | unloaded (ComfyUI itself not running) | est. 24 GB | Workflows 9 | `false`; `native_ui` = `http://127.0.0.1:8199/` (ComfyUI's own editor) |
| `example` | Example | 5100 | process | ready | n/a | 0.05 GB | Calls 0 | **`true`** (the `_template` page module) |

Each service has a realistic `listOperations` result. Use these, with plausible JSON-schema bodies:
- **tts**: `GET /health`, `GET /v1/voices`, `POST /v1/voices` (multipart: `name`, `file` binary, optional `transcript`), `POST /v1/voices/design`, `DELETE /v1/voices/{name}` (destructive, tool with confirm), `POST /v1/speech` (json → audio, tool `speak`), `POST /v1/audio/speech` (OpenAI-compatible, audio), `POST /v1/enhance`, `POST /v1/load`, `POST /v1/unload`.
  - In the mock, `POST /v1/speech` returns a short generated WAV (a soft tone sequence built in JS), so the `AudioPlayer` really plays.
- **gen3d**: `GET /v1/presets`, `POST /v1/estimate`, `POST /v1/jobs` (tool `make_3d`), `GET /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel` (destructive), `GET /v1/events` (stream).
- **lcpp**: `GET /api/overview`, `GET /api/models`, `POST /api/instances` (tool `start_llm`), `DELETE /api/instances/{name}` (destructive, tool with confirm), `GET /api/instances/{name}/logs/stream` (stream).
- **relay**: `GET /admin/stats/summary`, `GET /admin/stats/by-model`, `GET /admin/endpoints`, `GET /v1/models`, `POST /v1/chat/completions` (stream).
- **comfy** (a small adapter in front of ComfyUI): `GET /health`, `GET /v1/workflows`, `GET /v1/workflows/{name}`, `POST /v1/run` (json → json with a job id; tool `run_workflow`), `GET /v1/queue`, `POST /v1/queue/{id}/cancel` (destructive), `POST /v1/load` (starts ComfyUI), `POST /v1/unload` (frees its models).
- **example**: `GET /v1/hello?name=` → `{"message":"Hello, <name>!"}`, `POST /v1/echo` (json → json).

**Models registry** (sizes in bytes; paths relative to `data/models/`):

| id | kind | format | services | files / size | status |
| --- | --- | --- | --- | --- | --- |
| `gemma-4-26b-it` | llm | gguf | lcpp | `llm/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf` 16,796,015,520 · `mmproj-…BF16.gguf` (role mmproj) 1,194,827,776 · `mtp-gemma-4-26B-A4B-it.gguf` (role draft) 251,937,728 | ok |
| `minicpm-5-2b` | llm | gguf | lcpp | `llm/MiniCPM5-2B/MiniCPM5-2B-Q8_0.gguf` 2,679,710,688 | ok |
| `gemma-4-e4b-it` | llm | gguf | lcpp | `llm/Gemma4-E4B/…` | **missing** |
| `ornith1-35b` | llm | gguf | lcpp | `llm/Ornith1-35B/…` | **missing** |
| `breeze-tts-2` | tts | hf-dir | tts | `tts/breeze-tts-2/` 7,683,637,993 | ok |
| `kokoro-82m` | tts | hf-dir | tts | `tts/kokoro-82m/` ≈ 316,000,000 | unverified |
| `whisper-large-v3-turbo` | stt | hf-dir | tts | `stt/whisper-large-v3-turbo/` 1,622,443,975 | ok |
| `voice-brendon`, `voice-hope`, `voice-arabella` | voice | wav | tts | `voices/<slug>/reference.wav` + `voice.json`, ≈ 1.6 MB each; Brendon is 22.2 s (others ≈ 15–18 s) | ok (source `created`) |
| `cube3d-v0.5` | 3d | hf-dir | gen3d | `3d/cube3d-v0.5/` 8,269,343,812 | ok |
| `cubepart` | 3d | hf-dir | gen3d | `3d/cubepart/` 9,903,728,196 | ok |
| `qwen3-vl-4b-instruct` | text-encoder | hf-dir | gen3d | `3d/Qwen3-VL-4B-Instruct/` 8,887,284,080 | ok |
| `clip-vit-large-patch14` | text-encoder | hf-dir | gen3d | `3d/clip-vit-large-patch14/` 1,714,256,474 | ok |
| `z-image-turbo-fp8` | image | safetensors | comfy | `comfyui/diffusion_models/z_image_turbo_fp8_e4m3fn.safetensors` 6,154,958,896 | ok |
| `qwen-image-2.1-fp8` | image | safetensors | comfy | `comfyui/diffusion_models/qwen-image-2.1-UC-fp8.safetensors` 7,116,818,183 | ok |
| `qwen-image-2.1-q8` | image | gguf | comfy | `comfyui/diffusion_models/qwen-image-2.1-UC-Q8_0.gguf` 7,591,557,920 | unverified |
| `wan2.1-t2v-14b-fp8` | video | safetensors | comfy | `comfyui/diffusion_models/wan2.1_t2v_14B_fp8_e4m3fn.safetensors` 14,289,605,920 | ok |
| `wan2.1-i2v-480p-14b-fp8` | video | safetensors | comfy | `comfyui/diffusion_models/wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors` 16,397,245,448 | ok |
| `scail-2-q8` | video | gguf | comfy | `comfyui/unet/SCAIL-2-Q80.gguf` 17,666,268,832 | ok |
| `qwen3vl-8b-bf16` | text-encoder | safetensors | comfy | `comfyui/text_encoders/qwen3vl_8b_bf16.safetensors` 17,534,334,616 | ok |
| `umt5-xxl-enc-fp8` | text-encoder | safetensors | comfy | `comfyui/text_encoders/umt5-xxl-enc-fp8_e4m3fn.safetensors` 6,731,333,792 | ok |
| `qwen-3-4b` | text-encoder | safetensors | comfy | `comfyui/text_encoders/qwen_3_4b.safetensors` 8,044,982,048 | ok |
| `wan-2.1-vae` | vae | safetensors | comfy | `comfyui/vae/wan_2.1_vae.safetensors` 253,815,318 | ok |
| `qwen-image-2.1-vae` | vae | safetensors | comfy | `comfyui/vae/qwen_image_2.1_vae_bf16.safetensors` 675,509,688 | ok |
| `wan21-lightx2v-lora` | lora | safetensors | comfy | `comfyui/loras/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors` 739,472,104 | ok |
| `zit-watercolor` | lora | safetensors | comfy | `comfyui/loras/zit_watercolor.safetensors` 170,129,432 | ok |
| `clip-vision-h` | vision | safetensors | comfy | `comfyui/clip_vision/clip_vision_h.safetensors` 1,264,219,396 | ok |
| `remacri-4x` | upscale | safetensors | comfy | `comfyui/upscale_models/4x_foolhardy_Remacri.safetensors` 66,864,028 | ok |

Sources: give the LLMs and HF-dir models plausible `huggingface` sources with a revision. `kokoro-82m`, `qwen-image-2.1-q8` and the voices have no checksum yet. **Discovered** (not yet registered): `comfyui/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6,735,906,897) and `comfyui/checkpoints/sam3.1_multiplex_fp16.safetensors` (1,745,546,848).

**Outputs**: generate about 120 items over the last 30 days.
- **tts**: wav/mp3 clips in the voices Brendon / Hope / Arabella / Kokoro `af_heart`, with short sentences as prompts.
- **gen3d**: folder outputs with `mesh.glb`, `parts/part_00_base.glb…`, `rigged.glb` and `preview.png`. Prompts like "low-poly fox", "wooden armchair", "sci-fi supply crate".
- **comfy**: images named like `ComfyUI_00012_.png` (1024×1024 and 1344×768), a few Wan 2.1 videos (5 s, 832×480), and prompts in `meta`.
- **lcpp/relay**: none.

Thumbnails and posters are generated client-side (SVG gradients or canvas with a subtle pattern; no remote images). Audio URLs are generated WAV blobs.

**Simulated behavior**:
- **Start**: `stopped → starting → ready` after 1.5–4 s, with matching log lines and `service` + `activity` events. **Stop**: `stopping → stopped` after 1 s.
- **Load**: `loading → loaded`. Memory grows to the estimate over 2–6 s. **Unload** frees it.
- **Idle unload**: `tts` auto-unloads after a simulated idle period (shortened at ×5 speed) and posts an activity item.
- **Make room**: loading `gen3d` (needs 52 GB) while `lcpp` holds 18.6 GB and `comfy` is loaded (24 GB) returns `needs_room` with a plan to unload `comfy` (and `tts` if loaded). `lcpp` is in `never_unload`, so it is never in a plan. With `make_room=1`, the plan's services unload first, then the load proceeds.
- **Jobs**: calling `POST /v1/jobs` on gen3d creates a job that moves through its stages (shape → parts → rig → preview) over about 20 s with `job` events, then emits a new `output`. `POST /v1/speech` on tts emits an `output` immediately.
- **Verify model**: `verifying` for 3 s, then `ok`. `qwen-image-2.1-q8` ends as `checksum_mismatch`.
- **Delete output** removes it and emits `output_deleted`.

**Mock scenario panel** (mock only, `Shift+D`):
- AIHub down: every call rejects; show a full-width banner "AIHub not responding at 127.0.0.1:7000" with a retry countdown and the hint `bin/aihub start`.
- Fail a service: pick one; it goes to `failed` with an error and log lines.
- Memory pressure: preload `comfy` and `tts` so the make-room path triggers.
- Install a broken mod: add service `broken` with `manifest_errors: ["service.toml: missing [run].port"]`.
- Install a mod with no page: add service `transcribe` (port 5060, ops `POST /v1/transcribe` multipart audio → json), so the generic Overview/API tabs are exercised.
- Outputs: Empty / Seed / Many (2,000 items, to test paging).
- Speed ×1 / ×5.

---

## 8. States checklist (each must be designed and reachable)

- First load: skeleton, then data. AIHub down banner and its recovery. A dropped event stream while the hub still answers is not "down": the UI checks with `GET /api/overview`, reopens the stream and refetches without the banner (Firefox drops quiet connections whenever a network interface changes); a failed check or a second drop within 10 s shows the banner.
- Overview: alerts present and absent; every service state and load state; manifest-error tile; empty recent outputs.
- Service page: custom page (Example), generic page (Transcribe), service stopped, service unreachable, starting, failed with log excerpt, service with a native UI link (Images & Video → ComfyUI).
- API tab: JSON response, audio response, image response, stream response with Stop, error response (`upstream_error`), destructive confirm, multipart file upload form.
- Make room: enough (unload & continue), not enough (cancel only).
- Logs: streaming, follow paused with "N new", filter with no matches, empty.
- Models: every status; filters with zero results; drawer; discovered list; delete blocked (in use); verify in progress.
- Outputs: grid and list; each kind's preview; detail drawer for a folder output (3D); live arrival; Empty and Many (2,000).
- Settings: dirty with unsaved-changes guard, saved with restart-required note, invalid value, broken mod listed.
- Command palette with results and with none.
- Phone width (360 px) for every view, and both themes for every view.

---

## 9. Acceptance criteria

1. Opening `index.html` from any static server shows the seeded app in mock mode, and every control does something real against the mock.
2. Setting `window.AIHUB_API_BASE = ''` (or `?live`) switches to the HTTP endpoints in Section 6 with no other code changes.
3. **Adding a seventh service to the mock seed with no page module produces a fully usable sidebar item, overview tile and service page with zero UI code changes.**
4. The Example page module uses only `ctx` and `components.js`; it never calls `fetch` and uses no raw colors.
5. No console errors in normal use. No horizontal page scroll at 360 px.
6. Dark and light themes both pass WCAG 2.1 AA contrast. Full keyboard operation with visible focus rings, real `<button>`/`<input>`/`<dialog>` semantics, `aria-live="polite"` for status changes and toasts, and status is never conveyed by color alone.
7. No polling while the tab is hidden. Live data arrives through `subscribe`, with a 10 s `getOverview()` poll only as a fallback when the event stream drops.
8. Every Section 8 state is reachable through normal use or the `Shift+D` panel.

## 10. What to return

- The `web/` folder exactly as in Section 1, plus `services/_template/ui/page.js`.
- A short list of any API changes you found necessary, as a diff against Section 6.
- Open design questions.

---

## 11. Part A revision 2 — compact and graphical (built by hand in plan 6.5)

> Give Claude Design the **current `web/` folder** (the v1 export with AIHub's edits, listed in `web/PATCHES.md`), Section 6 and this section. **Change only what this section asks for.** Everything the current UI already does stays as it is.

### 11.1 Keep from v1
- **Layout:** the shell (sidebar, header with memory meter, jobs chip, activity bell and search), routes, the command palette, toasts, dialogs and the `Shift+D` mock panel.
- **Service pages:** every service-page tab, including the API explorer with its response viewers and Make room.
- **Other pages:** Models (table, drawer, scan, verify, delete), Outputs (grid/list, day groups, detail drawer, audio player) and Settings.
- **Components:** `OutputCard` and `JsonView`.
- **Look:** the light and dark tokens, and the accessibility work.

### 11.2 Housekeeping
- **Fold in AIHub's edits:** everything listed in `web/PATCHES.md` (edits 1–9: the hybrid API switch, the real version, MOCK notes, page modules through `ModPage`, model events and verify progress, live outputs in the drawer, Make room from the API tab) becomes part of the export, so that list can go back to empty. Keep `api.js`, `mod-ui.js` and `ModPage.dc.html` as they are (they are AIHub's, not the export's), and never change `support.js`.
- **No raw-template requests:** markup with `{{ … }}` in `src`, `poster` or SVG `d` attributes makes the browser fetch or parse it before `support.js` renders it (404s and console errors today). Avoid it, for example by wrapping such markup in `<template>`.
- **Renames:** "Hub" → **AIHub** everywhere (logo text, titles, the down banner). `bin/hub` → `aihub` (CLI hints in the banner, Settings → About, and the "Add a mod" card).
- **Data source:** replace the hard-coded `import('mock.js')` with the hybrid switch in Section 6.1.
- **MOCK badges:** show a small **MOCK** badge on any page section whose area isn't in `api.liveAreas`. The footer MOCK button stays, for the scenario panel.
- **Example mod:** move its Hello tab out to the page-module mechanism (Section 5).

### 11.3 Compact by default
**Make `compact` the default density** (`comfortable` stays as an option) with these targets:

| Element | v1 | Compact target |
|---|---|---|
| Sidebar width | 240 px | 208 px |
| Header height | 52 px | 44 px |
| Base font | 13 px | 12.5 px (labels 11 px) |
| Page padding | ~28 px | 14–18 px |
| Section gap | 20–22 px | 12–14 px |
| Card padding | 16 px | 10–12 px |
| Service tile min width | 290 px | 230 px (4 columns at 1440 px) |
| Service tile height | ~210 px | ≤ 130 px |
| Table row | ~38 px | 30 px |
| Buttons in tiles | text buttons | 28 px icon buttons with tooltips; text appears only in comfortable |

**Compact service tiles:**
- **Row 1:** icon, name, state badge, and a ⋯ menu.
- **Row 2:** port, load state, memory, and idle time on one mono line.
- **Row 3:** up to 4 stats in one row, each with a **sparkline** of its last 24 h when the stat is numeric.
- **Actions:** icon buttons on hover or focus. They stay visible on touch screens.

**Above-the-fold rule:** at 1440 × 900 in compact, the Overview Dashboard view shows all of these with no scrolling:
- the KPI strip
- every service (as tiles or the mini service table)
- at least two charts
- the alerts

### 11.4 Overview has four views
A segmented control at the top right of the Overview switches views. The choice is kept in the URL (`#/overview?view=dashboard`) and in `localStorage`.

| View | What it shows |
|---|---|
| **Dashboard** (default) | A KPI strip, then a grid of widgets (Section 11.5) |
| **Services** | v1's tiles in the compact form above, with sparklines |
| **Table** | One dense row per service: state, load, a memory bar with the number, a 1 h memory sparkline, idle time, running jobs, last error (truncated) and quick actions. Columns can be sorted. |
| **Timeline** | One swimlane per service over 1 h / 6 h / 24 h / 7 d (Section 11.6, `Timeline`). Each lane shows state bands (stopped, starting, ready, failed), when models were loaded, jobs as bars, outputs as dots, and warning/error markers. Hover for details; click to jump to the service, job or output. |

### 11.5 Dashboard widgets
Each widget is a card with a title, a range selector where it makes sense (1h · 6h · 24h · 7d · 30d), and a ⋯ menu ("View as table", "Open page"). A **Customize** button lets you show, hide and reorder widgets. The layout is saved in Settings (`Settings.ui.dashboard`: widget order, hidden widgets and each widget's range), so it follows you between browsers. The grid uses 12 columns: widgets span 3, 4, 6 or 12 columns and collapse to one column under 760 px.

| # | Widget | Chart | Data |
|---|---|---|---|
| 1 | **KPI strip** (always first) | number tiles with a delta and sparkline | memory used/total, services ready x/y, models loaded, jobs running, outputs today, LLM tokens today |
| 2 | Memory over time | stacked area per service + "other", reserve line, available line | `getMetrics(mem.svc.*, mem.other, mem.reserve)` |
| 3 | Memory now | donut per service + free, total in the center | `getMemory()` |
| 4 | GPU memory (GTT) | line | `getMetrics(gpu.gtt_used)` |
| 5 | Outputs per day | stacked bars by kind, 30 d | `getOutputStats({by:'day'})` |
| 6 | Outputs by service | horizontal bars, with the range selector | `getOutputStats({by:'service'})` |
| 7 | Activity heatmap | hour of day × last 14 days, color = count, red tint for errors | `getActivityStats()` |
| 8 | LLM traffic | requests/hour bars + tokens/hour line + p50 TTFT line (second axis) | the relay mod's widget (`getWidget('relay','traffic')`) |
| 9 | Jobs | running/queued now + duration per service (p50/p90 bars), 7 d | `getJobStats()` |
| 10 | Model storage | treemap (or donut) of size by kind, plus disk free | `listModels()` totals |
| 11 | Service uptime | a 24 h state strip per service, a mini version of Timeline | `getTimeline({range:'24h'})` |
| 12 | Mod widgets | any widget a mod declares (Section 11.7) | `listWidgets()` / `getWidget()` |
| 13 | Recent outputs | v1's strip with compact cards | as v1 |
| 14 | Activity feed | v1's list, compact, with level filter chips | as v1 |

Alerts stay above the grid; they aren't a widget.

### 11.6 Chart components (`.dc.html`, no chart library)

Add these as separate components, drawn in plain SVG:
- `AreaChart` (stacked or not)
- `LineChart` (up to 2 y-axes)
- `BarChart` (vertical or horizontal, stacked or grouped)
- `Donut`
- `Sparkline`
- `Heatmap`
- `Treemap`
- `Timeline` (swimlanes with bands, bars, dots and markers)
- `KpiTile`

What every chart must do:
- Use the `SERIES` colors and the tone tokens, so it works in both themes.
- Size itself to its container (ResizeObserver).
- Show a crosshair and tooltip on hover, with the same readout when navigating with the keyboard.
- Let you click legend items to hide or show a series.
- Format time on the axis in local time: `HH:mm` for ranges under 24 h, `ddd HH:mm` up to 7 d, `MMM d` above that.
- Format bytes and durations like the rest of the UI.
- Have loading (skeleton), empty ("No data in this range") and error (with a retry) states.
- Carry `role="img"`, an `aria-label` summary, and a **"View as table"** option that shows the same data as an accessible table.
- Respect `prefers-reduced-motion`.

### 11.7 New `api` methods (add to Section 6.2)

| Method | HTTP | Returns |
|---|---|---|
| `getMetrics({series, range, step})` | `GET /api/metrics?series=a,b&range=1h\|6h\|24h\|7d\|30d&step=` | `Metrics` |
| `listMetricSeries()` | `GET /api/metrics/series` | `SeriesInfo[]` |
| `getTimeline({range, services})` | `GET /api/timeline?range=&services=` | `Timeline` |
| `getOutputStats({range, by})` | `GET /api/outputs/stats?range=30d&by=day\|service\|kind` | `{ buckets: OutputBucket[] }` |
| `getActivityStats({range})` | `GET /api/activity/stats?range=14d` | `{ cells: { day: string; hour: number; count: number; errors: number }[] }` |
| `getJobStats({range})` | `GET /api/jobs/stats?range=7d` | `{ by_service: { service: string; count: number; failed: number; p50_s: number; p90_s: number; max_s: number }[] }` |
| `listWidgets()` | `GET /api/widgets` | `WidgetInfo[]` |
| `getWidget(service, id, {range})` | `GET /api/widgets/{service}/{id}?range=` | `WidgetData` |
| `getDoctor()` | `GET /api/doctor` | `Doctor` (plan 12.4; Settings → About) |

```ts
// Series names: "mem.total" "mem.used" "mem.available" "mem.reserve" "mem.other" "gpu.gtt_used"
//               "mem.svc.<id>" "jobs.running" "svc.<id>.stat.<slug>" (any numeric stat a mod reports)
// Series names may end in ".*" to request a whole family, e.g. "mem.svc.*".
interface Metrics { range: string; step_s: number; t: number[];            // unix seconds, one per bucket
                    series: Record<string, (number | null)[]> }             // null = no sample in that bucket
interface SeriesInfo { name: string; label: string; unit: "bytes" | "count" | "seconds" | "ms" | "ratio" | string; service?: string;
                     reset?: "daily" }   // a counter that resets each day: a null marks the reset
interface Timeline { from: number; to: number; lanes: {
  service: string;
  states: { from: number; to: number; state: ServiceState }[];
  loaded: { from: number; to: number }[];
  jobs: { id: string; label: string; from: number; to: number | null; state: Job["state"] }[];
  outputs: { ts: number; id: string; kind: OutputKind }[];
  events: { ts: number; level: "warn" | "error"; text: string }[] }[] }
interface OutputBucket { key: string; count: number; size_bytes: number; by_kind: Partial<Record<OutputKind, number>> }
interface WidgetInfo { service: string; id: string; title: string; kind: "line" | "area" | "bar" | "donut" | "number" | "table";
                       ranges: string[]; span: 3 | 4 | 6 | 12 }
interface DoctorCheck { area: "models" | "manifests" | "paths" | "ports" | "units" | "disk" | "offline";
                       level: "ok" | "note" | "warn" | "fail"; title: string; detail: string; fix?: string }
interface Doctor { ts: number; ok: boolean;                                  // ok = no "fail" checks
                   counts: { ok: number; note: number; warn: number; fail: number }; checks: DoctorCheck[] }
interface WidgetData { unit?: string; t?: number[]; categories?: string[];
                       series: { name: string; values: (number | null)[]; axis?: "left" | "right" }[];
                       rows?: Record<string, string | number>[] }   // for kind "table"
```

**Mods declare widgets in their `service.toml`** (see architecture §4), and AIHub proxies and caches them for 30 s. Each `ServiceSummary.stats[i]` also gains an optional `series` field (the metric name), so tiles can draw sparklines.

**As built (plan 6.2):**
- `getMetrics`: `series` is required; unknown names come back all `null`. Default `step` per range: 1h → 10 s, 6h → 60 s, 24h → 5 min, 7d → 30 min, 30d → 2 h (any `step` is rounded to the table's resolution, at most 2000 points). Ranges are `1h 6h 24h 7d 14d 30d` or any `<n>m|h|d` up to 400 d.
- `getOutputStats({by:'day'})` returns every local day in the range, zeros included; `by:'service'|'kind'` returns only non-empty buckets, largest first.
- `getActivityStats` returns every day × hour cell in the range (zeros included); `errors` counts `error`-level items.
- `getJobStats` counts jobs started in the range; `p50_s`/`p90_s`/`max_s` are over the jobs that finished `done` (0 when none).
- `getTimeline`: lanes for every mod (or `services`), in sidebar order; a band or span still open ends at `to`; a running job has `to: null`. Time the hub was down has no band (a gap).
- `getWidget` errors: `widget_not_found` (404), `invalid_request` (422, a range the widget doesn't offer), `service_not_running` (503), `upstream_error` (502, the mod failed or didn't answer JSON) and `widget_invalid` (502, the data doesn't match `WidgetData`; `data.problems` lists why).

### 11.8 Graphics on the other pages
- **Service page header:** a 1 h memory sparkline next to the memory figure.
- **Generic Overview tab:** a chart for each of the mod's numeric stats (`svc.<id>.stat.*`) over the chosen range, plus its mini timeline lane.
- **Memory popover (header):** a 1 h stacked area above the existing bar.
- **Models:** a size-by-kind treemap above the table, replacing the plain stacked bar, plus a disk-free gauge.
- **Outputs:** a per-day histogram above the grid. Dragging across it sets the date filter.
- **Settings → Memory:** a 24 h memory chart with the reserve line drawn, which updates live as you edit the reserve value.

### 11.9 Mock additions
- **7 days of metric history.** 10 s samples for the last hour, 1 min for 24 h and 1 h beyond, following realistic patterns:
  - lcpp loaded roughly 09:00–18:00 every day
  - tts load spikes with a 180 s idle tail
  - gen3d bursts up to ~52 GB while jobs run
  - comfy sessions of ~20 GB
  - "other" steady at ~12–15 GB
- **The rest of the history:** timeline lanes that match it, output/activity/job stats derived from the seeded outputs and activity, and a relay `traffic` widget (requests, tokens, TTFT per hour).
- **New `Shift+D` scenarios:** "Empty history" (a fresh install) and "Gaps" (the hub was down for 2 h, so the series contain nulls).

### 11.10 New states and acceptance
- **States:** every widget loading, empty and in error; a range switch; a legend toggle; "View as table"; the Customize panel; each of the four Overview views in compact and comfortable; and every chart at 360 px (Timeline scrolls sideways inside its card; widgets stack).
- **Acceptance:**
  - The above-the-fold rule in Section 11.3 holds.
  - The Dashboard opens in under 1 s with mock data.
  - No chart triggers polling while the tab is hidden.
  - Every chart has a text alternative.
  - Nothing is loaded from a CDN.

### 11.11 As built (plan 6.5)

Revision 2 was built by hand in this repo, not in a Claude Design pass. Where it differs from the sections above:
- **The chart components are plain ES modules, not `.dc.html` components.**
  - They live in `web/chart-kit.js` and `web/charts.js` and draw SVG through the page's React. The shell puts them in a template as React elements (`{{ ov.dash }}`).
  - **Why:** a data-driven chart needs hover state, a ResizeObserver and computed SVG paths. In a template, those paths would sit in `{{ … }}` inside SVG `d` attributes.
  - The Overview's Dashboard, Table and Timeline views are modules too (`web/dashboard.js`, `web/views.js`). The Services view, the tiles, stays in the template.
- **The Dashboard has a 15th widget, "Services":** a mini service list with state, memory and a 24 h sparkline. It shows every service above the fold, as §11.3 requires.
- **Default layout (span):**
  - Services 4, Memory over time 4, Memory now 4
  - Outputs per day 6, LLM traffic 6
  - Activity heatmap 6, Jobs 3, Model storage 3
  - Service uptime 6, GPU memory 3, Outputs by service 3
  - Recent outputs 6, Activity feed 6
  - then one widget per mod widget, at its declared span

  The grid packs densely. Spans of 3 and 4 become 6 under 1100 px, and everything is 12 under 760 px.
- **"LLM traffic" appears only when the relay mod declares its `traffic` widget**, while relay runs (`listWidgets()` lists only running mods' widgets). Any other mod widget is drawn by its `kind`.
- **KPI strip:**
  - memory used, with its share of total and a 1 h sparkline
  - services ready
  - models loaded (mods whose load is `loaded`)
  - jobs running (24 h sparkline)
  - outputs today, compared with yesterday (7-day sparkline)
  - LLM tokens today: the first mod stat labelled "Tokens today", or "—"
- **Customize** lists every widget, with show/hide and move up/down. Changes apply at once and are saved about 0.5 s later as `saveSettings({ui: {dashboard}})`; Reset clears the layout.
- **Compact tiles show their icon buttons on hover or focus** over the right of the first row, and always on touch screens. In comfortable, the buttons have text.
- **Outputs histogram:** it covers the last 30 days and is only on the Outputs page, not on a service's Outputs tab, because `getOutputStats` has no service filter. Dragging sets a day range, shown as a chip; the dashboard links to `#/outputs?from=YYYY-MM-DD&to=…`.
- **Raw-template requests (§11.2) are fixed by the hub, not by `<template>` wrapping.** A page load gets the page with an empty `<x-dc>`, and `support.js` renders from its own fetch of the same URL.
- **Keyboard:** time charts, bars, the donut, the heatmap and the treemap move their readout with the arrow keys. The Timeline's text alternative is its summary label plus "View as table".
- **Density:** this browser's choice (`localStorage`) wins; otherwise `Settings.ui.density`, whose default is `compact`. The theme works the same way.

---
---

# Part B — Service pages (build after Part A is approved, one per pass)

Each page lives in its mod's folder, as `services/<id>/ui/Page.dc.html` (a Claude Design component) or `ui/page.js` (a page module); see Section 5. It calls its service's native API through `ctx.call(...)`, which reaches the AIHub proxy at `/api/s/<id>/…`. Each pass:
- extends `mock.js` with that service's native endpoints
- sets `has_page: true`
- keeps the generic Outputs / API / Logs / Settings tabs

**Every Part B page follows revision 2:** compact by default, built from the Section 11.6 chart components, and with at least one chart. **Reuse the existing UIs as functional references; don't redesign behavior that already works.** Each page is built in the backend-plan phase that moves its mod in, and wired live in that same phase.

### B1. LLM Launcher (`lcpp`): port the existing lcpp UI

The attached lcpp UI was built from an earlier Claude Design brief. Its views become tabs: **Instances**, **Catalog**, **Playground**, **Relay publishing**. Its Settings view folds into a "Launcher settings" section under the generic Settings tab. The AIHub shell supplies the sidebar, header and memory meter, so drop lcpp's own. Its `api.js` method list stays the same, with every path prefixed by `/api/s/lcpp`. **Charts:**
- memory per instance over time (from `mem.svc.lcpp` plus each instance's RSS)
- tokens/s per Playground reply
- a catalog size treemap

### B2. LLM Relay (`relay`): analytics and routing

Tabs:
- **Dashboard**: KPIs (requests, tokens, p50/p95 TTFT, tok/s, error rate) with a window selector (1h / 24h / 7d / 30d). Charts: tokens over time, requests by model, latency distribution, tokens by hour of day. Use the Section 11.6 chart components.
- **Requests**: a live table that expands to show the request and response bodies when body logging is on.
- **Endpoints**: CRUD, test, activate, health. lcpp-owned endpoints are badged and read-only, with a link to the Launcher.
- **Tunnels**: SSH tunnels.
- **Connect**: copyable snippets for OpenAI SDK, curl and env vars.

Native API: `/admin/stats/*` (returns `{dimensions, source}` datasets), `/admin/endpoints*`, `/admin/router`, `/admin/tunnels*`, `/admin/settings`, `/v1/models`.

### B3. Speech (`tts`)

- **Speak**:
  - a text area with a character count
  - an engine segmented control (Breeze TTS 2 / Kokoro)
  - a voice picker (saved voices + Kokoro's built-in voices)
  - a delivery-direction field (Breeze) or speed (Kokoro)
  - an **Enhance** button that calls `POST /v1/enhance` and shows the added vocal tags as a reviewable diff
  - format select
  - **Generate**: the result card has an `AudioPlayer` with word-timing highlight (`timings: true`), and the file lands in Outputs.
- **Voices**:
  - a grid of voice cards: name, source (uploaded / designed), duration, play sample, edit, delete (confirm)
  - **Clone a voice**: upload a clip with an optional transcript; auto-transcribe if it's empty; preview, then save
  - **Design a voice**: a text description generates a sample; regenerate or save
- **History**: the generic Outputs tab is enough, so no custom tab.

**Charts:**
- clips per day by voice (stacked bars)
- load/idle state over 24 h (a mini timeline)
- a waveform in the result card

Native API: `/v1/voices*`, `/v1/voices/design`, `/v1/speech`, `/v1/enhance`, `/v1/enhance/tags`, `/v1/load`, `/v1/unload`.

### B4. 3D Generate (`gen3d`)

- **Create**:
  - engine (a dropdown): Cube3D from text, or an image engine (Hunyuan3D 2.1, TRELLIS.2, SAM 3D Objects, SAM 3D Body; plan 17)
  - for an image engine: the picture (Upload, which becomes an AIHub output, or Recent outputs), the engine's presets (Fast default, Base, TRELLIS.2 Draft) and every setting from `/v1/options` `engines`, face-budget shortcuts (Raw / 200k / 100k / 50k), its licence and where it runs
  - prompt (Cube3D)
  - preset (Low-poly / Fast / Balanced / Quality; Cube3D)
  - stage toggles (shape → parts → rig → preview)
  - part template (Chair, Character, Vehicle, Weapon, Creature)
  - face budgets
  - seed
  - live ETA from `POST /v1/estimate`
  - or **upload a mesh** to run only parts/rig
- **Jobs**: queue and history with per-stage progress over SSE (`/v1/jobs/{id}/events`), plus cancel, retry and delete. The job detail has:
  - the engine, preset, faces (and the raw mesh's), and the picture an image job started from
  - a `Viewer3D` with rig sliders (the raw mesh is a second tab when a face budget reduced it)
  - the parts list with colors
  - follow-ups (split, rig, re-split, new seed)
  - zip download

**Charts:**
- a per-job stage Gantt (shape → parts → rig → preview, with actual vs ETA)
- peak GPU memory per stage
- job durations over 30 days

Native API: `/v1/options`, `/v1/presets`, `/v1/estimate`, `/v1/jobs*`, `/v1/events`, `/v1/load`, `/v1/unload`.

### B5. Images & Video (`comfy`): later, after the ComfyUI adapter exists

- **Workflows**: cards for saved workflows (FLUX.2 Klein, Krea 2, Qwen-Image 2.1, Z-Image, SDXL, Wan 2.1/2.2, SCAIL 2), each with its exposed inputs.
- **Run**: a `SchemaForm` built from the workflow's input map (prompt, negative prompt, seed, size, steps, input image), then queue with live progress. Results go to Outputs.
- An **"Edit in ComfyUI ↗"** link opens the native UI.
- **Charts:** queue depth over time, run duration per workflow, and images/videos per day.

### Reserved: Chat (agent), built last in backend-plan Stage D

Not built yet. Keep the shell ready for it (Section 3). It gets its own brief when Stage D starts. What it will contain:
- **Thread list:** chats saved on the server, with search, rename and delete.
- **The thread:**
  - streaming replies
  - tool-call cards, with **Approve / Deny** for tools marked `confirm`; a pending approval is still waiting after a reload or restart
  - result cards that reuse `AudioPlayer`, `ImageView`, `Viewer3D` and `OutputCard`
- **Rewind / branch:** pick an earlier step in a thread and continue from there. It forks the thread's event log at that point (architecture §14.2); the full chat brief is plan step 14.1.
- **Sessions panel:** save the current setup (what's running and loaded), restore it, and switch between named setups.
- **Composer:** model picker (via the relay), tool-group toggles, and attachments from Outputs.

### 11.12 Agent tools and approvals (plan Phase 13)

The `tools` area. The chat (Stage D) and outside clients (MCP) use the same calls; the UI shows them in the API tab (tool badges with the risk level), the header **Approvals** popover and the chat's parameter cards.

**Methods** (area `tools`):

| Method | Endpoint |
|---|---|
| `listTools({q?, names?})` | `GET /api/tools` (`q`: best 8 by keywords; `names`: these, 404 `unknown_tool` with `data.close`) |
| `getToolIndex()` | `GET /api/tools/index` |
| `callTool(name, args, {mode?, origin?, wait?})` | `POST /api/tools/{name}/call?wait=` |
| `getToolCall(id, {wait?})`, `cancelToolCall(id)` | `GET /api/tools/calls/{id}`, `POST /api/tools/calls/{id}/cancel` |
| `listApprovals({state?})`, `getApproval(id)` | `GET /api/approvals` (pending; `state=all`), `GET /api/approvals/{id}` |
| `decideApproval(id, {approve, args?, reason?, wait?})` | `POST /api/approvals/{id}`: the edited `args` are what runs |

Also `GET /api/tools/calls/{id}/result?offset=&limit=` pages a capped result. **Events:** `{type: "approval", approval: Approval}` when one is created or decided; `{type: "tool_call", call: ToolCallResult & {origin}}` as a call starts, makes progress and ends.

```ts
type Risk = "read" | "write" | "generate" | "destructive";
interface ToolIndexItem { name: string; mod: string;                // "hub" for the hub's own tools
                          risk: Risk; core: boolean; summary: string; available: boolean; why?: string }
interface Tool extends ToolIndexItem { description: string;
                          parameters: JSONSchema;                   // one flat object; file inputs carry "x-kind": image|video|audio|mesh|file
                          ask: string[];                            // inputs the user chooses: editable on the parameter card
                          examples: object[]; job: boolean; source: "manifest" | "tools_source" | "hub" }
interface ToolOutput { output_id: string; ref: string;              // "output:<id>": what file inputs take
                       kind: string; title: string; url: string; preview?: string; summary: string; prompt?: string }
interface ToolCallResult { status: "needs_approval" | "denied" | "running" | "done" | "error" | "cancelled";
                           tool: string | null; call_id?: string; approval_id?: string;
                           result?: any;                            // JSON over 8 KB: {truncated, preview, full}
                           outputs?: ToolOutput[];
                           error?: { code: string; detail: string; fix?: string; problems?: object[] };
                           progress?: number; note?: string; job_id?: string; elapsed_s?: number;
                           arguments?: object; ask_fields?: string[]; risk?: Risk; schema?: JSONSchema; description?: string;
                           filled?: string[] }                      // needs_approval; filled: arguments the hub chose (an x-options default)
interface Approval { id: string; tool: string; arguments: object;  // as the model sent them
                     final?: object;                                // as run (after edits)
                     ask_fields: string[]; risk: Risk; origin: object;
                     state: "pending" | "approved" | "denied" | "expired"; reason?: string; call_id?: string;
                     created_ts: number; decided_ts?: number; schema?: JSONSchema; description?: string;
                     filled?: { [field: string]: "default" | "carried" | string };   // what the hub chose: a default, a preference ("pref:<id>"), carried from this chat
                     edited?: string[] }                                              // the fields the user changed on the card (plan 21.1)
```

**Choices that depend on the inputs (`x-options`, plan 20.1).** Any `enum` property may carry `x-options`, one entry per value: `{label?, needs?: string[], excludes?: string[], default?: boolean, good_for?, speed?, kind?, allows?: {<param>: values[]}}`. A choice **fits** when every `needs` parameter is given and no `excludes` one is. A property with `"x-depends-on": "<param>"` takes only the values that its parent's chosen option `allows` (when it lists them); its own `x-options` may say `quality` (`full`, `fast`, `draft`) and `when` (e.g. "only when the user asks for a quick result").
- **The hub** fills a missing choice with the `default` that fits (listed in `filled`) and refuses one that doesn't fit, before any card, as `invalid_arguments` with a `fix` naming the choices that do; edited card arguments are checked the same way (422, the approval stays pending).
- **The card** lists only the choices that fit the current values (re-checked when a file input changes), labelled with `label` and with `good_for` as help, and a dependent field only its parent's `allows`; it says which fields the hub chose (`filled`). As built: `web/mod-options.js` (`choices`, `defaultOf`, `labelOf`, `helpOf`), used by `schemaForm` (any mod page gets it too).
- **The model** reads `GET /api/tools?view=model`: each `x-options` rendered as lines in the property's description, the keys removed. `/api/tools` (default `view=full`), approvals and `needs_approval.schema` keep the metadata.
- **MCP forms** list only the choices that fit, with `enumNames` from the labels.

```json
"engine": {"type": "string", "enum": ["cube3d", "trellis2"], "x-options": {
  "cube3d":   {"label": "Cube3D", "needs": ["prompt"], "excludes": ["image"], "default": true, "good_for": "a mesh straight from text"},
  "trellis2": {"label": "TRELLIS.2", "needs": ["image"], "default": true, "good_for": "objects", "allows": {"preset": ["base", "fast", "draft"]}}}},
"preset": {"type": "string", "enum": ["base", "fast", "draft"], "x-depends-on": "engine",
           "x-options": {"fast": {"quality": "fast", "when": "only when the user asks for a quick result"}}}
```

**Preferences (plan 21.2–21.3).** `GET/POST /api/prefs`, `PATCH/DELETE /api/prefs/{id}`, `POST /api/prefs/{id}/approve|reject`:

```ts
interface Pref { id: string; scope: "tool" | "agent" | "thread"; tool?: string; field?: string; thread?: string;
                 value: any;                               // the argument's value, or a sentence for scope "agent"
                 when: { [param: string]: "present" | "absent" | any };   // where it applies (derived from x-options)
                 cue: string; source: "stated" | "inferred" | "carried";
                 state: "proposed" | "active" | "retired" | "rejected"; confidence: number;
                 evidence: { kind: string; ref: string }[]; seen: number; contradicted: number; note: string;
                 created_ts: number; updated_ts: number; last_used_ts?: number }
```

An approval's `filled` names which preference filled each field (`pref:<id>`), so the card can badge it "from your preferences". Bus events: `{type: "pref", pref: Pref | {id, deleted: true}}`.

**API tab (as built, Wire 13):** an operation that is an agent tool whose risk isn't `read` is sent as `callTool("<mod>_<tool>", args, {mode: "ask"})` (`web/api-tool.js`), so it asks first like any client: the chat's parameter card shows inline, Run / Cancel decide the approval, then the call's progress and its outputs (links to Outputs) show under the form. Read tools and operations with a file upload are still sent directly through the proxy.

**Error codes in `error.code`:** `invalid_arguments` (with `problems[]`, each `{field, detail, fix}`), `unknown_tool`, `denied`, `denied_by_user`, `unknown_output`, `service_not_running`, `mod_error` (the mod refused: 4xx), `upstream_error` (5xx or no answer), `job_failed`, `job_timeout`, `needs_room`, `interrupted` (the hub restarted). Deciding an approval twice is a hub error `409 already_decided`; edited arguments that don't validate are `422 invalid_arguments` and the approval stays pending.

### 11.13 Chat (plan 14.1) as built

Built by hand in `web/chat/` (plain ES modules on the page's React, like the dashboard), not in a Claude Design pass. The shell mounts `ChatPage` for `#/chat` and `#/chat/<thread id>` in a full-height main area; `?mock` runs it on a scripted mock agent (`chat-mock.js`).

**The page**
- **Thread list** (248 px; a drawer under 760 px of page width): search, New chat, and per chat Rename / Archive / Delete (with a confirm), an Archived toggle (the heading then reads "Archived chats"), 200 chats at a time with *Show more*, a dot for running (amber) or waiting (purple) chats.
- **Header:** the title (click to rename), the running / waiting state, the model picker (`skynet · 131k`, from the agent's `/v1/models`), the ask mode (Ask about choices / Use defaults / Read only), the **context meter** (`8.6k / 131k` with a bar; a popover with the breakdown, the 70% and 85% compaction marks and Compact now), and Branch (copy the chat). Under 700 px the model and mode move into a popover.
- **Thread (Phase 19):** a 760 px column of **turns**. A turn is your message (or "You ran …" for a result button or quick action), its **activity fold**, any agent errors, the **output strip** and the answer. A sticky **Plan** bar shows while any todo isn't done. The view stays at the bottom while you are there (new events, images loading, forms mounting).
  - **The activity fold** (`chat-activity.js`) is closed by default, the running turn included. Its header is the live status: a spinner, "Thinking…" with the seconds counting and the last two lines of thought peeking under it, "Generating an image… 42%" with the step's note, "Writing…", or "Waiting for you to approve below" / "Waiting for your answer below" (a purple shield), with the turn's time on the right. Once done it reads "Ran 2 tools · 2m 58s" (lookups aren't counted; "Looked something up" or "Thought it through" otherwise). A turn with no steps (a plain reply) has no fold.
  - **Opened**, the fold lists the steps with a rule on the left: thinking ("Thought for 4s ›", opening to the text), the agent's updates (its text in a step that called tools), tool calls (a status mark, the step's words and grey detail, percent or time, "needs you" or "next"; a progress bar under the running one), lookups and notes in grey, "You chose …" for an answered question, "Remembered: …", "Made a plan of N steps". A failed call reads "Tried making a 3D model" with the error's sentence as its detail. Steps are described by the arguments that ran (the ones approved on the card, which you may have changed), not the model's.
  - **A step opens to its sentence:** "Generated with **Z-Image Turbo**, square, seed 81723, from this prompt:", the prompt quoted (a failed step starts with "What it tried:"), "Approved by you" when it was approved, the result ("Made #1 in 18s", or the error and its fix), then **Raw call** (the tool name, the error code, the arguments and the result as JSON).
  - **The output strip** (`chat-results.js`): the turn's outputs as 56 px `#n` thumbnails when there's more than one; the picked one (the newest by default) as the result card, its preview capped at 300 px.
  - **The dock:** pending approvals, questions and parameter cards opened by a button sit above the composer, newest first ("Waiting for you · 2" when several), at most half the page tall. Nothing that waits for you sits in the thread.
- **Composer:** a growing text box (Enter sends, Shift+Enter is a new line, a message sent during a turn is queued and marked), attachment chips (a picker of this chat's and recent outputs), tool-group toggles (Auto / Pinned / Off per mod → the thread's `settings.pinned` / `disabled`), the quick actions, Stop, and slash commands with a suggestion list: `/compact`, `/clear`, `/model <id>`, `/context`, and `/<skill>` (sends "Use the <id> skill: …").
- **Reconnect:** the stream is `GET /v1/threads/{id}/stream?after=<last seq>`; on an error it reopens after 0.8–10 s from the last seq it saw, and replays are de-duplicated by seq. Pending question and parameter cards are rebuilt from the event log, so they survive a reload or a restart.
- **Rewind / branch:** hovering a message shows Branch from here: `POST /fork {seq: previous}`, then the new chat opens with that message in the box to edit.
- **Header Approvals** (Phase 13 Wire): a shield button with a purple count; the popover lists every pending approval (chat, MCP, API) as a compact parameter card with Approve / Deny. **API tab:** tool badges show the risk (`tool · generate`).
- **Settings → Agent:** the models, AGENT.md and MEMORY.md editors, topic files, skills, the modes and how permissions work.

**Events → turns.** `chat-thread.js` `buildView(events, live)` folds the log into items, then `chat-turn.js` `groupTurns(view, {running, now, tools})` groups them into turns of steps by the `step` id the agent puts on thinking, text and tool calls; the last step's text is the answer when that step called no tools. `buildView` folds the log into items as follows. A `tool_call` becomes a **tool** item (its `call`, live `progress` and `tool_result` folded in), or an **approval** item when an `approval` event names it (with its `decision`); `ask_user` becomes a **question** item with its `answer`; a result with outputs adds a **result** item; `update_todos` and `remember` calls are hidden (their `todos` / `memory` events have cards); `usage`, `state`, `call`, `answer`, `decision` are folded. Every other event type is an item of its own kind. Live `delta` events show streaming text and thinking until the stored `assistant` / `thinking` event of that step replaces them.

**Built-in cards:** user (right-aligned; Branch from here, Copy, `queued`), assistant (safe Markdown: every character escaped first, only http(s) / mailto / `#` / `/` links), question (1–4 questions, options with descriptions as radio or checkbox rows, "Other…", a schemaForm when the question has a `schema`; Enter on an option picks it and submits a single question; answered → a one-line summary), parameter (the `ask` fields first, plus required fields still empty, through `schemaForm`; the rest under "All settings"; file inputs (`x-kind`) offer this chat's outputs of that kind as thumbnails, then "More from Outputs"; Run / Cancel; a 422 shows inline and the card stays; once decided "Ran with …" or "Cancelled", with the run's progress), result (`#n`, title, kind; image, video, audio, or a 3D poster with "View in 3D" (viewer3d.js); Open in Outputs, Download; action buttons), todos, memory ("Remembered: …"), note, error (detail and fix), compact ("Earlier messages summarized", opens the summary). Anything else gets the **generic card**: the event type, collapsed JSON.

**Extending the chat (the modularity contract).** Import from `web/chat/chat.js`:

```js
import { registerCard, registerAction, registerPreview } from '/chat/chat.js';

// A card for a new event type (the agent emits {type: "storyboard", payload: {...}}):
registerCard('storyboard', ({ item, ctx }) => h('div', null, item.ev.payload.title));
// One tool's own look, for its tool / parameter / result card:
registerCard('result:gen3d_make_3d', MyMeshResult);
registerCard('approval:tts_speak', MyVoicePicker);

// A result button, or a composer quick action ('composer'):
registerAction({ id: 'image.upscale', on: 'image', label: 'Upscale', icon: 'upscale',
  tool: 'comfy_upscale_image', args: o => ({ image: { $file: 'output:' + o.output_id } }) });
registerAction({ id: 'audio.transcribe', on: 'audio', label: 'Transcribe', prompt: o => `Transcribe #${o.n}` });

// How results of a new output kind are shown:
registerPreview('pointcloud', ({ output, ctx }) => h(MyViewer, { src: output.url }));
```

- **Steps:** `registerStep(toolName, { running, done, icon, detail(args, ctx), sentence(args, ctx), lookup })` (`chat-steps.js`, re-exported by `chat.js`) gives a tool its words in the fold. Without one, the words come from the tool's name ("vllm_engine_status" → "Checking engine status" / "Checked engine status") and its schema's property titles; values show by the schema's labels (`x-enum-labels` or `oneOf` titles) and `output:<id>` values as `#n` chips. Any catalog tool whose risk is `read` is a lookup. `registerCard('step:<tool>', ({ row, item, ctx }) => …)` replaces one tool's opened step.
- **Cards** are looked up as `<kind>:<tool name>`, then `<kind>`, then the generic card, and each renders in an error boundary: an unknown or broken card never breaks the thread. Props: `{item, ctx}`; `ctx` carries `api`, `outputs` (this chat's `#n` outputs), `tools` (the catalog), `answer(qid, answers)`, `decide(approval, approve, args)`, `cancel()`, `runAction(action, output)`, `openOutput(id)`, `running`.
- **Actions** have `on` (an output kind or `composer`) and one of `tool` (opens a parameter card prefilled by `args(output)`, then `POST /v1/threads/{id}/action`: no model call), `prompt(output)` (sends a message), `attach` (adds the output to the composer) or `run(output, ctx)`. An action whose `tool` (or `needs`) isn't in the catalog is hidden. **Actions are also derived:** any catalog tool (not the hub's, not destructive) with a file input whose `x-kind` fits the output's kind becomes a button with no UI code (live: Clone voice on audio; in the mock also Upscale image), deduplicated against the registered ones.
- **Built-in actions:** image → Animate, Edit, Remove background (tools), Describe (a prompt); Make 3D opens `gen3d_make_3d` with the picture (plan 20.7: the card offers only the engines that take one), Use as reference (attach); video → Describe; model3d → Rig; composer → Image, Video, 3D, Speech, Edit image.

### 11.14 Sessions (plan Phase 15, Wire 15)

The `sessions` area: named setups (which mods run, which are loaded, lcpp's LLM instances) that can be saved and restored. An auto-saved "Last session" is kept by the hub, and at each start it copies the previous one to "Before restart" (both `auto`).

**Methods** (area `sessions`):

| Method | Endpoint |
|---|---|
| `listSessions()` | `GET /api/sessions` (named ones newest first, the auto one last) |
| `saveSession(name)` | `POST /api/sessions {name}` (201; the same name replaces that session) |
| `renameSession(id, name)` | `PUT /api/sessions/{id} {name}` (409 `conflict` when the name is taken) |
| `deleteSession(id)` | `DELETE /api/sessions/{id}` (204) |
| `restoreSession(id, {dryRun})` | `POST /api/sessions/{id}/restore[?dry_run=1]`: the plan; without `dry_run` it runs it (409 `busy` while another restore runs) |
| `getSessionState()` | `GET /api/sessions/state` |

**Events:** `{type: "session", session}` when one is saved (without its snapshot); `{type: "session_step", session: id, step: SessionStep}` as each step of a restore finishes.

```ts
interface Session { id: string; name: string; auto: boolean;           // auto: the hub's "Last session"
                    created_ts: number; updated_ts: number;
                    summary: string;                                      // "LLMs: gemma4-26B; loaded: comfy; 6 mods running"
                    snapshot: { version: number; ts: number; mods: Record<string, { running: boolean; load: LoadState }>;
                                lcpp: object[]; notes: string[] } }
interface SessionStep { action: "stop_llm" | "unload" | "start" | "launch_llm" | "load" | "skip";
                        target: string; detail: string; bytes?: number | null;   // negative: frees memory
                        spec?: object | null;                               // launch_llm: the instance's launch spec
                        ok?: boolean | null; error?: string | null }        // in results, after it ran
interface SessionMemory { available_bytes: number; freed_bytes: number; needed_bytes: number; reserve_bytes: number;
                          after_bytes: number;                                // available + freed − needed − reserve
                          fits: boolean }
interface SessionRestore { session: string; steps: SessionStep[]; memory: SessionMemory; dry_run: boolean;
                           results?: SessionStep[] | null; ok?: boolean | null }   // when it ran
interface SessionState { unclean_shutdown: boolean;                       // the hub didn't stop cleanly last time
                         last_auto: Session | null /* "Before restart" */; restoring: string | null; restore_on_boot: boolean }
```

**As built (UI):**
- **The Sessions panel** (`web/sessions.js`, a module on the page's React) opens from the Chat page (a Sessions button at the bottom of the thread list) as a dialog, and is the whole of **Settings → Sessions**. It lists every session with its summary and age (the auto one marked "auto"), and has **Save current setup…** (a name; the same name replaces).
- **Switch** first shows the dry-run plan: each step with its icon, detail and memory (−frees / +needs), then the memory line "available + freed − needed − reserve = after" with a fits / doesn't-fit badge. **Switch** runs it; each step ticks off live from `session_step` events (running, done, failed with its error), and the result is a toast.
- Rename (inline) and Delete (with a confirm) per session.
- **Command palette:** "Save session…" and "Switch to session…" (both open the panel; Switch opens a session's plan when typed as "Switch to <name>").
- **On page load**, when `unclean_shutdown` is set and a last auto session exists, a toast offers **Restore last session?** (Restore opens its plan; Dismiss is remembered for this tab in `sessionStorage`).
