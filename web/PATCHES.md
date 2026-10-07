# The UI's history, and edits since revision 2

`web/` began as Claude Design's Part A v1 export (`Hub.dc.html`, `OutputCard.dc.html`, `JsonView.dc.html`, `mock.js`, `support.js`), copied from [docs/reference/ui-export-2026-10-04/](../docs/reference/ui-export-2026-10-04/README.md) in plan step 1.8.

**Revision 2 was built by hand (plan step 6.5, 2026-10-05).** Brief §11 was done in this repo instead of in another Claude Design pass, so `web/` is now AIHub's own code. A later Claude Design pass (the Part B pages, or a future revision) starts from the current `web/` folder plus this file. The "Edits since revision 2" table starts empty. Any hand edit to `Hub.dc.html`, `OutputCard.dc.html`, `JsonView.dc.html` or `mock.js` goes there, so a future export can be checked against the list.

**Never edit `support.js`.** It's Claude Design's generated runtime.

**Not edits (done by the hub as it serves the page, in `utils/routes/web.py`):**
- `/vendor/react*.js` and `/config.js` `<script>` tags are added before `support.js` on `GET /`.
- The Google Fonts `<link>`s become `/vendor/fonts.css` in every `.dc.html`.
- A page load (`Sec-Fetch-Mode: navigate`) gets `Hub.dc.html` with an empty `<x-dc>`. `support.js` renders from its own `fetch` of the same URL, which gets the full template. The browser never parses the raw template, so the `{{ … }}` in `src`, `poster` and SVG `d` attributes no longer cause `/{{ … }}` 404s or `<path> attribute d` errors (brief §11.2).

## Edits since revision 2

