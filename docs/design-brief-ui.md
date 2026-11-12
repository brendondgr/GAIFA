# Claude Design Brief: GAIFA — one control panel for every local AI service

> Companion docs: [architecture.md](architecture.md) (how GAIFA works) and [backend-plan.md](backend-plan.md) (backend build steps). Section 6 of this brief, plus the additions in Section 11.7, is the authoritative contract for the UI-facing API.
>
> **Status (2026-10-04):** **Part A v1 is delivered.** Claude Design exported it in its `.dc.html` format; the reference copy is in [reference/ui-export-2026-10-04/](reference/ui-export-2026-10-04/README.md). It is the visual and structural baseline for everything else.
> - **Part A revision 2** (Section 11) was built by hand in this repo (backend-plan 6.5, 2026-10-05); what differs from Section 11 is under §11.11. `web/` is now the baseline.
> - **Next Claude Design pass:** the Part B pages, one per mod as each one is moved in (backend-plan Phases 7–11). Give Claude Design the current `web/` folder and `web/PATCHES.md` with the Part B section.
>
> Paste everything below the line into Claude Design (`/design`). Attach these three files from the lcpp project as the starting design system: `~/Models/LLMs/web/assets/tokens.css`, `components.css` and `components.js`.
> **Build Part A first.** Part B (the service-specific pages) is built afterwards, one page per pass, against the contract defined in Part A.

---

## 0. What you are building

GAIFA is a **fully working, interactive single-page web app**. It is the one control panel for every AI service on one Linux workstation: a relay with an analytics dashboard for language models, a llama.cpp model launcher, a text-to-speech server with voice cloning, a 3D asset generator, and later ComfyUI for image and video generation, plus a chat agent that drives all of them.

Each service is a **mod**: a folder in `services/` that runs as its own local HTTP server. The GAIFA backend (`app.py`, at `http://127.0.0.1:7000/`) discovers the mods, starts and stops them, proxies their APIs, tracks memory, indexes everything they produce, and serves this UI. **Anyone can add a mod by dropping a folder into `services/`.** The UI must therefore work for services it has never heard of. That is the most important design requirement in this brief.

**Everything runs on this one machine.** The GAIFA binds to 127.0.0.1 only. There is no login, no accounts and no multi-user handling.

The page must work on its own in the browser **against a built-in mock API** that behaves like the real GAIFA (Section 7). One switch (Section 6.1) changes it to the real API without touching any UI code.

---

## 1. Hard deliverable constraints

1. **No build step.** Plain HTML, CSS and ES2022 modules. No npm, no bundlers, no TypeScript, no JSX.
2. **No framework.** Vanilla JS (`fetch`, `EventSource`, `<template>`, `<dialog>`, custom elements where helpful). No React, Vue, Tailwind or component libraries.
3. **External requests**: only Google Fonts (**IBM Plex Sans**, **JetBrains Mono**), with good system fallbacks. No CDNs, no analytics, no icon fonts, no remote images. Icons are inline SVG.
4. **All data access goes through one `api` object** (Section 6) with exactly the listed method names. UI code never calls `fetch` directly.
5. **Mock mode is the default** in the design environment. Live mode is chosen by `window.GAIFA_API_BASE` being set, or by the URL query `?live`.
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
│   ├── mock.js           createMockApi(): in-memory GAIFA + services with simulated time
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
- **React and ReactDOM load from `web/vendor/`.** GAIFA serves `Hub.dc.html` with local `react` and `react-dom` scripts placed before `support.js`; the runtime then skips its unpkg download. No other CDN is allowed, and nothing needs `.jsx`/`.tsx` (so no Babel).
- **All data goes through the `api` object** (Section 6).
- **`mock.js` stays a plain ES module** exporting `createMockApi()`.
- **New shared components go in their own `X.dc.html` files,** like `OutputCard` and `JsonView`. This includes every chart in Section 11.6.
- **Don't edit `support.js`.** If something needs a runtime change, say so in "What to return".

---

## 2. Visual direction

GAIFA belongs to the same product family as the existing Relay dashboard and lcpp: a **dense, calm operator console, dark-first**. Use the attached lcpp `tokens.css` / `components.css` / `components.js` as the starting point. Keep the token names, convert `components.js` to an ES module, and add the new components listed in Section 2.1.

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
1. Logo + "GAIFA"
2. **Overview** (default view)
3. **Chat**: present but **disabled** with a "Coming later" tooltip. The shell must leave room for a full-height chat view with a right-hand side panel later, without a redesign.
4. Section label **SERVICES**: **one nav item per service, generated from `api.listServices()`**, in the configured order. Each item has the service icon, its name and a status dot. Mods that failed to load show a red dot and still appear.
5. Section label **LIBRARY**: **Models**, **Outputs**
6. **Settings**
7. Footer: GAIFA status dot + version, and a `MOCK` badge in mock mode.

**As built (plan 33, 2026-10-21; `web/nav/`):** the sidebar has three groups. **Overview**, **Chat**, **Outputs** sit on top; the services are in the middle; **Memory** (while the agent mod is installed; `#/s/agent/memory`, lit on the agent page's Memory, Review and Preferences tabs; it was **Learning** until memory-auto-learning 4.2), **Models** and **Settings** are at the bottom. The top and bottom groups stay put and only the services scroll. The services show in one of three ways (`Settings.ui.nav.services`):
- `list`: a **SERVICES** header that folds the list (its counts show while folded), one item per listed mod (its logo, name and a state dot), then **See all**, always.
- `button`: one **Services** item, like the others.
- `counts`: the same item with how many are active (green), inactive (grey) and failed (red).

Hovering the header or the item shows a gear. Its menu picks the way they show and has a checkbox per mod (*Show all*, *Hide all*); hidden mods are left out of the list only, and new mods show. Active means `ready`, `degraded` or `starting`; inactive means `stopped` or `stopping`; failed means `failed` or a manifest error. Starting and stopping pulse.

A button beside the logo **collapses** the sidebar to a 56 px rail: icons with tooltips, each listed mod's logo with its state dot, and in the button modes (or folded) the Services icon over a three-colour bar of the counts. The expand button sits under the logo.

Every mod has a logo (`ServiceSummary.logo_url`); one without gets a monogram on a colour from its id. Logos also replace the icons on the Overview tiles and the service page header. Every item has a custom tooltip to its right (in the rail and expanded): the page and what it is, a mod's name, state ("Ready · Active") and description, the counts on Services and See all. Phones keep the drawer, always expanded, without tooltips. The choices are saved in `config.toml [ui.nav]` about 0.5 s after a change and kept in this browser (`localStorage` `hub.nav`) for the first paint.

**See all** opens the **Services page** `#/services`. It has the counts, filter chips (All · Active · Inactive · Failed), a search, *Sidebar shows* (List · Button · Button with counts), and a card per mod (listed or not): logo, name, id, state, description, port, memory, version, Open, Start or Stop, and an *In sidebar* switch. The header Search has the page and **Collapse / Expand the sidebar**.

**Persistent header** (every view):
- **Where you are** (plan 33.5): the page's icon (a mod's logo on its page) and its name, then `/` and the tab or Settings section ("Speech / Voices"). The GAIFA mark and name are only in the sidebar.
- **Memory meter**: unified memory used / total (this machine shares one memory pool between CPU and GPU). It turns amber above 80% and red above 92%. Clicking it opens a popover with the `MemoryBar` broken down by service.
- **Running jobs chip** ("2 running"), shown only when a service reports jobs. Clicking opens a popover listing them with progress and links.
- **Activity bell**: an unread count, and a popover with the last 30 activity items.
- **Search** button that opens the CommandPalette (`Ctrl/Cmd+K`).

**Toasts** sit bottom-right (bottom-center on phones). Errors stay until dismissed; successes auto-hide after 4 s.

**Hash routes** (reload keeps your place; Back works):
`#/overview`, `#/services`, `#/s/<serviceId>`, `#/s/<serviceId>/<tabId>`, `#/models`, `#/models/<modelId>`, `#/outputs`, `#/outputs/<outputId>`, `#/settings`, `#/settings/<section>`.

---

## 4. Views (Part A)

### 4.1 Overview (home)
*As built today: the bento Dashboard of §11.11b.*


- **Alerts strip** (only when present): for example "2 models have missing files", "Mod `broken` has a manifest error", "Speech failed to start". Each has an action link.
- **Services grid**: one `ServiceTile` per service.
  - State: `stopped`, `starting` (amber pulse), `ready` (green), `degraded` (amber), `stopping`, `failed` (red).
  - Load state for services that hold models in memory: `unloaded`, `loading` (amber pulse), `loaded` (cyan), `unloading`. It shows `n/a` for services with no models.
  - Port (mono), memory used (or "~52 GB when loaded" from the estimate), and idle time ("idle 12m").
  - Up to 4 **stats** supplied by the service (e.g. "Voices 3", "Requests today 1,284").
  - Quick actions: Start/Stop, Load/Unload, Open. Destructive actions confirm.
  - A tile for a mod with a manifest error shows the error and a "Show details" link instead of actions.
- **Memory panel**: `MemoryBar` (services + other + free, with the reserve marked), a total line ("33.1 / 121.0 GB · 12 GB reserved"), and a table of services sorted by memory with used, estimate, idle time and whether the GAIFA may auto-unload them.
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
   - A **Copy as curl** button for the request, using the GAIFA URL `http://127.0.0.1:7000/api/s/<id><path>`.
5. **Logs**: a live tail with the same behavior as lcpp's logs drawer. Follow toggle (auto-off when the user scrolls up, with a "↓ N new" pill), filter, wrap, copy, download, and a line-count select (200/1000/5000). Lines containing `error`/`failed` are red and `warn` lines are amber.
6. **Settings**: a form for this service's section of `config.toml`.
   - Enabled, autostart, port, idle-unload seconds (or "never"), "GAIFA may auto-unload this service to make room", priority (lower is unloaded first), environment overrides (`KeyValueEditor`).
   - Save and Revert, with a "restart required" note where relevant.
   - A read-only **Manifest** card shows the parsed `service.toml` and any manifest errors.

**Service unreachable** (GAIFA up, service down): an inline banner on the page ("Speech is not responding on 127.0.0.1:5040") with Start/Restart and a link to Logs. Custom tabs show their own empty state rather than crashing.

**Make room dialog**: when `loadService` is rejected with `needs_room`, show the `plan`. Example: "Loading **3D Generate** needs ~52 GB, 31 GB available. GAIFA will unload: **Speech** (frees 9.2 GB, idle 12m) and **Images & Video** (frees 24.0 GB, idle 40m)."
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
  - search over title and prompt, and, while the `embed` mod runs, a **By meaning** toggle beside it (plan 28.4; `web/outputs/meaning.js`): the words describe what to find and go to the mod's `POST /v1/search`; the grid gives way to a ranked list, one row per output, with its thumbnail or kind, title, score, and where it matched (page and line, seconds) with a snippet; a row opens the drawer. The kind chips filter the list.
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

One page, `web/settings/` (plan settings-redesign): `schema.js` declares every section, group and row as data (label, hint, `config.toml` key, control, keywords; or a named block for anything that isn't one value), `rows.js` draws the rows and groups, `blocks-hub.js` and `blocks-agent.js` the blocks, `settings-nav.js` the section list and search box, `route.js` the hashes, and `settings.js` is the page (`SettingsPage`, mounted by `Hub.dc.html`, which asks it `dirty()` for the unsaved-changes guard).

- **Hash:** `#/settings/<section>[/<group>[/<row>]]`; a group or row named by the hash opens and flashes. The old `paths`, `memory`, `interface`, `agent/permissions` and `about/hardware` are aliases to their new places.
- **The section list:** the sections as plain links in a left column with the search box at its top, sticky under the header (44 px compact, 52 px comfortable) so it stays in view while a long section scrolls; a link can carry a small count at its end. Under 760 px it sits above the content, not pinned.
- **Groups:** each section is one to seven groups, each a title that opens and closes it, with a one-line summary while closed ("Reserve 12 GB · auto make room off · 1 never unloaded"); Expand all and Collapse all; what you close is remembered in this browser (`gaifa.settings.open`); the hash's group and a group with a problem open regardless.
- **Search:** a box at the top of the section list (`/` focuses it, Esc or × clears) finds settings by label, hint, `config.toml` key or a synonym ("dark mode", "RAM", "VRAM", "MCP"), from two characters on, with no request; each installed mod's own Settings tab is found too ("<name> settings", under **Mods** after the sections). With a query the page shows every section that has a match, only matching groups open, other rows dimmed and matches in `<mark>`; the list counts matches per section and dims the rest; "12 matches in 4 sections" is announced. Enter and ↓ go to the next match (scrolled to and flashed, its mark in full accent), ↑ to the previous; clearing returns to the section you were on.
- **Row details:** under each hint the row's `config.toml` key in 11 px mono; when a value differs from its default (`getSettingsDefaults()`, from `config.example.toml`) a "Reset to default (<value>)" link beside the control sets the draft back; a row that needs a restart (the port) shows a "restart" badge while changed, and the Save bar says "Save and restart later". The section list counts the changed rows per section, and a **Changed** chip filters the page to them, as a search does.
- **Saving:** the hub's settings (brief §6 `Settings`) are one draft with one Save bar (Save sends only what changed, Revert, a restart note when the port changed); theme, density and the sidebar rows apply at once; the agent's own settings (AGENT.md, MEMORY.md, documents) keep a Save in their card, marked "saved by the agent".

The sections:

- **General:** *Hub* (**Set on this machine**: the saved values that differ from the defaults as "key · value (default x)" links to their rows, with Copy as TOML; the port, "Bound to 127.0.0.1 — this machine only", restart to apply; the process card: version, PID, uptime, memory), *Interface* (theme System/Light/Dark, density, services in the sidebar as list/button/counts, fold the list, Reset the dashboard layout), *Outputs* (delete saved web pages after N days).
- **Machine:** *Memory* (the 24 h chart with the draft reserve line; reserve; "Automatically make room when a service needs memory"; Never auto-unload; the unload order with up/down), *Storage* (the folders with sizes and Copy path, the disk bar), *Hardware* (plan 35.2: the system line, one row per GPU with memory, runtimes, what it can run and any problem, the accelerators GAIFA can use, Read again).
- **Services:** every folder in `services/`, broken mods with their errors; per mod enabled, autostart, its tool count and sidebar order (up/down); the **Add a mod** card (`gaifa new <id>`, edit `services/<id>/service.toml`, restart), linking the Example mod.
- **Services → Repositories** (plan mod-repos 3.5): relay, lcpp, tts and gen3d are git submodules of their own repositories. One row per mod: its repository (linked) and branch, the pinned and checked-out commits, badges for its problems (red error, amber warning, cyan info, green at its pin, purple when a new pin is staged) with each problem's fix, Pin when it has commits GAIFA doesn't pin yet, and **Update…**, which lists the incoming commits (`repoIncoming`), then follows the hub's update step by step to its result. **Check now** asks GitHub; the line says when it last did. Rows: Check GitHub every (hours, 0 = never), Alerts (warnings, all, off), Check when GAIFA starts.
- **LLMs** (plan llm-servers 4.1; while the relay is installed), between Services and Agent: *Servers* (the relay's endpoints grouped On this machine / Remote / Cloud / Agents, each with its health, its key as its last four characters (Add key / Key… / Remove key, a password field sent once to the relay), Turn off, Remove (asks again; OpenCode's card has no key buttons and says its provider keys live in `services/opencode/.env`), and **Models**, the server's own list read live (`GET /api/s/relay/admin/endpoints/{id}/models`) with a checkbox per model to show it in the Chat picker, Refresh, and on a cloud OpenAI server the filter that hides embedding, speech and image models); *Add a server* (Anthropic, OpenAI, Gemini with a key, or any OpenAI-compatible URL; a short name, picked as `<short name>/<model>`; the note that cloud models answer chats only); *On this machine* (`getLlmEngines`: each engine with its state, Start while stopped, its models with size, memory, context and format, Load / Unload, and on `needs_room` "GAIFA can unload …" with **Unload & load**); *Defaults* (the agent's chat model and fallback, saved to its `AGENT_MODEL` / `AGENT_FALLBACK_MODEL` and restarting it). Agent → Model links here.
- **Agent** (while the agent mod is installed): *Model*, *Documents*, *Reading web pages* (long pages and the relevance model), *Instructions* (AGENT.md), *Memory* (the counts and a link to Review; recall; fading; plan memory-auto-learning 2.4: "Save what it learns without asking when it's sure", How sure Cautious 0.9 / Normal 0.8 / Eager 0.65, and Always ask about: health, money, legal, relationships, religion, politics, sexuality), *Skills*, *Learning*.
- **Permissions** (while the agent mod is installed): *Modes*, *Tool rules* (never run, always ask, run without asking), *Grants* (with Revoke), *Auto judge* (its decision model, plan web-approvals; what it reads, threshold, time limit, your command rules), *Screening* (pages, documents, transcripts, the screening model, text per call, calls at once), *Judged calls* (with "Always allow", added to the draft).
- **Speech** (while the stt or tts mod is installed): *Dictation* (microphones in order, language, model, the button), *Voice* (the voice that reads replies, speed, read every reply, voice mode's pause), *Voice mode* (Start muted, plan voice-mute 1.3; plan voice-speech-model 3.2; while the stt and tts mods or the voice mod are installed: **Voice mode uses** Chat model, read aloud / Speech model (local), the second disabled with "Install the Voice mod: gaifa setup voice" until that mod exists; with the speech model chosen, **Who answers** (The chat's agent / The speech model itself; `voice_mode.answers`), its **Size** (Q4_K_M / Q8_0), its **Voice** (Female / Male), and, when the speech model itself answers, **Tools it may use** (chips, none by default: Calendar: your day / find / free time, Web search, The time; `voice_mode.tools`), **Let it ask the chat's model** (`voice_mode.ask_chat`), and a line saying whether the model is downloaded and loaded).
- **Sessions:** the Sessions panel (brief §11.14).
- **About:** *Versions* (with "GAIFA · Great, Another Interface For Agents · say “guy-fuh”"), *Command line* (`gaifa status`, `start <id>`, `logs <id> -f`, `new <id>`, `doctor`), *Doctor* (plan 12.4: `getDoctor()`, the counts, the warn and fail checks with fixes, Show all, Run again).
---