| # | File(s) | Edit | Why | Step |
|---|---|---|---|---|
| 1 | `Hub.dc.html` | `pageUrl`: in `?mock`, `tts`, `gen3d`, `relay`, `lcpp` and `comfy` (11.11) load their own `services/<id>/ui/page.js` instead of the template's | The Part B pages are page modules in the mods' folders, and mock.js answers their native API | 7.7 |
| 2 | `mock.js` | The `tts` mock answers LocalTTS's real API shapes (`/v1/voices` → `{custom, kokoro}`, design/PATCH/clone, `timings`, enhance, the clips widget); `tts` has a page; the API-tab operations match | So the Speech page works in `?mock` | 7.7 |
| 3 | `mock.js` | The mods' native handlers (tts, gen3d, lcpp, relay, comfy, transcribe) moved to `mock-mods.js` (`createModMocks(M)`; `M` hands over mock.js's state and helpers); gen3d's mock answers 3DGenerate's real API (options, estimate, jobs with stages, `/v1/events`, files as box GLBs) | mock.js was near the 800-line limit, and the 3D page needs gen3d's real shapes | 8.7 |
| 4 | `mock.js`, `mock-mods.js` | `relay` and `gen3d` have pages on the mock; the relay mock answers DashLLM's real admin API (stats datasets, endpoints, router, tunnels, proxy, status, the traffic widget) | So the Relay and 3D pages work in `?mock` | 9.7 |
| 5 | `mock.js`, `mock-mods.js` | `lcpp` has a page on the mock, and its mock answers lcppd's real API | So the Launcher page works in `?mock` | 10.7 |
| 6 | `Hub.dc.html`, `api.js`, `mock.js` | Settings → About gets a **Doctor** panel (`getDoctor()` → `GET /api/doctor`, area `system`): a summary chip, the warn/fail/note checks with fixes, "Show all", "Run again"; `aihub doctor` joins the CLI list; the mock builds a report from its mods | Plan 12.4's Wire item | 12.4 |
| 7 | `Hub.dc.html` | **Chat** (plan 14.1, Wire — Phase 14): the nav item is enabled (in `sb.top`, the disabled "LATER" item removed) and in the palette; `#/chat` and `#/chat/<id>` mount `chat/chat.js`'s `ChatPage` (`{{ chatEl }}`) in a full-height `<main>` (`mainSt` for the chat page: fixed height, no padding, no page scroll); its output buttons open the Outputs drawer over the chat (`loadOutputDetail`) | The Chat page is a module in `web/chat/`, like the dashboard | 14.1 |
| 8 | `Hub.dc.html` | Header **Approvals** button (shield, purple count badge) and popover (`pop.ap`, `{{ pap }}` = `chat/chat-approvals.js`'s `ApprovalsPanel`: pending approvals as parameter cards, Approve / Deny); `loadApprovals()` at boot and on `approval` / `resync` events | Wire — Phase 13 | 14.1 |
| 9 | `Hub.dc.html` | API tab: the purple tool badge shows the risk (`tool · generate`), from `getToolIndex()` (loaded once, matched as `<mod>_<tool>`); the operation header names the tool and says when it asks first | Wire — Phase 13 | 14.1 |
| 10 | `Hub.dc.html` | Settings gets an **Agent** section (`se.sec.agent`, `{{ se.agentEl }}` = `chat/chat-settings.js`'s `AgentSettings`: AGENT.md, memory, models, skills, permissions, Show thinking) | Wire — Phase 14 | 14.1 |
| 11 | `mock.js`, `mock-tools.js` | The `tools` area on the mock: `listTools`, `getToolIndex`, `callTool`, `getToolCall`, `cancelToolCall`, `listApprovals`, `getApproval`, `decideApproval` (`createToolMocks` mixed into the api; one pending approval from "Claude Code (MCP)") | So the chat, the Approvals popover and the API tab's risk badges work in `?mock` | 14.1 |
| 12 | `Hub.dc.html`, `api.js`, `mock.js`, `mock-sessions.js` | **Sessions** (Wire 15): `sessions.js` mounted as a dialog (`dlg.sessions`, `{{ sessEl }}`; opened from the Chat page's thread list, the palette's "Save session…", "Switch to session…" and "Switch to <name>") and as **Settings → Sessions** (`se.sessionsEl`); the "Restore last session?" prompt after an unclean shutdown (`{{ restoreEl }}`); `loadSessions()` at boot and on `session` events; api.js gets the `sessions` area; the mock's sessions in `mock-sessions.js` | Plan 15, brief §11.14 | 15 |
| 13 | `Hub.dc.html`, `mock.js` | Settings → Paths lists `data/logs` and `data/state` with their sizes (`System.paths/usage` gained `logs`, `state`) | Wire 16 | 16 |
| 14 | `Hub.dc.html`, `mock.js`, `mock-tools.js` | API tab: an operation that is an agent tool with risk other than read is sent as a tool call (`api-tool.js` `ToolRun`: `callTool(<mod>_<tool>, args, {mode: 'ask'})`, the parameter card inline, `decideApproval`, progress, outputs as links); a file upload still goes direct. The mock's `tts_speak` tool takes the same inputs as its `POST /v1/speech` operation (whose voice default is now `Hope`, one of its enum values); finished mock tool calls return an output | Wire 13 | 14.1 |
| 15 | `Hub.dc.html` | `componentDidUpdate` no longer reads `prevState` (support.js passes only `prevProps`, so opening the palette threw on every update and its input wasn't focused) | Bug fix | 14.1 |

## Revision 2 (step 6.5): what changed

**New files (ours, plain ES modules on the page's React; no chart library, nothing from a CDN):**

| File | What it is |
|---|---|
| `chart-kit.js` | Formatting, scales, null-safe paths and stacks, the size hook, and the frame every chart shares: loading/empty/error, legend toggles, tooltip, "View as table" |
| `charts.js` | `AreaChart`, `LineChart`, `BarChart` (time or category axis, stacked, 2 y-axes, drag-to-select), `HBarChart`, `Donut`, `Sparkline`, `Heatmap`, `Treemap`, `Timeline`, `KpiTile` |
| `views.js` | The widget `Card`, the `useData` hook (it never polls while the tab is hidden), the Overview Table and Timeline views, `MemoryChart`, `StorageChart`, `OutputsHistogram`, `ServiceCharts` |
| `dashboard.js` | The Dashboard view: the KPI strip, 13 built-in widgets plus one per mod widget, and Customize |
| `mock-history.js` | 7 days of seeded mock history for the chart methods, plus the "Empty history" and "Gaps" scenarios |

**`Hub.dc.html` (the template plus `class Component`):**
- **Edits 1–9 from v1 are kept.** They are the AIHub renames, the hybrid API switch, the real version, the Settings MOCK notes, page modules through `ModPage`, model events and verify progress, live outputs, and Make room from the API tab.
- **Compact by default.** The density comes from this browser's choice, or else from `Settings.ui.density` (default `compact`).
  - The shell is density-driven (`rootSt`, `hd.st`, `mainSt`, `h1St`): sidebar 208 px, header 44 px, base font 12.5 px, page padding 14–18 px, gaps 12 px.
- **Overview with four views** (`?view=dashboard|services|table|timeline`; the choice is also kept in `localStorage` as `hub.ovView`):
  - The Dashboard, Table and Timeline views are rendered by `dashboard.js` and `views.js` as React elements (`{{ ov.dash }}`, `{{ ov.table }}`, `{{ ov.timeline }}`).
  - The Services view is v1's tiles in the compact form. Each tile has a mono status line, up to 4 stats with 24 h sparklines, and a ⋯ menu. Its icon buttons appear on hover or focus and are always shown on touch screens. The v1 memory, activity and recent-output sections stay below the tiles.
- **Dashboard layout:** Customize and the range pickers save `Settings.ui.dashboard` through `saveSettings({ui: {dashboard}})` (`onLayout`, debounced), so the layout follows you between browsers.
- **Sparkline history:** `loadHist()` fetches 1 h and 24 h of `mem.svc.*`, `mem.used`, `jobs.running` and the mods' numeric stat series. It refreshes every 60 s while the tab is visible.
- **Graphics on other pages (§11.8):**
  - the service header's 1 h memory sparkline
  - a History card on the generic Overview tab: a chart per numeric stat, memory, and the mod's timeline lane
  - the memory popover's 1 h stacked area
  - the Models treemap and disk gauge, which replace the stacked bar; clicking a kind filters the table
  - the Outputs histogram: drag across days to set a date filter, shown as a chip you can clear. The Overview links `#/outputs?from=&to=` and `?range=` work too
  - the Settings → Memory 24 h chart, whose reserve line follows the unsaved value
- **The `Shift+D` panel** gains History: Normal, Empty history, Gaps (2 h down).

**`mock.js`:**
- Numeric stats carry `series`.
- `settings.ui` has `density: 'compact'` and `dashboard`.
- `saveSettings` merges a partial save the way the hub does.
- The chart methods come from `mock-history.js`.

## States only the mock can produce

These are the brief §8 and §11.10 states the live hub can't show on demand. Use `?mock` and `Shift+D` for them:
- **Many outputs (2,000):** the live index shows whatever `outputs/` holds.
- **Empty history:** live, only a fresh install or a new `data/databases/aihub.db` looks like this.
- **Memory pressure** ("Load … then try Load on 3D Generate", and the variant where the plan falls short): live, these need mods big enough to fill 121 GB.
- **"Install mod with no page"** (Transcribe): live, any mod without `ui/` looks like this.

Everything else can be reached live:
- **Gaps:** stop the hub for a while.
- **Hub down:** `aihub stop`.
- **A failed mod:** `fake-crash` with `--demo-mods`.
- **A widget error:** stop the mod that serves it.
- **A broken manifest:** a mod folder with a bad `service.toml`.