## 5. The page-module contract (how a service brings its own UI)

A service may ship `services/<id>/ui/page.js`. The real GAIFA serves it at `/ui/services/<id>/page.js`, and the shell loads it with a dynamic `import()` when `has_page` is true. A page module is plain ES and imports the design system from the GAIFA:

```js
// services/<id>/ui/page.js
import { Button, Card, Field, AudioPlayer /* … */ } from '/js/components.js';

export default {
  // Shown before the generic Outputs / API / Logs / Settings tabs.
  tabs: [{ id: 'speak', label: 'Speak', icon: 'wave' }, { id: 'voices', label: 'Voices', icon: 'user' }],

  // Render tab ctx.tab into el. May return a cleanup function.
  mount(el, ctx) { /* … */ },

  // Optional (calendar 3.1), with [ui] main in service.toml: the page as a main view at #/<id>, full height.
  main: { mount(el, ctx) { /* … */ } },
};
```

`ctx` provides:

| Field | What it is |
| --- | --- |
| `ctx.service` | the current `ServiceDetail` (kept fresh by the shell) |
| `ctx.tab`, `ctx.params` | current tab id and hash query params (`#/s/tts/voices?edit=hope`) |
| `ctx.call(method, path, opts)` | shorthand for `api.callService(ctx.service.id, method, path, opts)` |
| `ctx.api` | the full GAIFA `api` object (e.g. to list outputs or models) |
| `ctx.ui` | the components module |
| `ctx.toast(msg, level)`, `ctx.confirm({title, body, danger})` | shell helpers |
| `ctx.navigate(route)` | change the hash route |
| `ctx.on(eventType, fn)` | subscribe to GAIFA events; returns an unsubscribe function; auto-cleaned on unmount |

Rules: a page module never calls `fetch` directly, never styles with raw colors, and handles "service not running" by showing an `EmptyState` with a Start button.

**As built (plan 2.9).** In the `.dc.html` shell, `web/ModPage.dc.html` hosts every page module: it `import()`s `ServiceSummary.page_url` and calls `mount(el, ctx)` on its own element, remounting when the mod, the tab, the hash params or the running state change. `ctx.ui` is `web/mod-ui.js`, plain DOM helpers that use the theme variables, because the export has no importable `components.js`: `h(tag, attrs, ...children)`, `text`, `row`, `stack`, `card`, `button(label, onClick, {kind})`, `input`, `textarea`, `select`, `field(label, control, hint)`, `json(value)`, `badge(label, tone)`, `empty(title, body, action)` and `table(rows)`. `ctx.on('*', fn)` receives every event. Tab ids can't reuse the generic ones (`overview`, `outputs`, `api`, `logs`, `settings`). If `mount` throws, ModPage shows the error and the other tabs keep working.

**As built (plan 7.7).** The Part B pages are built by hand as `ui/page.js` modules, like revision 2. Two shared modules help: `web/mod-kit.js` (the not-running state, `callRoom` for calls that may need make-room, a segmented control, panels) and `web/mod-charts.js` (mounts the §11.6 chart components into a page module's DOM: `chartCard`, `chart`, `waveform`). In `?mock`, the built-in mods show their real page modules and `mock.js` answers their native API.

**In the `.dc.html` shell (from revision 2 on), a mod's page can come in either of two formats.** Either way, it lives in the mod's own folder.

| Format | Who uses it | How it loads |
|---|---|---|
| **`ui/page.js`**, the ES module above | any mod, with no Claude Design needed | The shell hosts it in a `ModPage.dc.html` component, which calls `mount(el, ctx)` on a ref and runs the cleanup on unmount. |
| **`ui/Page.dc.html`**, a dc component | the built-in mods, whose pages Claude Design draws in Part B | GAIFA serves `services/<id>/ui/Page.dc.html` at `./Mod_<id>.dc.html`, and the shell's `<dc-import>` loads it like any other component. backend-plan step 2.9 checks whether `dc-import` accepts a dynamic name. If it doesn't, the shell keeps a small static list of built-in pages. |

The Example mod's **Hello** tab, which v1 built into `Hub.dc.html`, moves out to `services/_template/ui/page.js` as the reference `page.js` module.

**Part A delivers one example module**, `services/_template/ui/page.js`, for the mock service **Example** (Section 7). It has one tab, **Hello**: a name field, a call to `GET /v1/hello?name=…`, and the JSON result in a `Card`. It also shows a toast on errors. This file becomes the template that `bin/gaifa new` copies, so keep it short and commented.

---

## 6. The `api` object (exact contract)

These are also the real GAIFA's HTTP routes. All methods return Promises that resolve to the documented JSON, or reject with `ApiError { status, detail, code, data }`.

### 6.1 Mode switch

```js
const LIVE = !!window.GAIFA_API_BASE || new URLSearchParams(location.search).has('live');
const BASE = window.GAIFA_API_BASE || '';
export const api = LIVE ? createHttpApi(BASE) : createMockApi();
```

**Updated for progressive wiring (supersedes the block above from revision 2 on).** The backend goes live one area at a time, so the UI uses a **hybrid** API. `web/api.js` is written by us, not by Claude Design, and exports `createApi`:

```js
import { createMockApi } from './mock.js';
import { createApi } from './api.js';
// The real GAIFA serves /config.js, which sets GAIFA_API_BASE and GAIFA_LIVE_AREAS.
const areas = window.GAIFA_LIVE_AREAS || [];      // e.g. ['system','services','logs','operations','proxy','events']
const forceMock = new URLSearchParams(location.search).has('mock');
export const api = createApi({ base: window.GAIFA_API_BASE ?? null, liveAreas: forceMock ? [] : areas, mock: createMockApi() });
```

- **Methods in a live area** call HTTP. Everything else answers from the mock.
- **`subscribe`** merges live events for live areas with mock events for the rest.
- **`api.liveAreas`** says which areas are live, so each page section can show a small **MOCK** badge while its area is still mocked. `api.isLive(area)` answers the same for one area.
- **Errors in `callService`:** a non-2xx from the mod rejects with `upstream_error` (`detail` = the mod's message, `data.body` = its body). Hub errors carry an `X-GAIFA-Error` header and reject with their own code.

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
| `listOutputs(filter)` | `GET /api/outputs?service=&kind=&q=&from=&to=&cursor=&limit=&include_hidden=` | `OutputPage` (`service` and `kind` are comma-separated lists; `q` matches every word; `limit` 1–500, default 60; hidden outputs, the web mod's saved pages, only with `include_hidden=true`, plan 30.9) |
| `getOutput(id)` | `GET /api/outputs/{id}` | `Output` |
| `deleteOutput(id)` | `DELETE /api/outputs/{id}` | `204`; the output moves to `outputs/.trash/`, emptied after 30 days; `?permanent=true` deletes it for good (the eval's outputs) |
| `uploadOutput(file)` | `POST /api/outputs/upload?name=` (the file as the body) | `Output` (`201`): an image, video, audio, text or document file (plan 24.1); `upload_type` 415, `upload_encoding` 415 (a text file that isn't UTF-8, or UTF-16 with a BOM), `upload_too_large` 413 (64 MB), `upload_empty` 400 |
| `getWebReading()` | `GET /api/web/reading` | `{screen: {backend, model, confirm: string \| null, same_as_judge}, judge: {backend, model}, choices: {relay: string[], decide: string[]}, relevance: "decide" \| "lexical" \| "off", decide_up: boolean}`: the screening and relevance models in use and the choices (Settings → Agent → Reading web pages) |
| `readWebPage(url, {text?})` | `POST /api/web/read` | `WebPage` (plan 30.8): `{output: Output, url, final_url, title, kind: 'text'\|'document', chars, screening: {removed, checked, ms, model?, covered, findings: [{passage, why, by, excerpt, line}]} \| null, markdown?, screened?}`; the web mod's errors (`blocked_address` 403, `robots` 403, `too_large` 413, `unsupported_type` 415, `timeout` 504, …) with `data.fix`; `service_not_found` 404 without the web mod |
| `outputText(id, {offset, limit, page, pages})` | `GET /api/outputs/{id}/text?offset=&limit=&page=&pages=` | `OutputText` (plan 24.3; text and documents; `screened=true`: as the chat model reads it, screened per `[agent.screen]`, the note in `notes`): `limit` 12000 chars by default, at most 48000; `page`/`pages` (`3` or `3-5`) start at that page and stop at the range's end; `next_offset` continues through the document. `not_text` 409 for other kinds, `no_page` 404 |
| `outputSearch(id, q, {limit})` | `GET /api/outputs/{id}/search?q=&limit=` | `OutputSearch`: words (any case, all within one line, else one paragraph), a `"quoted phrase"`, or `/regex/` (`/regex/i` ignores case; `search_timeout` 422 past 1 s); `limit` 20, at most 200; at most 5,000 matches are counted (`capped: true` past that) |
| `outputPageUrl(id, n, {width})` | `GET /api/outputs/{id}/page/{n}.png?width=` (a URL, not a request) | A PDF page as a PNG (`width` 1200 px by default, 64–2400), cached under `outputs/.previews/<id>/`; `no_page` 404 |
| `getSettings()` | `GET /api/settings` | `Settings` (`services.order` and `memory.priority` list every installed mod: the configured ids first, then the rest in sidebar order) |
| `saveSettings(s)` | `PUT /api/settings` | `{ settings: Settings, restart_required: boolean }` (send the whole form or any part; what is left out stays as it is, and only changed values are written. A bad value is `422 invalid_config` with `data.field`, e.g. `"hub.port"` for a port a mod uses; nothing is written). With `base` (`{section: {key: value}}`, what each changed key held when the page loaded), lists and tables merge with what is saved now (architecture §9, Saving); a value changed elsewhere too is `409 settings_conflict` with `data: {field, current, yours}`) |
| `getUiStore(scope)` | `GET /api/ui/store/{scope}` | `{ values: Record<string, unknown> }`: what the pages remember for a mod (its id) or for the hub (`"hub"`) (settings-that-stick 4.1) |
| `saveUiStore(scope, {set, del})` | `PATCH /api/ui/store/{scope}` | `{ values }` after setting and deleting those keys only (each value ≤ 16 KB: `413 payload_too_large`) |
| `getSettingsDefaults()` | `GET /api/settings/defaults` | `Settings`: the values of `config.example.toml`, what each row of the Settings page returns to with Reset (plan settings-redesign 4.1) |
| `subscribe(onEvent)` | `EventSource /api/events` | `{ close() }`; each `data:` is a `HubEvent` |

File and preview URLs (`Output.url`, `Output.preview`) are plain GETs used directly in `<img>`, `<audio>`, `<video>` and download links.

### 6.3 Error codes to handle

`service_not_found`, `service_not_running`, `service_failed`, `service_disabled` (start on a disabled mod), `external_service` (start/stop on a `kind = "external"` mod), `manifest_invalid`, `port_in_use`, `needs_room`, `not_unloadable`, `model_not_found`, `model_in_use`, `model_exists` (adding a model whose id or files are already registered), `model_files_missing` (verify on a model with no files on disk), `registry_invalid` (registry.json can't be read; changes are refused until it is fixed), `output_not_found`, `output_not_deletable` (the output resolves outside `outputs/`, e.g. through a symlinked folder), `upload_encoding` (a text upload that isn't UTF-8 or UTF-16 with a BOM), `not_text` (409: reading the text of an output that has none), `no_page` (404: a page the document doesn't have), `search_timeout` (422: a `/regex/` search over 1 s), `invalid_config` (422: a settings save that would break config.toml, e.g. a port clash; nothing is written), `upstream_error` (the service itself returned an error; `detail` carries its message), `widget_not_found`, `widget_invalid` (a mod's widget data doesn't match `WidgetData`), `hub_error`. Generic HTTP errors use `not_found` (404), `method_not_allowed` (405) and `invalid_request` (422, a request body or query that fails validation; `data.errors` lists `{loc, msg}`).

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
  kind: "process" | "external";  // external = GAIFA does not launch it; it only health-checks and proxies it
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
  logo_url: string | null;       // plan 33.1: the mod's logo ([ui] logo, else ui/logo.svg), or null: the UI draws a monogram
  chat_url?: string | null;      // plan 44.1: the mod's chat module ([ui] chat), which the Chat page loads; null without one
  badge?: number | null;         // calendar 2.1: the mod's unread count (its last POST /api/notify `unread`), a badge on its sidebar item
  main?: { label: string; after: "overview" | "chat" | "outputs" } | null;   // calendar 3.1: the page module's `main` as a main view at #/<id>
  chat_panel?: { label: string; url: string } | null;   // calendar 7.1: a side panel in Chat
  has_outputs: boolean;
  native_ui: string | null;      // URL of the service's own UI, if any
  enabled: boolean;
  autostart: boolean;
  last_error: string | null;
  manifest_errors: string[];     // non-empty → state "failed", not startable
  accel: string | null;          // plan 38.3: the variant installed (rocm, cuda, xpu, mps, vulkan, cpu); null: not recorded
  unavailable: string | null;    // plan 38.3: why it can't start on this machine (its variant's accel isn't here); start answers 409 unavailable
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
  auto_unload: boolean;          // GAIFA may unload it to make room
  priority: number;              // lower = unloaded first
  env: Record<string, string>;
  accel: string | null;          // plan 38.2: the variant installed (rocm, cuda, xpu, mps, vulkan, cpu); null: not recorded
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
                idle_s: number | null; auto_unload: boolean; priority: number;
                gpu_busy_pct?: number;      // its busiest GPU engine's share since the last sample, 0–100 (plan 28.2)
                vram_bytes?: number }[];    // its VRAM on dedicated GPUs (plan 36.1; only where there's one)
  other_bytes: number;           // OS, desktop, browser — anything the GAIFA does not own
  pools: { id: string; name: string; total_bytes: number; used_bytes: number; available_bytes: number }[];
                                 // plan 36.1: "system" first, then "gpu:<index>" per dedicated GPU (one entry where GPUs share the RAM)
}

interface MakeRoomPlan {
  service: string; needs_bytes: number; available_bytes: number;   // available = MemAvailable − reserve − other loads' reservations
  unload: { id: string; frees_bytes: number; reason: string; pool?: string }[];  // reason: "priority 1, idle 12m"; pool: a GPU's VRAM it frees
  enough: boolean;
  pool: string;                  // plan 36.2: the pool that's short: "system" or "gpu:<index>"
  pools: { pool: string; name: string; needs_bytes: number; available_bytes: number; enough: boolean }[];
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

type OutputKind = "audio" | "image" | "video" | "model3d" | "text" | "document" | "archive" | "other";
interface Output {
  id: string;
  service: string;
  kind: OutputKind;
  subtype?: string;              // text and documents (plan 24.1): "markdown", "plain", "code:python", "config:toml", "web:html",
                                 // "data:csv", "subtitles", "notebook", "pdf", "docx", "epub", "pptx", "xlsx", "odt"
  title: string;
  path: string;                  // "outputs/tts/2026-10-04/143012-good-morning.wav" (file or folder)
  files: { path: string; kind: OutputKind; size_bytes: number; role?: string }[];
  url: string;                   // main file
  preview: string | null;        // thumbnail / poster
  size_bytes: number;
  created_ts: number;
  duration_s?: number;
  dims?: { w: number; h: number };
  hidden?: boolean;              // plan 30.9: kept out of lists (the web mod's saved pages); set only when true
  meta: { prompt?: string; model?: string; voice?: string; seed?: number;
          params?: Record<string, unknown>;
          excerpt?: string;          // text outputs without a prompt: their first lines, for the card
          [k: string]: unknown };
}
interface OutputPage {
  items: Output[]; next_cursor: string | null;
  totals: { count: number; size_bytes: number;
            by_kind: Record<OutputKind, number>;      // counts with every filter except kind
            by_service: Record<string, number>;       // counts with every filter except service
            hidden: number };                         // hidden outputs with these filters (listed only with include_hidden)
}

interface OutlineItem { level: number; title: string; offset: number; line: number; page?: number }   // plan 24.2
interface OutputText {                       // plan 24.3: a window of an output's extracted text
  text: string; offset: number; next_offset: number | null;   // null at the end
  total_chars: number; tokens: number;       // tokens: the whole text's estimate (chars / 4)
  pages: number; lines: number;              // pages: 0 for text without pages
  page_of_offset: number | null; outline: OutlineItem[];
  scanned: number[];                         // PDF pages with almost no text: look at their page image
  truncated: boolean;                        // the text was cut at 4 M characters
  notes: string[];
}
interface SearchHit { page?: number; line: number; offset: number; text: string }   // text: the line with ±1 line of context
interface OutputSearch { hits: SearchHit[]; total: number; capped?: boolean }   // capped: over 5,000 matches; total counts the first 5,000

interface Activity { id: string; ts: number; service: string | null;
                     level: "info" | "warn" | "error"; text: string; route?: string }
interface Alert { id: string; level: "warn" | "error"; text: string; service?: string;
                  action?: { label: string; route: string } }
interface Job { id: string; service: string; label: string; progress: number | null;  // 0..1
                state: "queued" | "running" | "done" | "failed" | "cancelled"; route?: string;
                live?: Live }                 // plan 44.2: live progress, the same for any job (from the agent, a mod page, ComfyUI's own page, the API)

// plan 44.2: a job's live progress (utils/live.py). Paths are on the hub (/api/s/<id>/…): whatever shows the job pulls
// the preview frame itself when `preview.seq` changes. Every field is optional.
interface Live { stage?: string; stages?: { id: string; label: string; state: "waiting" | "running" | "done" | "failed" | "skipped"; eta_s?: number }[];
                 step?: number; steps?: number; eta_s?: number; frames?: number; lines?: [number, number]; audio?: string;
                 preview?: { url: string; seq: number; w?: number; h?: number } }

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
  hub: { port: number };          // 1024–65535; a change applies after GAIFA restarts (restart_required)
  memory: { reserve_gb: number; auto_make_room: boolean; never_unload: string[]; priority: string[] };
  services: { order: string[]; enabled: Record<string, boolean>; autostart: Record<string, boolean> };
  ui: { theme: "system" | "light" | "dark"; density: "comfortable" | "compact";   // compact is the default
        dashboard: { order: string[]; hidden: string[]; ranges: Record<string, string> };   // Customize (§11.5), saved in config.toml
        nav: { collapsed: boolean; services: "list" | "button" | "counts"; hidden: string[]; folded: boolean };   // the sidebar (plan 33.2), [ui.nav]; send it whole
        chat: { steps: "fold" | "split"; environment: string | null;   // [ui.chat] (settings-that-stick 3.1); chat and overview may be sent in part
                list: { show: "chats" | "archived" | "both"; group: "environment" | "date" | "none"; env_order: "activity" | "name" | "created"; chat_order: "updated" | "title" | "created"; collapsed: string[] } };
        overview: { view: "dashboard" | "services" | "table" | "timeline"; timeline_range: "1h" | "6h" | "24h" | "7d"; services_range: "1h" | "6h" | "24h" | "7d" } };   // [ui.overview]
  learning: { enabled: boolean;   // plan 21: preferences on the cards and the learner; off = nothing filled or learned
              nightly_at: string; idle_min: number; infer_after: number; fade_days: number };
  speech_input: { mics: string[];   // plan 29.4: microphone labels, most preferred first; the first one present is used
                  language: string; preset: "fast" | "balanced" | "accurate" | "best"; mode: "both" | "toggle" | "hold" };
  speech_output: { voice: string; engine: "auto" | "breeze" | "kokoro"; speed: number;   // plan 49.1: reading replies aloud ("" = tts's default voice)
                   auto_read: boolean; pause_ms: number };   // auto_read: every finished reply; pause_ms: voice mode's turn end (plan 49.2)
  voice_mode: { engine: "chat" | "speech";   // plan voice-speech-model 3.1: chat = the chat's model through stt and tts; speech = the voice mod's speech-to-speech model
                answers: "agent" | "speech";   // with the speech engine, who answers (6.1): the chat's agent (its model, tools, apps, cards) or the speech model itself
                quant: "q4_k_m" | "q8_0"; voice: "female" | "male";   // the speech model's size and voice
                tools: string[]; ask_chat: boolean;   // answers = "speech": tools it may call (≤ 6), and handing a question to the chat's model (Phase 5)
                start_muted: boolean };   // voice mode starts muted, either engine (plan voice-mute 1.3)
  judge: { backend: "decide"; model: string;   // config.toml [agent.judge] (plan 30.3): always a decision model (web-approvals); picked in Settings → Permissions → Auto judge
           url: string; threshold: number; timeout_s: number;
           allow_commands: string[]; ask_commands: string[];   // your command rules for Auto (`pytest *`; judge_user.py, plan 30.7)
           context: "none" | "trail" | "full" };   // what the judge reads of the turn besides your words (judge_context.py, 2026-10-21)
  permissions: { deny: string[]; ask: string[]; allow: string[] };   // [agent.permissions]: tool-name globs (architecture §14.7)
  screen: { pages: boolean; documents: boolean; transcripts: boolean;   // [agent.screen] (plan 30.6)
            timeout_s: number; window_chars: number;
            backend: "relay" | "decide" | null; model: string | null; url: string | null;   // null: the judge's (plan 30.8)
            threshold: number | null; confirm: boolean; parallel: number };   // parallel: model calls at once for one text; confirm: ignored (web-approvals)
  web: { relevance: "auto" | "decide" | "lexical" | "off"; model: string; url: string; candidates: number; timeout_s: number };   // [agent.web]: a long page's relevant passages first (webread.py, 2026-10-21)
  workflows: { enabled: boolean; parallel_local: number; parallel_remote: number; max_children: number; max_depth: number;   // [agent.workflows]: sub-agents (plan agent-workflows 3.6)
               child_max_steps: number; workflow_tokens: number; queue_wait_s: number; min_window: number };   // Settings → Agent → Sub-agents
  outputs: { hidden_keep_days: number };   // [outputs] (plan 30.9): saved web pages go to the trash after this many days; 0 keeps them
  repos: { fetch_every_h: number; notify: "warnings" | "all" | "off"; check_on_start: boolean };   // [repos] (plan mod-repos 3.5): how often to ask GitHub (0 = never), which problems are alerts
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
  | { type: "ui_store"; scope: string; keys: string[] }   // a page's remembered values changed (settings-that-stick 4.1)
  | { type: "notification"; id: string; ts: number; service: string; title: string; body: string; level: "info" | "warn"; route: string | null; key: string | null; actions: { label: string; op: string }[] }   // calendar 2.1: a mod's toast (POST /api/notify), area `notify`
  | { type: "badge"; service: string; unread: number }   // calendar 2.1: a mod's unread count, its sidebar badge
  | { type: "settings"; changed: string[] }   // config.toml was saved (settings-that-stick 2.3): `changed` are dotted Settings keys; open pages reload getSettings()
  | { type: "resync" };            // events were dropped (slow client): refetch everything

interface LogLine { ts: number; text: string; stream: "stdout" | "stderr" }
```

---

## 7. Mock API requirements (must feel real)

The mock keeps in-memory state, applies the same validation rules, emits `HubEvent`s through `subscribe`, and simulates time. **The seed data is this real machine; use it.**

**System**: AMD Ryzen AI MAX+ 395. Unified memory 121.0 GB total (~33 GB used at start). GPU "AMD Radeon 8060S (Strix Halo)": VRAM 4.0 GB, GTT 121.5 GB. Disk 952 GB with 450 GB free. GAIFA v0.1.0 on port 7000, RSS ~90 MB.

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
- GAIFA down: every call rejects; show a full-width banner "GAIFA not responding at 127.0.0.1:7000" with a retry countdown and the hint `bin/gaifa start`.
- Fail a service: pick one; it goes to `failed` with an error and log lines.
- Memory pressure: preload `comfy` and `tts` so the make-room path triggers.
- Install a broken mod: add service `broken` with `manifest_errors: ["service.toml: missing [run].port"]`.
- Install a mod with no page: add service `transcribe` (port 5060, ops `POST /v1/transcribe` multipart audio → json), so the generic Overview/API tabs are exercised.
- Outputs: Empty / Seed / Many (2,000 items, to test paging).
- Speed ×1 / ×5.

---

## 8. States checklist (each must be designed and reachable)

- First load: skeleton, then data. GAIFA down banner and its recovery. A dropped event stream while the hub still answers is not "down": the UI checks with `GET /api/overview`, reopens the stream and refetches without the banner (Firefox drops quiet connections whenever a network interface changes); a failed check or a second drop within 10 s shows the banner.
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
2. Setting `window.GAIFA_API_BASE = ''` (or `?live`) switches to the HTTP endpoints in Section 6 with no other code changes.
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

> Give Claude Design the **current `web/` folder** (the v1 export with GAIFA's edits, listed in `web/PATCHES.md`), Section 6 and this section. **Change only what this section asks for.** Everything the current UI already does stays as it is.

### 11.1 Keep from v1
- **Layout:** the shell (sidebar, header with memory meter, jobs chip, activity bell and search), routes, the command palette, toasts, dialogs and the `Shift+D` mock panel.
- **Service pages:** every service-page tab, including the API explorer with its response viewers and Make room.
- **Other pages:** Models (table, drawer, scan, verify, delete), Outputs (grid/list, day groups, detail drawer, audio player) and Settings.
- **Components:** `OutputCard` and `JsonView`.
- **Look:** the light and dark tokens, and the accessibility work.

### 11.2 Housekeeping
- **Fold in GAIFA's edits:** everything listed in `web/PATCHES.md` (edits 1–9: the hybrid API switch, the real version, MOCK notes, page modules through `ModPage`, model events and verify progress, live outputs in the drawer, Make room from the API tab) becomes part of the export, so that list can go back to empty. Keep `api.js`, `mod-ui.js` and `ModPage.dc.html` as they are (they are GAIFA's, not the export's), and never change `support.js`.
- **No raw-template requests:** markup with `{{ … }}` in `src`, `poster` or SVG `d` attributes makes the browser fetch or parse it before `support.js` renders it (404s and console errors today). Avoid it, for example by wrapping such markup in `<template>`.
- **Renames:** "Hub" → **GAIFA** everywhere (logo text, titles, the down banner). `bin/hub` → `gaifa` (CLI hints in the banner, Settings → About, and the "Add a mod" card).
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
*Since plan overview-bento: three views (no Services) and a bento Dashboard; see §11.11b.*

A segmented control at the top right of the Overview switches views. The choice is kept in the URL (`#/overview?view=dashboard`) and in `localStorage`.

| View | What it shows |
|---|---|
| **Dashboard** (default) | A KPI strip, then a grid of widgets (Section 11.5) |
| **Services** | v1's tiles in the compact form above, with sparklines |
| **Table** | One dense row per service: state, load, a memory bar with the number, a 1 h memory sparkline, idle time, running jobs, last error (truncated) and quick actions. Columns can be sorted. |
| **Timeline** | One swimlane per service over 1 h / 6 h / 24 h / 7 d (Section 11.6, `Timeline`). Each lane shows state bands (stopped, starting, ready, failed), when models were loaded, jobs as bars, outputs as dots, and warning/error markers. Hover for details; click to jump to the service, job or output. |

### 11.5 Dashboard widgets
*Since plan overview-bento the widgets are tiles of fixed sizes, and the KPI strip is four number tiles; see §11.11b.*

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
| `getHardware(refresh?)` | `GET /api/system/hardware[?refresh=true]` | `Hardware` (plan 35.2; Settings → About): read once and cached; `refresh` reads the machine again |
| `getRepos(refresh?)` | `GET /api/repos[?refresh=1]` | `Repos` (plan mod-repos 3.5; Settings → Services → Repositories): the mods that are their own repositories |
| `fetchRepos(id?)` | `POST /api/repos/fetch[?id=]` | `Repos`: asks GitHub what's new (the one call that does) |
| `repoIncoming(id)` | `GET /api/repos/{id}/incoming` | `{id, ok, commits: string[], refused: string[], message}`: what an update would bring in |
| `updateRepo(id, {to?, commit?, force_busy?})` | `POST /api/repos/{id}/update` | `RepoUpdate` (202, in the background; `repos` events per step, the result on `getRepos`); `409 repo_refused {refused}`, `409 repo_update_running` |
| `pinRepo(id)` | `POST /api/repos/{id}/pin` | `{ok, old, new, commits, refused, staged, committed, message}`: the checkout as GAIFA's pin, staged |
| `getLlmEngines()` | `GET /api/llm/engines` | `LlmEngine[]` (plan llm-servers 3.4; Settings → LLMs → On this machine, the Chat picker): every mod with `[llm]` |
| `loadLlm(sid, id, makeRoom?)` | `POST /api/llm/{sid}/load[?make_room=1]` `{id}` | `LlmAction` (202); `409 needs_room {plan}` (the mod's own), `409 engine_stopped`, `404 engine_not_found` |
| `unloadLlm(sid, id?)` | `POST /api/llm/{sid}/unload` `{id?}` | `LlmAction`: that model, or all of them |

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
interface DoctorCheck { area: "models" | "manifests" | "paths" | "ports" | "units" | "disk" | "offline" | "repos";
                       level: "ok" | "note" | "warn" | "fail"; title: string; detail: string; fix?: string }
interface Hardware { os: "linux" | "darwin" | "windows"; arch: string; wsl: boolean; container: string;   // plan 35.2
                     distro: Record<string, string>; kernel: string; cpu: string; cpus: number; ram_bytes: number; pkg: string;
                     gpus: HardwareGpu[]; accels: string[];   // rocm | cuda | xpu | mps | vulkan, best first; cpu last
                     unified: boolean }                       // one memory pool: every GPU shares the system's RAM
interface HardwareGpu { vendor: "amd" | "nvidia" | "intel" | "apple"; name: string; memory: "unified" | "dedicated" | "unknown";
                        vram_bytes: number; arch: string; driver: string; pci: string; index: number; vendor_index: number;
                        runtimes: Record<string, string>; accels: string[]; problems: string[] }
// plan llm-servers 3.4: the local engines ([llm] mods, architecture §4.3)
interface LlmEngine { id: string; name: string; state: ServiceState; running: boolean;
                      engine: { state: string; loaded: string[] } | null;   // null while the mod is stopped
                      models: LlmModel[]; error: string | null }
interface LlmModel { id: string; name: string; format?: string; size_gb?: number; memory_gb?: number; context?: number;
                     downloaded?: boolean; loaded: boolean; relay_model?: string }   // relay_model: the name a chat picks once loaded
interface LlmAction { id?: string; state?: string; loaded?: string[] }             // plus the mod's own fields
// plan mod-repos 3.5: relay, lcpp, tts and gen3d are git submodules of their own repositories
interface Repos { repos: RepoState[]; settings: Settings["repos"]; last_fetch_ts: number | null; update: RepoUpdate | null }
interface RepoState { id: string; path: string; url: string; branch: string; initialized: boolean;
                      pinned: string | null; staged_pin: string | null; head: string | null; on_branch: string | null;   // null: detached
                      dirty: number; untracked: number; ahead: number; behind: number; unpushed: number;
                      pinned_on_remote: boolean | null; checkout_vs_pin: "same" | "ahead" | "behind" | "diverged" | "unknown";
                      remote_url: string | null; last_fetch_ts: number | null; fetch_error: string | null;
                      problems: RepoProblem[]; level: "info" | "warn" | "error" | null }
interface RepoProblem { code: string; level: "info" | "warn" | "error"; title: string; detail: string; fix: string }
interface RepoUpdate { id: string; running: boolean; started: number; steps: { ts: number; text: string }[];
                       result: { ok: boolean; message: string; old?: string; new?: string; commits?: string[]; refused?: string[];
                                 rolled_back?: boolean; staged?: boolean; committed?: string | null } | null }
interface Doctor { ts: number; ok: boolean;                                  // ok = no "fail" checks
                   counts: { ok: number; note: number; warn: number; fail: number }; checks: DoctorCheck[] }
interface WidgetData { unit?: string; t?: number[]; categories?: string[];
                       series: { name: string; values: (number | null)[]; axis?: "left" | "right" }[];
                       rows?: Record<string, string | number>[] }   // for kind "table"
```

**Mods declare widgets in their `service.toml`** (see architecture §4), and GAIFA proxies and caches them for 30 s. Each `ServiceSummary.stats[i]` also gains an optional `series` field (the metric name), so tiles can draw sparklines.

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
- **Settings → Machine → Memory:** a 24 h memory chart with the reserve line drawn, which updates live as you edit the reserve value.

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
- **States:** every widget loading, empty and in error; a range switch; a legend toggle; "View as table"; the Customize panel; each of the four Overview views in compact and comfortable; and every chart at 360 px (Timeline scrolls sideways inside its card; widgets stack); the Settings section list while a long section scrolls (in view under the header) and at 360 px (above the content), and a Settings section with every group collapsed (a list of summaries).
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
- **Density:** `Settings.ui.density` (`config.toml`), whose default is `compact`; the browser keeps a copy only to paint the first frame (settings-that-stick 3.3). The theme works the same way.

---
---

# Part B — Service pages (build after Part A is approved, one per pass)

Each page lives in its mod's folder, as `services/<id>/ui/Page.dc.html` (a Claude Design component) or `ui/page.js` (a page module); see Section 5. It calls its service's native API through `ctx.call(...)`, which reaches the GAIFA proxy at `/api/s/<id>/…`. Each pass:
- extends `mock.js` with that service's native endpoints
- sets `has_page: true`
- keeps the generic Outputs / API / Logs / Settings tabs

**Every Part B page follows revision 2:** compact by default, built from the Section 11.6 chart components, and with at least one chart. **Reuse the existing UIs as functional references; don't redesign behavior that already works.** Each page is built in the backend-plan phase that moves its mod in, and wired live in that same phase.

### B1. LLM Launcher (`lcpp`): port the existing lcpp UI

The attached lcpp UI was built from an earlier Claude Design brief. Its views become tabs: **Instances**, **Catalog**, **Playground**, **Relay publishing**. Its Settings view folds into a "Launcher settings" section under the generic Settings tab. The GAIFA shell supplies the sidebar, header and memory meter, so drop lcpp's own. Its `api.js` method list stays the same, with every path prefixed by `/api/s/lcpp`. **Charts:**
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
  - for an image engine: the picture (Upload, which becomes a GAIFA output, or Recent outputs), the engine's presets (Fast default, Base, TRELLIS.2 Draft) and every setting from `/v1/options` `engines`, face-budget shortcuts (Raw / 200k / 100k / 50k), its licence and where it runs
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

### 11.11b The bento Overview (plan overview-bento, 2026-11-10)

The Dashboard below §11.11 was replaced; §11.4's Services view and §11.5's KPI strip and spans no longer apply. As built:
- **The grid** (`web/bento.js`): 12 columns, fixed rows (60 px compact, 68 px comfortable; gaps 10 and 14 px), dense packing. Every tile is one of six sizes, columns × rows: `xs` 3×1 (a number), `s` 4×2, `m` 4×3 (a list), `w` 6×3, `l` 8×3 (a wide chart), `f` 12×2 (a strip). Each tile lists the sizes it allows. Under 1100 px, `s`, `m` and `w` take 6 columns and `l`, `f` 12; under 760 px everything is full width but `xs`, two to a row. Content that doesn't fit scrolls inside its tile; charts fill it exactly (`fit`, legend included).
- **A tile:** a one-line header (icon, title, a count badge, range chips, ⋯ with Size, View as table, Open page and Hide), then its body.
- **Default tiles, most relevant first:** Needs you `s` (alerts, failed mods and manifest errors, approvals waiting (opens the header's Approvals), memories to review; "All clear" when none) · Running now `s` (running then queued jobs with their live thumbnail and progress, the GPU slot when held or waited on, models in memory) · Memory `s` (used / total, the three largest users over 0.5 GB and Other, free, the reserve line, a 1 h sparkline when the tile is tall enough) · four numbers `xs`: services ready, outputs today vs yesterday, LLM tokens today, the next scheduled task · Services `m` (ready, stopped and failed counts; problems and mods working or holding memory as rows, the idle ones as pills) · Today `m` (the calendar's day: overdue to-dos, all-day items, then items and scheduled tasks by time, past ones dimmed, the current one marked "now") · Recent chats `m` (top-level chats, as many as fit, working / waiting / age) · Memory over time `l` · Activity `m` · Recent outputs `f` · LLM traffic `w` (while relay declares it) · Service uptime `w`.
- **Off by default** (Customize turns them on): Jobs running and Models loaded (numbers), Memory now (the donut), GPU queue, Outputs per day, Activity heatmap, Job durations, Model storage, GPU memory, Outputs by service, and every mod widget (sized from its `span`).
- **Tiles that read mods:** Today shows while the calendar or the agent mod runs (`GET /api/s/calendar/v1/agenda?day=today`, the agent's `GET /v1/tasks`), Recent chats and the next task while the agent runs (`GET /v1/threads?limit=12`); each polls every 30–60 s while the tab is visible.
- **Customize** turns on editing: tiles get a dashed border and a grip; drag one onto another to put it before that one, or focus the grip and use the arrow keys. A panel lists every tile with a switch and a size, plus Reset and Done. Saved as `[ui.dashboard]` `order`, `hidden` (default tiles turned off), `shown` (off tiles turned on), `sizes` and `ranges`.
- **Views:** Dashboard, Table, Timeline. A saved or linked `services` view opens the Dashboard. The alert strip shows on Table and Timeline; the Dashboard has them in Needs you.

### 11.12 Agent tools and approvals (plan Phase 13)

The `tools` area. The chat (Stage D) and outside clients (MCP) use the same calls; the UI shows them in the API tab (tool badges with the risk level), the header **Approvals** popover and the chat's parameter cards.

**Methods** (area `tools`):

| Method | Endpoint |
|---|---|
| `listTools({q?, names?})` | `GET /api/tools` (`q`: best 8 by keywords; `names`: these, 404 `unknown_tool` with `data.close`) |
| `getToolIndex()` | `GET /api/tools/index` |
| `callTool(name, args, {mode?, origin?, wait?})` | `POST /api/tools/{name}/call?wait=` (`mode`: plan · manual · accept_edits · auto · bypass; old ask, read_only accepted, plan 27.4) |
| `getToolCall(id, {wait?})`, `cancelToolCall(id)` | `GET /api/tools/calls/{id}`, `POST /api/tools/calls/{id}/cancel` |
| `listApprovals({state?})`, `getApproval(id)` | `GET /api/approvals` (pending; `state=all`), `GET /api/approvals/{id}` |
| `decideApproval(id, {approve, args?, reason?, remember?, confirm?, wait?})` | `POST /api/approvals/{id}`: the edited `args` are what runs; `remember: "once" \| "thread" \| "always" \| "sites"` (plan 25.2; `sites`: a `url:host` tool on any site in this chat, plan web-approvals) also writes a grant (`thread` needs a call from a chat, else 422 `no_thread`; `always` for `execute`/`destructive` needs `confirm: true`, else 422 `confirm_needed`); the result carries the `grant` |
| `listGrants({thread?, tool?})`, `revokeGrant(id)` | `GET /api/grants`, `DELETE /api/grants/{id}` (plan 25.2); `DELETE /api/grants?thread=` ends a chat's grants; `POST /api/grants` writes one ahead of time (a scheduled run's pre-allows, scheduled-tasks 2.1) |
| `listJudged({thread?, limit?})`, `getJudgeStatus()` | `GET /api/judge/recent` → `JudgedCall[]` (newest first), `GET /api/judge/status` → `JudgeStatus` (the Auto mode's judge, plan 30.3, 30.5); a verdict is `allow`, `ask` or `refused` (asked in an unattended run, scheduled-tasks 2.1) |

Also `GET /api/tools/calls/{id}/result?offset=&limit=` pages a capped result. **Events:** `{type: "approval", approval: Approval}` when one is created or decided; `{type: "tool_call", call: ToolCallResult & {origin}}` as a call starts, makes progress and ends (`origin.grant`: the grant that let it run without a card); `{type: "grant", grant: Grant}` when one is written and `{type: "grant_deleted", id}` when one is revoked or ends.

**Grants (plan 25.2).** A tool may declare a `grant_key`: `url:host` (the host of its `url` argument), `arg:<name>` (that argument as is) or `const:<x>`. A grant covers calls of its tool whose key matches (a null key covers every call); a `thread` grant only calls from that chat, an `always` grant every caller (MCP and the API included). The card shows the key ("on github.com", "in ~/Projects/foo") next to the risk.

```ts
type Risk = "read" | "write" | "generate" | "network" | "execute" | "destructive";   // plan 25.1
interface ToolIndexItem { name: string; mod: string;                // "hub" for the hub's own tools
                          risk: Risk; core: boolean; summary: string; available: boolean; why?: string;
                          group?: string }                          // mcp-client 4.1: a group within its mod ("mcp:blender"); else the mod
interface Tool extends ToolIndexItem { description: string;
                          grant_key?: string;                       // "url:host" | "arg:<name>" | "const:<x>" (plan 25.2)
                          parameters: JSONSchema;                   // one flat object; file inputs carry "x-kind": image|video|audio|mesh|file
                          ask: string[];                            // inputs the user chooses: editable on the parameter card
                          examples: object[]; job: boolean; source: "manifest" | "tools_source" | "hub";
                          view?: { kind: "table" | "bar" | "hbar" | "line" | "area" | "donut"; rows: string; columns?: { key: string; label: string; format?: string }[];
                                   x?: string; y?: string[]; unit?: string; title?: string } }   // plan 46.1: its result's default view in Chat
interface ToolOutput { output_id: string; ref: string;              // "output:<id>": what file inputs take
                       kind: string; title: string; url: string; preview?: string; summary: string; prompt?: string }
interface ToolCallResult { status: "needs_approval" | "denied" | "running" | "done" | "error" | "cancelled";
                           tool: string | null; call_id?: string; approval_id?: string;
                           result?: any;                            // JSON over 8 KB: {truncated, preview, full}
                           outputs?: ToolOutput[];
                           error?: { code: string; detail: string; fix?: string; problems?: object[];
                                     fixes?: ({ label: string; tool?: string; arguments?: object; service?: string; action?: "restart"; retry?: object; command?: string })[];   // plan 46.5
                                     log?: string[] };                // plan 46.5: the mod's lines around the failure
                           progress?: number; note?: string; job_id?: string; elapsed_s?: number;
                           live?: Live;                             // running: the job's live progress (plan 44.2); GET …/calls/{id}?wait=&changed=true answers at its next change
                           arguments?: object; ask_fields?: string[]; risk?: Risk; schema?: JSONSchema; description?: string;
                           filled?: string[];                       // needs_approval; filled: arguments the hub chose
                           filled_by?: { [field: string]: "default" | "carried" | string };  // how, an x-options default, carried in this chat, or a preference ("pref" + its id, plan 21.7)
                           grant_key?: string;                      // needs_approval, the tool's grant key kind (plan 25.2)
                           grant?: Grant;                           // a decision with remember: thread | always | sites
                           grant_id?: string;                       // a grant ran the call (a scheduled run's pre-allow, scheduled-tasks 2.1)
                           why?: string;                            // needs_approval: why it asks (the mode, a list, the risk; plan 27.4)
                           limits?: CallLimits;                     // needs_approval for a tool with a preflight (a workspace call, plan 27.4)
                           judge?: Judged }                         // Auto mode: the judge's verdict and why (plan 30.3)
interface Judged { verdict: "allow" | "ask" | "refused"; reason: string;   // refused: asked in an unattended run (scheduled-tasks 2.1)
                   source: string;                                  // "rules" | "model" | "fail-closed"
                   rule: string; ms?: number; model: string;
                   summary: string;                                 // the command, URL or file, in one line
                   why?: string;                                    // the step row: "Auto: ran (judged safe: …)" | "Auto: asked you (…)"
                   refused?: boolean }                              // on a result: the judge asked, no one was there (scheduled-tasks 2.1)
interface JudgedCall extends Judged { id: number; ts: number; tool: string; thread?: string; call_id?: string; approval_id?: string;
                                      suggest?: string[] }   // allow rules that would cover a command the model asked about (plan 30.7)
interface JudgeStatus { available: boolean; backend: string; model: string; detail: string;   // Auto is offered only when available
                       choices: string[] }   // the decide mod's usable models (the picker in Settings → Permissions → Auto judge)
interface CallLimits { action: "read" | "edit" | "delete" | "commit" | "command" | "network" | "host" | "remote" | "change";
                       folder?: string; level?: string; allow_bypass?: boolean; path?: string;
                       key?: string;                                // what "allow in this chat" covers: the folder and the exact command
                       once?: boolean;                              // asks every time: only "Allow once" (host runs, commits, git remotes)
                       ask_folder?: { path: string; level: string; max_level: string; capped?: string; environment: { id: string; name: string } };   // plan 34: a folder outside the chat's environment
                       preview?: { summary?: string; diff?: string; command?: string; where?: "sandbox" | "host"; network?: boolean; cwd?: string; note?: string } }
interface Grant { id: string; tool: string;                         // a name glob
                  key?: string;                                     // a host, a folder, a constant (absent = every call of the tool)
                  kind?: string; risk?: Risk; scope: "thread" | "always"; thread?: string;
                  created_ts: number; expires_ts?: number; note: string; used: number; last_used_ts?: number }
interface Approval { id: string; tool: string; arguments: object;  // as the model sent them
                     final?: object;                                // as run (after edits)
                     ask_fields: string[]; risk: Risk; origin: object;
                     state: "pending" | "approved" | "denied" | "expired"; reason?: string; call_id?: string;
                     created_ts: number; decided_ts?: number; schema?: JSONSchema; description?: string;
                     filled?: { [field: string]: "default" | "carried" | string };   // what the hub chose: a default, a preference ("pref:<id>"), carried from this chat
                     edited?: string[];                                               // the fields the user changed on the card (plan 21.1)
                     grant_key?: string }                                             // the tool's grant key kind (plan 25.2)
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
- **Similarity badge** (`web/score.js`, 2026-10-21): every result of a search by meaning (the chat list's By meaning, the Outputs page's By meaning, the header Search) shows its score on the right: a small muted badge with the score to two places ("0.58") and a tiny bar filled to it, tooltip "Similarity to your search: 0.58 (higher is closer)": the embed mod's cosine similarity; there's no minimum, so a search always lists its nearest matches and the badge shows how close each is. The header Search (Ctrl K), while the embed mod runs, also searches by meaning after a 350 ms pause on 3+ characters (outputs through `POST /api/s/embed/v1/search`, chats through `GET /api/s/agent/v1/chats/search`; `web/palette-meaning.js`): up to 8, best first, under the name matches, as "Output · by meaning" / "Chat · by meaning" with the badge; name matches carry no score. The footer reads "n results · k by meaning".
- **Thread list** (248 px; a drawer under 760 px of page width): at the top the search box across ("Search", or "Search archived"), then **+ New** (a round + and the word, as Claude Code's) with the **View** button (sliders) on its right; no "Chats" heading (plan 42.1; chats by meaning are in the header's Search, plan 28.5), and per chat Rename (also a double-click on its title) / Move to… (another environment) / Archive / Delete (with a confirm); while a chat's menu is open its letters work: **R** Rename, **M** Move to, **A** Archive (or Unarchive), **D** Delete (each item shows its letter; not while typing); a dot for running (amber), waiting (purple) or failed (red) chats at the right edge of the row, where ⋯ takes its place on hover or focus (both on a touch screen; the user's ask, 2026-11-10); a row shows only the chat's name (no time, no environment; plan chat-history 2.1), and hovering it (or focusing it, or its open menu) highlights it and shows ⋯ at its right edge (always shown on a touch screen); an archived chat listed with live ones is dimmed, with an archive mark before its name, and its menu says Unarchive. **By environment** (plan 41.2, `chat-groups.js`; while the workspace mod is up): one section per environment with a caret (collapse), its name (its folders as the title), a running dot, the chat count, **New chat in** it (`+`) and a ⋯ menu (**Rename** in place, **Manage folders…**); inside, its first 5 chats and *Show more · N* (a full-width divider: a line on each side of the words), which opens all of that environment's chats in place (200 at a time from the agent; then *Show less*; whether a section is open is the page's, not saved; chat-history 2.4) (`GET /v1/threads?environment=`; a deleted environment's chats show under Default); an environment with no chats in this view isn't shown (all of them archived: only under Archived). **By date** (plan chat-history 2.3, `chat-dates.js`): plain headings (11.5 px, dim; no arrow, no count) Today, Yesterday, the dates of 2 and 3 days ago ("Nov 6", "Nov 5"), Last week (4 to 7 days) and Older, from local midnight; a chat's day is its last activity (its creation when ordered by Created), and ordered by Name the chats in each heading go A to Z. The **View** button, the one place to choose which chats show (plan chat-history 2.2; no Archived chip at the bottom): Show (Chats · Archived · Both), Group by (Environment · Date · None; Environment only while the workspace mod is up, else the list is flat), Environments by (Recent activity · Name · Created), Chats by (Recent activity · Name · Created), saved in `config.toml` (`[ui.chat.list]`, with the collapsed sections; settings-that-stick 3.3). A search, or grouping off, shows one flat list, each row with its name only; flat, by date or searching, the list holds the 20 newest (in the chosen order), then *Show all · N* (N from `GET /v1/threads/count`) opens the Show all page (`#/chat/all`, with the search as `?q=`; chat-history 2.4).
- **All chats** (plan chat-history 3.1, `chat-all.js`, `#/chat/all`, also from the palette): the main area instead of the panes, the sidebar beside it; the panes come back as they were when a chat opens (`#/chat/<id>`, in the active pane) or with × (back to the active pane's chat). A title "All chats" with the count, a search (focused on open; `?q=` from the URL; titles and messages, as the sidebar's), Show and Group by as chips (the sidebar's saved view: changing one changes both), then the rows: by date (the sidebar's headings, over what's loaded), by environment (a heading per environment) or flat. A row is the sidebar's (⋯ menu, double-click rename, drag into a pane) with its environment (dim) and its date at the right: a time today ("14:32"), Yesterday, "Nov 5", or "Nov 5, 2025" in another year. Archived rows (Both) are dimmed. Pages of 50 load as the end scrolls into view, until the count; a search or a view change starts again. Keys: ↑/↓ through the rows, Enter opens, / focuses the search. Under 760 px it fills the screen, with the menu button for the chat list.
- **Scheduled tasks** (plan scheduled-tasks 4.1–4.5, `chat-tasks.js`, `chat-task.js`, `chat-task-edit.js`, `chat-task-panels.js`, `chat-when.js`): a **Scheduled** row right under Projects (a clock; the row opens `#/chat/tasks`; its chevron folds the tasks open as an accordion: on first, then by their next run, up to 8, then *All scheduled · N*, each with its next time, or a dot while it has unread runs; open or folded is kept on the hub, `hub.chat.tasks.open`; the row has a dot while any run is unread). **The tasks page** (`#/chat/tasks`): "Scheduled", a search (names and instructions) and **New task**; the tasks as cards (two columns, one when narrow), each with its name, the schedule in words and its next run ("Weekdays at 07:00 · next tomorrow 07:00", or *off*), its project, its last run ("Done · 1 refused, today 13:55"; red when it failed) and an on/off switch. **The editor** (a dialog for New task and Edit): name; instructions; the schedule (Hourly: every N hours at minute MM, *Only between* two times, *Weekdays only*; Every day and Weekdays: a time; Weekly: a day and a time; Monthly: a day of the month and a time, "a shorter month: its last day") with its words and next run under it; Project (and *Only its own folders*); Model; Mode (Plan, Accept edits, Auto, Bypass, which shows a warning); *Allowed ahead of time*: tools or globs, sites or *Every site*, MCP servers; skills always on; *Use my profile*, *Use the project's memory*; *Archive run chats after N days*. Saving checks the task: a new task with problems is saved turned off and the dialog lists them with their fixes (and the warnings), with *Open the task*. **A task's page** (`#/chat/tasks/<id>`): "All scheduled", the name and its switch, the schedule, the next run, its project and mode; *Run now*, *Test run* (opens the test run's chat, where its calls show cards), *Edit*, *Delete* (the confirm says its runs stay as chats); the instructions; the runs, newest first, each with when it ran, its state as a badge (Done, Failed, Skipped (still running), test, late, *N refused*), a dot while unread and *Open chat*; picking one shows on the right its **Judgement log** (each call: allowed, refused, denied, asked or pending, by pre-allowed, rules, the judge, the mode, you or the agent, and why), then *From this test run* (for a test run: what you approved, each with *Allow*), *Notes on how to do it* (edit, remove, add), *Folders* (its own, with levels; Add folder through the desktop's chooser) and *Allowed ahead of time*. Opening a run's chat anywhere marks it seen. **A project's page** gains a *Scheduled* panel: its tasks with their next run, and *New task* with the project chosen. The judge's verdict on a step in a run reads "Auto: refused, no one to ask (…)", and Settings → Permissions' judged calls show *refused* in red.
- **Sub-agents** (plan agent-workflows 3.1–3.6, `chat-tree.js`, `chat-agents.js`, `chat-agent-requests.js`, `chat-mock-agents.js`): **in the sidebar** a chat that started sub-agents has a chevron at the left of its row (in every list: flat, by environment, date or project, and Show all); open, its sub-agents fold out under it as a tree (├ └, deeper ones indented), each with a branch icon, its label, a dot while it runs (amber, pulsing), waits for a free slot (grey), waits for you (purple) or failed (red), and an amber dot once it ended and nobody opened it; opening one clears that dot (`POST /v1/threads/{id}/seen`). Which rows are open is kept on the hub (`hub.chat.tree.open`); the trees follow the page's `watchWorkflows` events, and a parent's row learns of new sub-agents from them. Sub-agents stay out of the list itself (a search finds them). **In the parent's activity fold** the `agent` tools have words ("Ran a sub-agent", "Started a sub-agent" in the background, "Heard back from a sub-agent", "Said no to a sub-agent", "Passed a request to you"; the sentence quotes the task), and under the fold each sub-agent the turn started has a live card (`live:agent`): a branch icon, its label, its state as a badge (its current step while it runs: "running workspace_read", "thinking", "waiting for a free slot", "waiting for you"; then "finished"), *writer* when it may change files, the steps it took, the start of its answer once it finished, Stop (icon) while it runs and Open (icon), which puts it in a pane beside this chat (`gaifa:open-chat-beside`; a pane already showing it becomes active; narrow: it opens in its place). While background sub-agents work, a strip above the composer says "N sub-agents at work:" with a chip per sub-agent (its dot, label and state; a click opens it beside). A background sub-agent's end (`agent_done`: "<label> finished in the background · Open") or request (`agent_request`: "<label> asked to run <tool>") heads the turn it starts, as a user message would; reviews (`agent_review`: "Passed to you · “reason”", "Said no", "You allowed it") are rows in the fold. **A sub-agent's request on the parent** (`chat-agent-requests.js`): each card a sub-agent waits on is docked on the parent's composer with the chat's own cards: "<label> wants to run <tool>" with Open (beside), what the parent agent said when it passed it on (in italics, "The chat’s agent is reviewing it…", before it has), and the parameter card with Allow once, Allow in this workflow (a grant on the workflow's root, so every sub-agent of it), Always allow and Deny; a question lists its questions and *Answer in its chat*. Deciding toasts "Allowed <tool> for <label>". The header's Approvals popover says "from a sub-agent" for one, with *Its parent chat →* beside *Open chat →*. **A sub-agent's own chat** (`chat-header.js`): its header starts with a link back, "↖ <parent's title> /", and after the title the chips *sub-agent*, *reads only* or *writer* (and *from another agent* for one started over `/mcp`; the last two not when the pane is narrow); it has no Learning toggle (it never learns); its composer works as any chat's (your message is a normal user event). Delete and Archive on a chat with sub-agents say so ("The chat and its 3 sub-agents and their histories are deleted"; "Archived with its 3 sub-agents"). **A chat another agent started** over `/mcp` (agent-workflows 4.3): its row has a small chip with the client's name ("Claude Code", "Codex", from `settings.external.client`) and its header "from Claude Code"; it is otherwise an ordinary chat in the list (its cards are yours to decide, its sub-agents nest under it). **Settings → Agent → Model** ends with the sub-agent rows (`[agent.workflows]`, each with its key, default and Reset): *Sub-agents* (on/off), then, while on, at once on this machine, at once on remote and cloud models, per turn, depth, a sub-agent's steps, tokens per turn and the smallest context window.
- **Projects** (plan projects 5.1–5.4, `chat-projects.js`, `chat-project.js`, `chat-project-panels.js`, `chat-project-groups.js`): a **Projects** row under + New (a folder icon and the word open `#/chat/projects`; its chevron, inside the row, folds the projects open right under it as an accordion: the pinned projects, then the most recent, up to 8, then *All projects · N*, the open project highlighted; open or folded is kept on the hub, `hub.chat.projects.open`; New and Projects sit close together, 28 px rows). **The projects page** (`#/chat/projects`, the main area): "Projects", a search (names and descriptions), *Sort by* (Recent activity · Name · Created; kept on the hub) and **New project** (a dialog: name, description, instructions); the projects as cards in two columns (one when narrow), pinned first, each with its icon, name, description, chat count and last activity, and a pin on hover. **A project's page** (`#/chat/projects/<id>`): "All projects", the name and description (each edited in place), a composer for a new chat in it (the project's mode and model under the box; its first message makes the chat, which opens in the panes) and Recents (20, then *Show all*: the Show all page filtered to the project); on the right the panels Instructions, Files (upload or pick from Outputs), Pages (URL, "fetched 2 h ago", status, freshness 15 min · 1 h · 6 h · 1 day · 1 week · never, Refresh, Remove), Memory (edit, forget, Open in Memory), Folders (its environments, primary first: drag or ↑; its own folders and their level; Add folder through the desktop's chooser) and Defaults (model, mode, tool groups off, MCP servers on, skills always on), then *Delete project…* (the confirm says the chats, memory and files stay). **A project chat** shows the project's name in the environment's place under the box; its menu opens the project, lists the folders it can use and offers *Remove from project*. A chat's ⋯ **Move to…** lists Projects (and *No project* for a project chat) above Environments, each with a line on what the move does. **Group by: Project** (the View menu, when there are projects; *Projects by* orders them): a section per project with chats here (its name, count, `+` New chat in it, ⋯ *Open project*; 5 chats, then *Show more*), then *No project*. The Show all page gains Group by: Project and a *Project* filter (`?project=`). A project chat's activity draws the pages fetched again for a message as one step ("Refreshed 2 pages"), and the context meter's popover has a *Project* part.
- **Several chats side by side** (plan chat-split, `chat-split.js`, `chat-layout.js`, `chat-pane.js`): the chat area is a tree of panes, each a whole chat (header, thread, dock, composer). **Split** (the two-column icon at a header's right) opens a new chat beside the pane, or below it when the pane is taller than wide; a chat **dragged from the list** onto a pane shows a shaded zone: the third at each edge splits that way, the middle opens it in that pane; a pane **dragged by its grip** (the dots at the header's left) moves to that side, or swaps chats when dropped on a middle; **×** closes a pane (the chat stays in the list). The **divider** between two panes drags to resize (double-click: equal sizes); no pane gets smaller than 320 × 240 px, and a split or move that would is refused with a toast. The **active pane** (a 2 px accent line along its top) is the one the URL names; a click anywhere in a pane makes it active, and opening a chat from the list, a link or Back opens it there (or activates the pane already showing it). The layout is kept in this browser (`gaifa.chat.layout`); a deleted chat's panes close. Under 760 px only the active pane shows, with a tab per pane above it. Any number of panes: every open chat's events come over one connection (`/v1/streams`, `chat-streams.js`); against an older agent without that route each pane opens its own stream and four panes are the most.
- **Header:** the title (click to rename), the running / waiting state, the **context meter** (`8.6k / 131k` with a bar; a popover with the breakdown, the 70% and 85% compaction marks and Compact now), Learning, and Branch (copy the chat).
- **Controls row** (plan 42.3, `chat-controls.js`, after Claude Code's): under the message box, quiet buttons (no outline until hovered) that open small menus, not selects: the **environment** (⌂ its name, +n for folders allowed in this chat only), the **mode** (its name; the menu lists Plan / Manual / Accept edits / Auto / Bypass with a line each, plan 27.4: Bypass only when the workspace folders this chat used allow it, or before it used one, when one does; Auto disabled with the reason while the judge's model doesn't answer), and on the right the **model** (plan llm-servers 5.1, `chat-model-menu.js`): a search field, then the models grouped **This machine**, **Remote**, **Cloud**, one header per server with its health when it isn't healthy, each model with its window, tools, vision and thinking, and cloud models with their provider's badge (Claude, OpenAI, Gemini). The list is the agent's `/v1/models` (the relay's catalog, one row per id) plus the local engines' models that aren't loaded (`getLlmEngines`), marked **Load** under their engine; a stopped engine shows "Start <engine> to list its models". Load starts the engine if needed, loads the model (on `needs_room` the menu offers **Unload & load** with what GAIFA would unload), the button reads "Loading <id>…" meanwhile, and the chat switches to the model once the relay serves it. Each pane has its own menu and model; Settings → LLMs → Defaults uses the same menu.
- **Thread (Phase 19):** a 760 px column of **turns**. A turn is your message (or "You ran …" for a result button or quick action), its **activity fold**, any agent errors, the **output strip** and the answer. A sticky **Plan** bar shows while any todo isn't done. The view stays at the bottom while you are there (new events, images loading, forms mounting).
  - **The activity fold** (`chat-activity.js`) is closed by default, the running turn included. Its header is the live status: a spinner, "Thinking…" with the seconds counting and the last two lines of thought peeking under it, "Generating an image… 42%" with the step's note, "Writing…", or "Waiting for you to approve below" / "Waiting for your answer below" (a purple shield), with the turn's time on the right. Once done it reads "Ran 2 tools · 2m 58s" (lookups aren't counted; "Looked something up" or "Thought it through" otherwise). A turn with no steps (a plain reply) has no fold.
  - **Opened**, the fold lists the steps with a rule on the left: thinking ("Thought for 4s ›", opening to the text), the agent's updates (its text in a step that called tools), tool calls (a status mark, the step's words and grey detail, percent or time, "needs you" or "next"; a progress bar under the running one), lookups and notes in grey, "You chose …" for an answered question, "Remembered: …", "Made a plan of N steps". A failed call reads "Tried making a 3D model" with the error's sentence as its detail. Steps are described by the arguments that ran (the ones approved on the card, which you may have changed), not the model's.
  - **Split at each message** (Settings → Agent → Model → Steps between messages; `config.toml` `[ui.chat] steps`, the same in every browser, settings-that-stick 3.3; 2026-10-22): instead of one fold, each update the agent wrote between steps is drawn as a message of its own (no reply bar under it), with a fold for the steps before it: "Ran 1 tool", the message, "Ran 2 tools", …, then the output strip and the answer. Each fold's time runs from the previous message; only the last one carries the live status. Thinking on its own (no tools before the message) is a "Thought for 4s ›" row, not a fold. The default stays one fold per turn (`chat-turn.js` `splitTurn`).
  - **A step opens to its sentence:** "Generated with **Z-Image Turbo**, square, seed 81723, from this prompt:", the prompt quoted (a failed step starts with "What it tried:"), "Approved by you" when it was approved, the result ("Made #1 in 18s", or the error and its fix), then **Raw call** (the tool name, the error code, the arguments and the result as JSON).
  - **The output strip** (`chat-results.js`): the turn's outputs (not the pages the web tools saved: they're hidden outputs, listed by the reply bar's Sources; 2026-10-21) as 56 px `#n` thumbnails when there's more than one; the picked one (the newest by default) as the result card, its preview capped at 300 px.
  - **Dictation (plan 29.3):** a microphone button next to Upload, shown only while the `stt` mod is up. Click to start and stop, or hold to talk; the microphone goes through an AudioWorklet that resamples to 16 kHz, and int16 frames go to `WS /api/s/stt/v1/stream`. Committed text and the live tail are written into the box after what was already typed; Stop flushes the rest. A refused microphone or a closed stream shows its reason beside the button (`web/chat/chat-mic.js`). **Speech input (plan 29.4)**, in Settings → Speech → Dictation (the button has no menu of its own): the microphones the browser sees, ranked by the user (matched by label; the first one present is used, the next on unplug, and a higher one takes over when plugged in, even mid-dictation), which one is in use, a level test, the language, the preset and the button's mode (click or hold, click only, hold only). While listening the composer shows only the button (tinted) and a thin level bar along its top; the mic's name, and "On the CPU" with why (e.g. "On the CPU: Images & Video is using the GPU") while the stt mod runs dictation there (its `ready` or `device` message), are in the button's title. Saved in `Settings.speech_input` (`config.toml [speech_input]`).
  - **Sending** (plan chat-responsive 1.3): a message is drawn the moment it's sent (`ChatPane`'s `pending`, drawn by `buildView`'s `live.pending`), a little dimmed with its turn's status header already running, and its user event takes its place when it arrives (matched by `client_id`, or the seq the send answered; same key, so nothing jumps). A new chat's first message makes the chat in the same request (`create({…, message})`), and the pane keeps what it drew while it opens the new chat's URL. A message that couldn't be sent stays in the thread marked **Not sent** with the reason, **Retry** and **Edit** (back into the box with its cards and attachments).
  - **The queue** (plan chat-responsive 2.2, `chat-queue.js`): while a turn runs, Enter and Send queue the message (the placeholder says so; **Ctrl/⌘+Enter** sends it now, into the turn), and Stop sits beside Send (outlined while there's a message to queue; its tooltip says it sends the queue). Queued messages show at once in a strip right above the box: "Queued · N · sent when this reply ends", with "Stop sends them now" and **Clear**; a row per message (its number, its text on one line, attachment and quote-reply counts) with **Edit** (inline; Enter saves, Esc cancels), **Send now**, **×**, and drag to reorder; a row the agent hasn't listed yet is dimmed, "queuing…". When the reply ends (or on Stop) they leave the strip and appear in the thread as messages, answered by one reply. "Queued · N · waits for your answer" while a card waits; "Paused after an error" (red) with **Resume** and Clear after a failed turn. Messages sent while a new chat is being made go to that chat, in order, and what's typed meanwhile stays in the box.
  - **The dock:** pending approvals, questions and parameter cards opened by a button sit above the composer, newest first ("Waiting for you · 2" when several), at most half the page tall. Nothing that waits for you sits in the thread.
- **Settings → Agent → Documents (plan 24.9):** *Whole documents up to* (tokens, or "up to the model's window") and *Reply reserve* (tokens), saved with Save (`saveSettings({documents})`, agent `PUT /v1/settings`).
- **Citations and the viewer (plan 24.7):** in the agent's replies `#n p.14`, `#n pp.3-5`, `#n page 2`, `#n:88`, `#n line 88` and the same after `output:<id>` become links (`a.aichat-cite` with `data-cite`, `data-page` or `data-line`; never inside code), drawn as small chips: the source's name and a dim place (`L112–113`, `p. 14`); with no name, the output's title. A bracketed group as models write it (`[eecs.berkeley.edu #1:112; BLS]`, `[resume #8 p.1]`) becomes a row of chips: a hostname gets the site's icon (the web mod's favicon; none when it has none), a part without `#n` is a plain chip, and the tip names the output it opens; a bracket that cites nothing (`[Medium]`) stays as written. Quoting gives back what the model wrote (`data-src`), and Text only drops the whole group. Clicking one opens the Outputs drawer (wider for documents) on the **viewer**: text and code with line numbers and a highlighter (keywords, strings, comments), markdown rendered or as source, a PDF page by page as the page image with its text beside it (prev / next, the outline as "Jump to…", scanned pages marked), and a search box (the hub's search: words, "a phrase", /regex/) whose hits jump to their page or line. The agent sees inline text and `hub_read_document` windows with numbered lines, so it can cite them.
- **Undo this turn** (plan 27.7): a turn whose tool results name an `undo` route (the workspace mod's edits) ends with an "Undo this turn" button: every file the turn changed goes back as it was; if one changed since, nothing is restored and a toast points to the Workspace page's Activity tab.
- **The reply bar (plan 32.1; `chat-replybar.js`):** under a finished reply, a row: the **Sources** pill (when the turn searched or read the web), **Copy**, then the thumbs; hidden while the reply streams or its turn runs. The answer card gets its turn as `ctx.turn`.
  - **Sources pill:** up to three overlapping site icons and "N sources" (pages the turn read with `web_fetch`, deduplicated by URL; "N results" when it only searched). It opens a popover above or below, whichever fits: "Sources" with a close button, `Results for "<query>"` (two queries, then "and n more"), "Read N pages", then a row per page (icon, host and `#n`, the title on 2 lines, a 3-line snippet: the search result's snippet, else the start of the page), linking to the page in a new tab, with a button that opens the saved page in the viewer; then **Also found (n) · not opened**, folded. Escape or a click outside closes it. Everything comes from the turn's events (`chat-sources.js` `turnSources`); nothing new is stored. Icons are `/api/s/web/v1/favicon?host=…`, else the host's first letter on a tinted circle.
  - **Copy** is a split button: the main part copies with the default; the chevron opens **Text only** (links become their words; citations and the Sources list go), **Including citations** (the reply as written, with "Sources" listing the pages read in place of the model's own list) and **Including thinking and steps** (the turn's thinking, updates and steps in words, then the answer with its sources). Picking from the menu copies and is remembered: the default is the way picked most in the last 24 hours (a tie goes to the latest; none means Text only), kept in this browser (`gaifa.chat.copyModes`, `chat-copy.js`). It says "Copied" or "Copy failed".
- **Reply to parts of a reply (plan 32.2; `chat-quote.js`, `chat-quote-reply.js`):** selecting text inside one of the agent's replies (`[data-quote-seq]`: the answer or an update row) shows a small **Reply** button next to it (nothing opens by itself); clicking it opens a small box: the selection (2 lines, muted) over a "Reply to this…" input with a send button. Enter adds a **quote-reply card** to the composer's card row; Shift+Enter is a new line; Esc or a click elsewhere closes it and adds nothing; Ctrl+C in the empty input copies the quote; the next selection opens a new box at once. Cards (~112 px: the quote with a left bar, the reply, a "Reply" label, × on hover) are unlimited: the row wraps and scrolls past about two rows, and a red alert disables Send past 200,000 characters. A card opens the **Reply** popup: the quote rendered as markdown, read-only, and the reply, editable (Save or Ctrl+Enter, Cancel, Remove); the popup keeps Tab and Escape inside and returns focus on close. Send works with only cards (empty text) when a reply says something. The quote is the selection as markdown: code with its language (the header bar left out), lists numbered from where the selection starts, headings, links, citations as written, pipe tables with alignment; across table cells the touched rows are quoted whole.
- **Web pages (plan 30.8):** a paste that is one http(s) URL is pasted as text and offers **Attach as a web page** under the box; the attach menu starts with **Add a web page (URL)**. While reading: "Reading the page and screening it…"; the chip has a globe icon and a badge: "n removed" (accent), "checked" (green), "patterns only" (accent) or "not screened". The web mod's page (`services/web/ui/page.js`) has one tab, **Read a page**: a URL box, then the title, final URL, a screening badge, characters, screening time and model, the removed passages (line, why, by, start), Copy markdown, Open in Outputs, and Show (as the agent reads it / as it was) over the rendered markdown.
- **Composer** (laid out after Claude Code's, plan 42.2): one box with one line inside it: **+** on the left (a menu: Upload files, Attach an output or a web page, Tool groups, then the quick actions), the text between, and the microphone, voice mode and Send on the right (filled square buttons: Send in the accent, the others in a muted tone; during a turn Send becomes Stop, a filled square); the text grows upward to 40% of the window (at least 120 px, then it scrolls) while the buttons stay on its bottom line. Its quiet buttons (+ and the sidebar's View) show no outline until hovered, focused or open (`.aichat-quiet`); no hint line under it; the chat's controls row sits under the box (plan 42.3). Clicking anywhere in a chat and typing puts the letters in its box. A growing text box (Enter sends, Shift+Enter is a new line, a message sent during a turn is queued and marked), attachment chips (a picker of this chat's and recent outputs; files uploaded with the Upload button, dropped or pasted: images, video, audio, text, code and documents, plan 24.6; each chip shows a kind icon, the name and, for text and documents, the pages or lines and **Whole / Card** (plan 24.9: Whole sends all of it if it fits the window after the reply reserve, Card only its card, neither is auto; the last choice is the chat's default, `settings.doc_mode`), and a text or document chip opens the output; a sent message's attachment chips say `whole` or `card`, and a document asked for whole that didn't fit says how much didn't, under the message), long pastes as files (over 2000 characters or 40 lines a paste is uploaded as `pasted-<HHMMSS>.md`, or `.py`, `.json`, … when the whole paste is one fenced block with a language or parses as JSON; Ctrl+Shift+V pastes it into the box as text), tool-group toggles (Auto / Pinned / Off per mod, and per MCP server as "<server> (MCP server)", mcp-client 4.1 → the thread's `settings.pinned` / `disabled`), the quick actions, and slash commands with a suggestion list: `/compact`, `/clear`, `/model <server/model>` (completing the served ids as you type, llm-servers 5.1), `/context`, and `/<skill>` (sends "Use the <id> skill: …"); a skill other agents keep in the chat's workspace folders is `/<folder>:<skill>` (found by either part, its hint led by the folder's name; skill-sources 2.3).
- **Reconnect:** the stream is `GET /v1/streams?threads=<id>:<last seq>,…` for every open chat at once (plan chat-split 3.2; `GET /v1/threads/{id}/stream?after=<last seq>` on an older agent); a chat opened or closed later joins or leaves that connection with `POST /v1/streams/{id}/threads` (the stream's id is its first event), so the other chats' stream isn't reopened (chat-responsive 3.1), and the pool reopens it only when that call fails; the events about no one chat (projects, tasks, sub-agents) come on one more connection for the whole page, `GET /v1/streams?threads=&watch=projects,tasks,workflows`, shared by every listener (PATCHES #96), so the page keeps three long-lived connections to the hub (with `/api/events`) of the browser's six; on an error it reopens after 0.8–10 s from the last seq it saw, and replays are de-duplicated by seq. Pending question and parameter cards are rebuilt from the event log, so they survive a reload or a restart.
- **Rewind / branch:** hovering a message shows Branch from here: `POST /fork {seq: previous}`, then the new chat opens with that message in the box to edit.
- **Header Approvals** (Phase 13 Wire): a shield button with a purple count; the popover lists every pending approval (chat, MCP, API) as a compact parameter card. Under them, **Memories**: "N memories wait for your review — Review →" (the agent's `/v1/memory/tree` `proposed`, read with the approvals); the count stays the tools' (they hold up a chat), and when only memories wait the button shows a small amber dot (memory-auto-learning 4.1, PATCHES #71). **API tab:** tool badges show the risk (`tool · generate`).
- **The approval card** (plan 25.3; `web/chat/chat-risk.js`, `ParamCard`'s `choices`), the same in the chat's dock, the popover and the API tab:
  - the risk as a badge with its word and colour: `read` green, `write` and `generate` purple, `network` cyan (globe icon), `execute` amber (code icon, amber border), `destructive` red; next to it what a grant would cover ("on github.com", "in ~/Projects/foo", "every search call");
  - **Allow once · Allow in this chat · Always allow**, then **Deny**. "Allow in this chat" shows only for a call from a chat (`origin.thread`); a web page's card (a `url:host` tool) in a chat adds **Allow every site in this chat** after it (`remember: "sites"`, plan web-approvals: any page opens in that chat without a card; links with passwords, long encoded values or private addresses still ask); "Always allow…" on `execute` and `destructive` opens a second confirm ("Always let the agent run code with … in every chat and from MCP, without asking?") before it decides with `confirm: true`. Deny opens a reason box (optional; Enter denies, the agent reads the reason). Ctrl+Enter allows once;
  - for `execute`, the code or command (a string argument named `code`, `command`, `script`, `cmd`, `source` or `shell`, or with `format: "code"` / `x-code`) shows whole in a monospaced, scrollable, editable box: what's in it is what runs;
  - decided: the fold's row says "Approved by you, and allowed in this chat" (or "always allowed").
- **Settings → Permissions** lists the grants (tool, risk, what it covers, "always" or a link to its chat, uses, age, expiry) with **Revoke** (plan 25.2), then **Tool permissions** (plan 30.7): "Never run", "Always ask" and "Run without asking", tool-name globs saved to `[agent.permissions]` (the defaults, `hub_set_preference`, `agent_memory_save` and `agent_memory_entity` ask and `hub_start_service` runs, show as entries).
- **Settings → Agent → Reading web pages and Permissions → Screening** (2026-10-21; `chat-webprefs.js`): screen pages, your documents, transcripts; "Screen pages with" (Same as the judge / A decision model (decide) / Another chat model, with a model picker from each backend's choices; for decide, the threshold; the "confirm with the judge's chat model" checkbox went with plan web-approvals); characters per call × calls at once; "Long pages" (`[agent.web] relevance`: auto, decide, lexical, off) and its model; "Saved web pages: delete after N days (0 keeps them)".
- **Environments (plan 34; `chat-env.js`, the menu in `chat-controls.js` since plan 42.3):** the controls row shows the chat's environment (+n for folders allowed in this chat; **None**, built in with no folders, is where a new chat starts until you pick another, plan 42.5); its menu (compact, 250 px) lists the environments as rows: a click picks one for this chat; **Edit** on a row's right (not None) and **New environment** open the **environment dialog** (plan 43.2, `chat-envedit.js`, as Claude Code's): centred over the page, **Name**, **Folders** (each with Read · Edit · Run · Net, levels above its cap disabled with the reason, and Remove), **Add folder…** (the desktop's own folder chooser, opened at `/` by the workspace mod: "Choose a folder in the window that opened…" while it's open; without a chooser, a path box), and Cancel with **Create** or **Save** (the dialog keeps its changes until then; Save is off while nothing changed); when editing (not Default or None), **Delete…**, whose warning says its chats go too, archived ones included ("This also deletes its 5 chats, including 2 archived. Their outputs stay in Outputs."). The mod's refusals show in the dialog with their fix. Under the rows, "Allowed in this chat" (each removable: that revokes its grant). A new chat starts in the last environment picked (`config.toml` `[ui.chat] environment`, settings-that-stick 3.3), else None (no folders: the agent asks for each one; its menu explains that and offers New environment; no Add to "None" on a folder card); the chip is hidden while the workspace mod is down. A folder card reads "Let this chat read ~/x?" with the path, a Read badge and "not in this chat's environment (<name>)"; its buttons are **Allow for this chat**, **Add to "<env>"** and **Deny** (in the Approvals popover with no chat, Allow once replaces the first). The Workspace page's Environments view: a switcher, New environment, Rename, Delete (not Default), add a folder (path and level), and the folder rows (level up to its cap, allow Bypass, Remove).
- **Sources you shared:** pages attached with "Add a web page" and links you typed that the agent read come first in the reply's Sources, labelled "you shared".
- **Settings → Permissions → Judged calls** (plan 30.7): under the judge picker, **The judge reads** (`[agent.judge] context`, 2026-10-21): "Your words and the call", "+ the agent’s earlier calls this turn" or "+ their results and the agent’s text", saved when picked; then **Your command rules**: "Always allow these commands in Auto" and "Always ask before these", each a list with add and remove and Save; errors show inline, and a 422 names the list. Each recent call the judge's model asked about offers **Always allow `<rule>`** (`suggest`), which confirms and then adds the rule. A verdict from your rules has the source `user`, shown as "your rule".
- **Settings → Agent:** the models, the AGENT.md editor, Memory (structured-memory 5.2: how many facts and entries, a link to review, Recall memories in each message, Let learned facts fade after N days, Open the Memory page; the MEMORY.md editor is gone), skills, the modes and how permissions work. Skills (skill-sources 3.2) are grouped by source (yours, learned, each mod); yours come from Upload a folder… or a SKILL.md or zip (checked for hidden instructions; one that looks off is saved turned off, with why), turn off and on, and delete (kept in `data/agent/skills/.trash/`); From a workspace lists the skills in an environment's folders, each with Copy.

**Events → turns.** `chat-thread.js` `buildView(events, live)` folds the log into items, then `chat-turn.js` `groupTurns(view, {running, now, tools})` groups them into turns of steps by the `step` id the agent puts on thinking, text and tool calls; the last step's text is the answer when that step called no tools. `buildView` folds the log into items as follows. A `tool_call` becomes a **tool** item (its `call`, live `progress` and `tool_result` folded in), or an **approval** item when an `approval` event names it (with its `decision`); `ask_user` becomes a **question** item with its `answer`; a result with outputs adds a **result** item; `update_todos` and `remember` calls are hidden (their `todos` / `memory` events have cards); the plan is pinned on top only while its turn runs or waits on you with steps open (`todosPinned`): a turn that ended, or a message you wrote since without a new list from the agent, leaves it inline, marked *stopped*; `usage`, `state`, `call`, `answer`, `decision` are folded. Every other event type is an item of its own kind. Live `delta` events show streaming text and thinking until the stored `assistant` / `thinking` event of that step replaces them.

**Built-in cards:** user (right-aligned; its quote-reply cards above the text (plan 32.2), each opening the read-only Reply popup with "Go to the quoted reply"; Branch from here (copies the cards into the draft), Copy (each quote as `>` lines, then its reply, then the text), `queued`), assistant (safe Markdown: every character escaped first, only http(s) / mailto / `#` / `/` links; GFM pipe tables with column alignment, in a frame that scrolls sideways when wide; fenced code blocks (``` or ~~~) with a header naming the language and a **Copy** button, highlighted by `chat/highlight.js`; the same renderer draws activity rows and markdown in the viewer), question (1–4 questions, options with descriptions as radio or checkbox rows, "Other…", a schemaForm when the question has a `schema`; Enter on an option picks it and submits a single question; answered → a one-line summary), parameter (the `ask` fields first, plus required fields still empty, through `schemaForm`; the rest under "All settings"; file inputs (`x-kind`) offer this chat's outputs of that kind as thumbnails, then "More from Outputs"; Run / Cancel; a 422 shows inline and the card stays; once decided "Ran with …" or "Cancelled", with the run's progress), result (`#n`, title, kind; image, video, audio, or a 3D poster with "View in 3D" (viewer3d.js); Open in Outputs, Download; action buttons), todos, memory ("Remembered: …"), note, error (detail and fix), compact ("Earlier messages summarized", opens the summary). Anything else gets the **generic card**: the event type, collapsed JSON.

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

**Read aloud (plan 49.1).** A speaker beside Copy under each finished reply reads it in the voice set in Settings → Speech → Voice (`speech_output`): the reply as plain text (no citations, links' addresses or code: "a code block"), streamed from the tts mod (not saved), so it starts in a moment; again stops it, and one reply reads at a time. Voice also sets the speed (Kokoro), "Read every reply aloud" (when a turn ends) and voice mode's pause.

**Voice mode (plan 49.2).** A speaker button beside the microphone (shown while the stt mod is up and Voice can be set) talks with the agent hands-free: it listens, sends what you said once you've been quiet for Voice's pause, reads the reply aloud, then listens again. A bar over the message box says where it is (Listening… with the words so far · Sending… · Thinking… · Speaking (talk to interrupt) · Waiting for you on screen) and "Esc ends". Talking over the reading stops it and listens; an approval or question waiting on screen pauses it until you've answered; Escape or the button ends it, and a refused microphone shows its reason by the button. "Read every reply aloud" stays quiet while voice mode is on.

**Voice mode on the speech model (plan voice-speech-model 3.4, 6.3).** With Settings → Speech → Voice mode set to *Speech model (local)* and the voice mod running, the same button starts a conversation through the voice mod's speech-to-speech model instead: the microphone goes to the mod (`/api/s/voice/v1/realtime`), which finds the end of what you said. **Who answers** is the bar's switch (and Settings → Speech → Voice mode → Who answers; the switch saves the setting and starts the conversation again that way). *Agent answers* (the default): what you said appears in the chat as your message and the chat's own model answers it exactly as a typed one, with its tools, apps, memory, mode and cards, drawn in the chat as any turn; the speech model says each step's text as it comes (the bar: Thinking… while the turn works, Speaking, and Waiting for you on screen while a card waits, which doesn't end voice mode). Talking over it stops the speech, and the turn too if it is still running. *Speech model answers*: it answers aloud by itself within a fraction of a second and writes each turn into the chat as ordinary messages (`via: "voice"`), so the chat's own model reads them when you type again; the rest of this paragraph is that mode. The bar reads "Voice mode · LFM3-Omni-2B" with Listening… · Thinking… · Speaking (talk to interrupt), your words in quotes once written down and the reply's text while it speaks. Talking over a reply stops it; the chat keeps what you heard of it, ending in "…". A message you type, or a card waiting on screen, pauses the conversation (Waiting for the chat); it starts again afterwards and knows that turn. The setting is read each time voice mode starts, so a change in Settings needs no reload. When the speech model can't run (the mod stopped, the model not downloaded, no memory), voice mode carries on with the chat's model and the bar says why; with only the voice mod installed, the button uses the speech model whatever the setting says. One conversation at a time: starting it in another pane ends the first. **Tools (Phase 5):** while the reply uses a tool the bar says what it does (Looking at your calendar… · Searching the web… · Asking the chat's model…); a call that would need a card is refused and the model says so ("That needs your approval in the chat"). When it asks the chat's model, your words appear in the chat as a message, the chat's model answers there as usual (its cards wait on screen; voice mode is not paused for that turn), and the speech model tells you the answer.

**Mute (plan voice-mute 1.3).** Both voice mode bars (the chat-model loop and the speech model) have a **Mute** button (a microphone; crossed out and red, reading *Muted*, while on) and the **M** key toggles it while no text field has the focus. Muted, nothing the microphone picks up is heard: no turn starts and a reply isn't stopped by noise; it goes on and the bar says *Speaking (muted)*, and *Muted* with a grey dot while it would listen. Muting while you talk drops what was heard. Typing still works. The browser's microphone stays open, so unmuting is instant (the tooltip says so). Settings → Speech → Voice mode → **Start muted** (`voice_mode.start_muted`) starts it muted.


**@-mentions (plan 48).** Typing `@` in the message box lists what you can name: this chat's outputs (`#n`: a pick becomes an attachment chip), its folders, and the mods' kinds (`api.listMentions`: voices, workflows, engines). `@voice:` narrows to a kind; `@voi` matches the kind too. ↑↓ and Tab or Enter pick, Esc closes. A pick writes `@voice:Brendon` into the text and goes with the message as a mention; the agent says it to the model and the hub fills that turn's calls with it (the card's field is marked "from your message"), asking when the model chose otherwise.

**Status and fix-it cards (plan 46).** Status results draw as cards under the fold, not JSON: the hub's memory (a bar by mod; each loaded one with Unload), services (Start, Stop), GPU queue (Cancel on a wait), install checks (problems first, with their fix) and what Free GPU freed (`chat-status.js`); a mod's own (vLLM's load through its stages, lcpp's start, the voices with Play sample). A tool that declares `view` in its manifest draws its result as a table or chart with no code (`chat-view.js`): gen3d's jobs, models, sessions, engines, workflows, instances. A step that failed after it ran shows a fix-it card instead (`chat-fix.js`): the error in a sentence, Show the log, and the hub's fixes as buttons (Start or Restart the mod, Free the GPU, Retry with a lighter preset, Retry), which run as your own step. A fix-it card shows only on the chat's newest turn, and goes once a later call of the same tool in that turn worked (2026-10-25: five failed page fetches kept Restart Web and Retry up after the answer); the fold's step keeps the error. `/clear-gpu [mod…]` runs Free GPU.

**Pictures in a reply (plan 47.3).** A picture is drawn once (2026-10-25). An output a tool in this chat made is shown at the top of the turn that made it (the output strip or its live card), so a `![caption](#n)` of it in any reply, or `show` of it, draws nothing. Any other output of this chat (an upload, one shown from Outputs) is drawn where it's written: on a line of its own, as the strip's result card with its buttons (Edit, Make 3D, Describe, Use as reference, …; `chat-cards.js` AssistantCard, `splitFigures`); inside a sentence, a picture or a 3D model's preview (click: Outputs), a video or audio with its controls, at most 360 px tall, with "#n caption" under it. Anything else stays as text, outside pictures included; quoting gives the markdown back; Text only keeps the caption.

**Show (plan 47.2).** The agent's `show` tool draws under the fold in the dashboard's own chart style (`chat-show.js`, `charts.js`): line, area, bar, horizontal bar, donut, heatmap and KPI tiles from inline data, a CSV/JSON output (read and sampled to 500 points) or GAIFA's own data (memory by mod, outputs per day, job times, a mod's stat; refreshed every 30 s); tables sort by a column, filter, page by 50, copy as CSV and save as an output (`chat-table.js`); image and gallery show the chat's outputs. A title, a caption, and "live · 24h" on GAIFA's data.

**Live cards (plan 44.3).** Under a turn's activity fold (open or folded), each tool step with a `live:<tool>` card draws it, while its job runs and after it ends (`chat-live.js` `LiveCards`); the output strip leaves out that tool's outputs, since its card shows them where they were made. A running step of a tool without one shows the kit's generic preview (`LivePreview`) while its job reports a frame. The card gets `ctx.liveCard = {row, live, note, status, outputs, kit}` (`ctx.live` stays "connected to the live hub"). The kit (`web/live-kit.js`, shared with the Overview and mod pages) draws the prototype's look ([reference/live-cards-2026-10/](reference/live-cards-2026-10/prototype.html)): a header with a pulsing dot and the step and time left, a box at the output's aspect (at most 420 px tall) with shimmer and grain and "Waiting for the GPU · …" / "Loading …" before frames, frames fading in over each other with "Step k of n", the result fading in over them, a progress line (green when done), and the footer. Mods bring theirs in their own `ui/chat.js` (plan 44.1).

- **Steps:** `registerStep(toolName, { running, done, icon, detail(args, ctx), sentence(args, ctx), lookup })` (`chat-steps.js`, re-exported by `chat.js`) gives a tool its words in the fold. Without one, the words come from the tool's name ("vllm_engine_status" → "Checking engine status" / "Checked engine status") and its schema's property titles; values show by the schema's labels (`x-enum-labels` or `oneOf` titles) and `output:<id>` values as `#n` chips. Any catalog tool whose risk is `read` is a lookup. `registerCard('step:<tool>', ({ row, item, ctx }) => …)` replaces one tool's opened step.
- **Cards** are looked up as `<kind>:<tool name>`, then `<kind>`, then the generic card, and each renders in an error boundary: an unknown or broken card never breaks the thread. Props: `{item, ctx}`; `ctx` carries `api`, `outputs` (this chat's `#n` outputs), `tools` (the catalog), `answer(qid, answers)`, `decide(approval, approve, args)`, `cancel()`, `runAction(action, output)`, `openOutput(id)`, `running`.
- **Actions** have `on` (an output kind or `composer`) and one of `tool` (opens a parameter card prefilled by `args(output)`, then `POST /v1/threads/{id}/action`: no model call), `prompt(output)` (sends a message), `attach` (adds the output to the composer) or `run(output, ctx)`. An action whose `tool` (or `needs`) isn't in the catalog is hidden. **Actions are also derived:** any catalog tool (not the hub's, not destructive) with a file input whose `x-kind` fits the output's kind becomes a button with no UI code (live: Clone voice on audio; in the mock also Upscale image), deduplicated against the registered ones.
- **Built-in actions:** image → Animate, Edit, Remove background (tools), Describe (a prompt); Make 3D opens `gen3d_make_3d` with the picture (plan 20.7: the card offers only the engines that take one), Use as reference (attach); video → Describe; model3d → Rig; composer → Image, Video, 3D, Speech, Edit image.


**Learning in Chat (plan 21.7).**
- **The badge:** a parameter card's fields that the hub filled from a preference (`filled_by` = `pref:<id>` or `carried`) show as "From your preferences: …" above the form, in purple with the bulb. Capability defaults show as "Chosen for these inputs: …".
- **Thumbs:** up and down on each output (next to Open in Outputs) and in the reply bar under each finished reply. They call `POST /v1/threads/{tid}/feedback` (`Thumbs` in `chat-cards.js`).
- **The per-chat switch:** the header's bulb (Learning or Not learning) sets the thread's `settings.no_learn`.
- **Proposals:** the miner's `proposal` events are cards with **Use it** and **Not now** (`POST /v1/prefs/{id}/approve|reject`); `feedback` events draw nothing.
- **Settings → Agent** gains a **Learning** section: the hub's `[learning]` switch, thresholds and nightly time, and a link to the Learning page.
- **The Learning page** is the agent mod's own `ui/page.js` at `#/s/agent/learning` (Memory, Review, Preferences, Tool usage, …; Review right after Memory since memory-auto-learning 4.2), reached from the sidebar's **Memory** item at `#/s/agent/memory` (PATCHES #22, #71); the Memory tab's "N to review →" links to Review. Its **Review** tab's memories (plan memory-auto-learning 2.3) are two lists: **Learned on its own** (what the learner saved in the last 14 days and you haven't kept: the fact, its entries, the date, the words you said, Keep, Not this, Keep all) and **Needs your look** (proposals grouped by chat, each with why it waits: "sensitive: health", "not sure: 0.55", "not in your words", "would change something you said", "auto-approval is off"). The Memory tab marks each fact "learned <date>" or "you said <date>", and an entry with past facts has a **Timeline** (its current and past facts, newest first, each with its span, "since 2026-11" or "2026-09 – 2026-11", and a link to the chat it came from; 3.3). Under a chat's last turn, "Remembered: <fact> · +N · K to review · Review" says what the learner took from that chat (PATCHES #70). The Memory tab's **Import…** (plan memory-import 2.1, `ui/memimport.js`) opens a card in three steps: *Ask your other assistant* (the export prompt with Copy, and where ChatGPT and Claude show their memories), *Paste its answer* (a box and From: ChatGPT, Claude, Gemini, Other; Read it), and *What it found*: a progress line while the agent's model reads it (about a minute per 20 entries; the page may be left), then the entries by section (Instructions, Identity, Career, Projects, Preferences), each with its date and words, the facts it becomes (kind, what they're about, "already known", "replaces: …", "waits: sensitive: money") and Save / Review / Skip per fact (All: per section), the counts, and one button ("Save 133, send 4 to Review"). After saving: "Imported N · M wait in Review", Review →, Undo import (confirmed), Import more. **Imports (N)** under the entry lists each import with its state and Undo; Review groups imported proposals as "From your Claude import" with the entry they came from, and the Memory tab marks those facts "imported from Claude <date>". Step 2 also takes Claude's export file (the zip or its memories.json; 3.1). **Export** beside Import… shows the memory in the same format with Copy and Download .md (3.2). Screenshots in `docs/reference/memory-import-2026-11/`.
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

### 11.15 Calendar (plan calendar)

- **Where:** the `calendar` mod's page as a main view (`[ui] main`): **Calendar** in the sidebar after Chat (its badge: unread reminders), `#/calendar` full height; `#/calendar?item=<occurrence id>` opens one (a reminder's Open). The mod's own tab (`#/s/calendar`) holds **Calendar settings**.
- **Header**, two even rows: Today, ‹ ›, the range's title (*Friday, November 13, 2026* · *Nov 9 – 15, 2026* · *November 2026*), Day · Week · Month · Agenda, **New**, the menu (Plan my day, Import an .ics file…, Export everything as .ics, Trash, Settings); then **quick add** (plain words, a preview of what it read and assumed under it, Enter adds, Undo in the snackbar) and Search (results as an agenda; a click goes to that day).
- **Left column** (248 px; a drawer when the page is under 880 px): a mini month (the shown range shaded, today in the accent), **Calendars** (colour, show/hide, the default, +), **Layers** (Scheduled tasks, History, when the agent mod is there), **To-dos** (open ones, overdue in red, a tick completes), **Reminders** (fired alerts, unread first, with Seen, **Snooze ▾** and Done; the menu: 5, 10, 30 min, 1 h, 3 h, Tomorrow at the all-day time, or a typed amount with a unit, up to 30 days; a snoozed one reads *Snoozed until …*).
- **Day and week:** hour rows of 48 px with working hours shaded and weekends a shade quieter, the all-day row (up to three rows, then "+N more"), events side by side in even columns with the calendar's colour on the left edge (focus blocks hatched, free ones dashed, ↻ for a repeat), timed to-dos as round chips, the now-line in the accent; it opens at 07:00 or an hour and a half before now. Drag on empty space to create (15-minute steps), an event to move it (across days), its bottom edge to resize; a repeating one asks **This one / This and the following ones / All of them**.
- **Month:** weeks from the setting's first day; all-day and multi-day items as bars across days, up to three items a day then "+N more" (opens the day); a day's number opens it; a click on empty space starts an all-day item. **Agenda:** 30 days by day (Today, Tomorrow, then *Wed Nov 11*), empty days left out, **Load more**.
- **A click** on an item: a popover (when, the repeat in words, the place, notes, the calendar, *made by the agent*, Edit, Done for a to-do, Delete). **The sheet** (Event · To-do): title, the time (date and time pickers, All day / No time, or typed words), the repeat picker (Doesn't repeat, Daily, Every weekday, Weekly on days, Monthly on day N, Monthly on the last day, Yearly, Custom with interval; ends Never, On a date, After N times; the rule in words), alerts (in the app: up to eight chips, + Alert with presets and *Custom…*, a number and minutes, hours, days or weeks before; an all-day item's in whole days, at the all-day time), calendar, Shows as (Busy, Free, Focus block) or Priority, Place or *Takes (minutes)*, Project, Link, Notes. Every write shows a snackbar with **Undo**; a delete says *moved to the trash, kept 30 days*.
- **Files:** an `.ics` dropped on the page or chosen opens the import sheet: every item ticked except those already here, what was skipped, the calendar, **Add N**. The same list draws a day plan and the agent's proposals.
- It follows the mod's `rev` every 10 s (and its notifications), keeping the scroll and what's typed. Keys: `t`, `d` `w` `m` `a`, `j` `k`, `n`, `/`, Esc.
- **A project's page** has a **Dates** panel (after Scheduled) when the calendar mod answers: the project's items in the next 14 days (colour, title, *Thu 10 Nov · 13:00* or *due Fri 20 Nov*), each opening it in the Calendar, and **New** (the Calendar's sheet with the project chosen, `#/calendar?new=<project>`).
- **Scheduled tasks' schedules** (calendar 6.1–6.2): the editor's picker gains **Once** (a date and time; it runs once, then turns off). A task made by the Calendar's **Prep task** shows **Before an event** and its words (*30 min before “Design review”, each time*), changed only from the Calendar. `#/chat/tasks?new=once&at=<time>` opens a new task at that time (the Calendar's *Schedule a task here*).
- **The Calendar and scheduled tasks** (calendar 6.3–6.4): the event sheet has **Prep task** (*Have the agent prepare before it*: what to do, how long before; saving makes a task *Prep: <title>* before each occurrence, in Auto; then the sheet shows *Runs 30 min before, each time* and **Open its task**), a prep mark ◷ on the event, and deleting an event asks whether to delete its prep task too. A new event's sheet also offers **Or schedule a task at this time**. The **Scheduled tasks** layer (on by default) draws each task's next times as dotted marks (◷ name) and its runs as chips coloured by how they went (green done, red failed, grey skipped; ● unread); a click opens the task or the run's chat.
- **Side panels in Chat** (calendar 7.1–7.2, `chat-panel.js`): a mod with `[ui] chat_panel` puts an icon on a slim rail at the Chat page's right edge; it opens a column (260–440 px, a divider to drag; a drawer from the right on a narrow page) beside the chats, one at a time, kept on the hub as `hub.chat.panel`. The Calendar's: Day · Week, ‹ Today ›, the date folding a mini month; Day as an hour column of 36 px rows from the first item or 08:00 with the now-line, Week as seven days of items; then to-dos due and overdue (a tick completes one) and unread reminders (Seen, Snooze ▾, Done for a to-do); **Open the Calendar**. A click opens the item's popover, whose **Mention** puts *“Design review” (calendar item c_…, Tue Nov 10 13:00)* into the composer you last used.
- **The History layer** (calendar 8.2, off by default): your chats each day as muted blocks from their first to their last message (at least 15 minutes; ◷ for a task's run) and outputs as ▣ marks at their time; a click opens the chat or the output.

