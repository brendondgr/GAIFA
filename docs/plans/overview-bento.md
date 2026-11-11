# Plan: the Overview as a bento grid: what needs you on top, tiles of fixed sizes, no holes

**Asked for:** 2026-11-10 · **Status:** Done (2026-11-10)

## 1. Introduction

The Overview's Dashboard view (`web/dashboard.js`, brief §11.4–11.5, built in backend-plan 6.5) is a KPI strip and 20 cards in a 12-column grid that packs by span only. Each card is as tall as its content, so rows are ragged and leave holes. The page runs about 2,600 px at 1440 × 900. The top of the page goes to a list of every service (most at "0.1 GB") and a donut whose legend repeats it. What needs you (approvals, memories to review, a failed service) is in the header or an alert strip, and what you'd look for first (what's running, your day, your chats) isn't on the page at all.

This plan rebuilds the Dashboard as a **bento grid**. It keeps 12 columns but adds **fixed row heights**, and every tile is one of six **sizes** (columns × rows), so tiles fill their boxes and the grid has no gaps. The default layout goes by relevance: **Needs you**, **Running now** and **Memory** on top, a row of small number tiles, then **Services**, **Today** (the calendar and scheduled tasks) and **Recent chats**, then the wide history tiles (memory over time, recent outputs, LLM traffic, uptime). Everything else stays available but is off by default. Customize works on the grid itself: drag a tile to move it, pick a size from its ⋯ menu, and show or hide tiles in a panel. The Services view goes, because the Services tile replaces it. Table and Timeline stay.

Touches the brief §11.3–11.5 and §11.11 (the Dashboard as built), `[ui.dashboard]`/`[ui.overview]` in `config.toml` (architecture §9, settings-that-stick 3.1), and reads the agent mod's threads and tasks (architecture §14) and the calendar mod's agenda ([calendar](calendar.md)) through the hub's proxy, as the header already does for memories to review.

## 2. Gaps & unanswered questions

- **New tiles from mods** (answered 2026-11-10): yes. Needs you, Today and Recent chats. Each one hides itself when the mods it reads aren't installed or running.
- **Customizing** (answered 2026-11-10): drag tiles on the grid to reorder them, choose each tile's size from presets, and show or hide tiles in a panel.
- **Other views** (answered 2026-11-10): keep Table and Timeline, drop the Services view. *Assumption:* a saved `view = "services"` reads as `dashboard`, and `config.toml` still accepts it, so an old file loads.
- **Sizes.** *Assumption:* six presets. `xs` 3 × 1 (a number), `s` 4 × 2, `m` 4 × 3 (a list), `w` 6 × 3 (half width), `l` 8 × 3 (a wide chart) and `f` 12 × 2 (a strip). Each tile lists the sizes it allows, so a chart is never 3 × 1. The row unit is 60 px in compact and 68 px in comfortable, with gaps of 10 and 14 px. Content that doesn't fit scrolls inside its tile. It never stretches the row.
- **Narrow widths.** *Assumption:* under 1100 px, `xs` keeps 3 columns (four to a row), `s`, `m` and `w` take 6, and `l` and `f` take 12. Under 760 px everything takes the full width except `xs`, which takes half, and row heights stay the same.
- **Packing.** CSS grid with `grid-auto-flow: row dense` and fixed rows. Dense packing may pull a later small tile up into a gap. That keeps the grid hole-free and is acceptable, since Customize shows the order.
- **The alert strip.** *Assumption:* in the Dashboard view, alerts are rows in Needs you, not a strip above the grid. Table and Timeline keep the strip.
- **Which tiles are on by default.** *Assumption:* the twelve above (with LLM traffic only while relay declares it). Off by default: Memory now (the donut; the Memory tile replaces it), GPU queue, GPU memory, Outputs per day, Outputs by service, Activity heatmap, Jobs, Model storage, the Jobs-running and Models-loaded numbers, and every other mod widget. Mod widgets were on before. They're off now because four of them filled the bottom of the page.
- **Saved layouts.** This machine's `config.toml` has no `[ui.dashboard]`. *Assumption:* the saved shape gains `sizes` (key → size) and `shown` (tiles that are off by default but turned on). `hidden` keeps meaning "turned off", and old keys that no longer exist are dropped as before.
- **Data for the new tiles.** Approvals (`listApprovals`) and memories to review (`memReview`) are already in the shell's state. Running chats arrive as jobs from the agent's status. Recent chats come from `GET /api/s/agent/v1/threads?limit=6`. Today comes from `GET /api/s/calendar/v1/agenda?day=today` and the agent's `GET /v1/tasks` (`next_due` today). *Assumption:* polled every 60 s while visible and refetched on the shell's events for those mods (`useData`'s existing rules: nothing while the tab is hidden).

## Phase 1 — The bento grid (M)

- [x] **1.1 Sizes, spans and the saved layout: `web/bento.js` (new).**
  - **Pure:** `SIZES = {xs:[3,1], s:[4,2], m:[4,3], w:[6,3], l:[8,3], f:[12,2]}`; `spanAt(size, width)` → `[cols, rows]` with the narrow rules above; `sizeOf(def, layout)` (the saved size if the tile allows it, else its default); `visibleKeys(defs, layout)` (the saved order first, then defaults; `def.off` tiles only when in `shown`, others unless in `hidden`); `dropBefore(order, key, beforeKey)` for a drag; `toggle(layout, key, on, def)`.
  - **Drawing:** `BentoGrid({tiles, width, compact, editing, onDrop})` lays out the grid (fixed `gridAutoRows`, dense flow), and `Tile({title, icon, count, tone, ranges, range, onRange, href, menu, sizes, size, onSize, onHide, mock, editing, children})` is the frame: a one-line header (icon, title, count badge, range chips, ⋯), a body with `flex: 1; min-height: 0; overflow: auto`, and a `ResizeObserver` that hands the body's height to children through `useTileSize()` so charts fill the tile. In editing mode tiles are `draggable`, show a grip and a dashed outline, and dropping one on another calls `onDrop(key, beforeKey)`. Keyboard: with a tile's grip focused, ←/→ move it one place.
  *Done when:* `utils/tests/web/bento.test.mjs` (new) covers every size at 1440, 1000 and 400 px, `sizeOf` refusing a size a tile doesn't allow, `visibleKeys` with `hidden`, `shown`, unknown keys and an `off` tile, and `dropBefore` (to the front, to the end, onto itself).
  *As built:* `stepKey(order, visible, key, dir)` is the keyboard's move (one place among the visible tiles); `isOn` and `setOn` read and write `hidden`/`shown`. Rows are 60 px compact and 68 px comfortable (56 was too short for three list rows). The tile body's scrollbar is thin.
- [x] **1.2 The saved layout in `config.toml`: `utils/config.py` (`DashboardCfg`), `utils/api_models.py` (`DashboardLayout`), `config.example.toml`.**
  - `sizes: dict[str, Literal["xs","s","m","w","l","f"]] = {}` and `shown: list[str] = []`. The `[ui.dashboard]` comment in `config.example.toml` names them. `[ui.overview] view` still accepts `services`.
  *Done when:* `utils/tests/settings/test_settings.py` (or `test_settings_ui_prefs.py`) saves and reads back `sizes` and `shown`, refuses an unknown size with 422, and loads an old `view = "services"`. Update architecture §9's `[ui.dashboard]` line.
  *As built:* `TILE_SIZE` in `utils/config.py`; the settings test also checks that a size the grid doesn't have is refused (422). `[ui.overview] view` keeps accepting `services` unchanged.

**Wire — Phase 1:** nothing visible yet.

**Checks & deliverables — Phase 1**
- [x] `uv run pytest` is green.
- [x] Delivered: `web/bento.js`, the changed config models, and tests.

## Phase 2 — The tiles (L)

- [x] **2.1 Tiles for what's happening now: `web/overview-tiles.js` (new).**
  - **Needs you** (`needs`, `s`/`m`/`w`): one row per thing, worst first. Alerts (error, then warning, with their action), failed services (→ logs), approvals waiting (count and the first tool's name, → opens the header's Approvals popover), memories to review (→ `#/s/agent/memory`). With none: "All clear" and a green check, and the tile shrinks to its body. Pure `needsRows({alerts, services, approvals, memReview})`.
  - **Running now** (`running`, `s`/`m`/`w`): running and queued jobs (the live thumbnail, label, progress, `jobStatusText`), the GPU slot's holder from the GPU state when one waits, and models in memory (services with `load = loaded`, with their memory). "Nothing running" when empty.
  - **Memory** (`memory-hero`, `s`/`w`): the used figure large (`25.3 / 130 GB`), a bar split into the three largest users, the rest and free with the reserve marked, a 1 h sparkline, and the pools when there are dedicated cards (`PoolBars`). Pure `memorySplit(memory, services, n = 3)`.
  - **Numbers** (`xs`): `stat-services` (ready x/y, red with failures), `stat-outputs` (today vs yesterday), `stat-tokens` (the first "Tokens today" stat), `stat-task` (the next scheduled task's time and name; hidden without the agent mod), and off by default `stat-jobs` and `stat-models`. These replace the KPI strip.
  *Done when:* `utils/tests/web/overview-tiles.test.mjs` (new) covers `needsRows` (order, each kind, empty), `memorySplit` (top 3 plus the rest, free never negative, one pool) and each number tile's text from fixtures.
  *As built:* `jobStatusText` moved here (dashboard.js re-exports it). Also `runningRows`. Memory keeps its legend to one line and shows free and the share in the header; the sparkline shows only when the tile is tall enough (`w`). List rows are 26 px, so three fit in an `s` tile.
- [x] **2.2 Tiles from the agent and the calendar: `web/overview-tiles.js` (or `web/overview-mods.js` if past ~450 lines).**
  - **Services** (`services`, `m`/`w`): failed and degraded first, then services holding memory (largest first), then the rest folded into one "+ N idle" row that opens in place. Each row: state dot, name, load, memory and a 24 h sparkline. Pure `serviceRows(services, {open})`.
  - **Today** (`today`, `m`/`w`/`l`): today's calendar items (time, title, a dot in the calendar's colour; all-day first), overdue to-dos, and scheduled task runs due today, merged by time with a "now" line. Rows open `#/calendar` or the task's page. Shown when the calendar or agent mod is running. Pure `todayRows({agenda, tasks, now})`.
  - **Recent chats** (`chats`, `m`/`w`): the six newest threads, with the running, waiting and error dot, the title and the age; a row opens `#/chat/<id>`; the header links to `#/chat/all`. Shown when the agent mod is running.
  *Done when:* `overview-tiles.test.mjs` covers `serviceRows` (order, folding, failed first) and `todayRows` (merge order, all-day, overdue, a task already run today drops out, an empty day). The mock (`web/mock.js`, `mock-mods.js`) answers `agent /v1/threads`, `/v1/tasks` and `calendar /v1/agenda` so `?mock` shows every tile.
  *As built:* Today and Recent chats are `web/overview-day.js`; the next scheduled task tile (`NextTaskNum`, `nextTask`) is there too. Services draws the idle mods as pills (a fold left the tile half empty). Recent chats shows as many rows as fit. The mock's agent and calendar are `web/mock-overview.js`.
- [x] **2.3 The Dashboard on the bento grid: `web/dashboard.js`.**
  - `widgetDefs` gains each tile's `sizes`, `size` (default), `icon`, `off` and `needs` (mods that must be running). The existing chart widgets move into `Tile` and take their height from `useTileSize()`. Default order and sizes: needs s, running s, memory-hero s; four numbers xs; services m, today m, chats m; memory (over time) l, activity m; recent f; llm w, uptime w; then the off tiles.
  - `Dashboard` draws `BentoGrid`. **Customize** turns on editing mode (drag, grips) and opens a slim panel listing every tile with a switch and a size picker, plus Reset. The ⋯ menu of every tile has Size ▸, View as table (charts), Open page and Hide. Changes save through `onLayout` as today.
  - Split `dashboard.js` if it passes ~450 lines (the chart widgets to `web/overview-charts.js`).
  *Done when:* `utils/tests/web/dashboard-jobs.test.mjs` still passes and a new `dashboard-layout.test.mjs` covers `widgetDefs` (relay's traffic only when declared, a mod widget `off`, `needs` hiding a tile when its mod isn't running). In the browser at 1440 × 900 on a second hub (`?mock`): no gaps between tiles, Needs you, Running now, Memory, the numbers and the top of Services, Today and Recent chats above the fold, a drag moving a tile, a size change and Hide saving and surviving a reload.
  *As built:* `widgetDefs(widgets, services)` drops a tile whose `needs` mods aren't running (all kept before the service list loads); a tile's `count(ctx)` gives the header badge. Time charts take `fit` (`charts.js` XYChart, with `useHeight` in `chart-kit.js` measuring the legend). The Customize panel has three columns on wide screens. Tests for the tile list are in `charts.test.mjs` (where the dashboard's were). Checked at 1440 × 900, 1000 and 375 px wide, dark and light, on the installed hub and `?mock`: no gaps, the page 1,128 px tall (was 2,600), drag, the grip's arrow keys, a size from ⋯ and Hide.

**Wire — Phase 2:** the Overview's Dashboard is the bento grid, live on the installed hub with the agent and calendar mods.

**Checks & deliverables — Phase 2**
- [x] On the installed hub at 1440 × 900 and 400 px wide, in light and dark: every default tile draws, no holes, approvals and a failed mod show in Needs you.
- [x] Delivered: `web/overview-tiles.js`, the changed `dashboard.js`, the mock's new routes, and tests.

## Phase 3 — Views, the shell and docs (S)

- [x] **3.1 Drop the Services view; alerts in Needs you: `web/Hub.dc.html`, `web/ui-prefs.js`.**
  - The view switcher shows Dashboard, Table and Timeline. A saved or linked `services` view opens Dashboard. The tile template, the memory panel and the activity and recent sections that only the Services view used are removed from the template and from `vmOverview`. The alert strip is drawn only for Table and Timeline.
  *Done when:* `utils/tests/web/ui-prefs.test.mjs` covers `services` reading as `dashboard`; the web tests and `uv run pytest` are green; in the browser, `#/overview?view=services` opens the Dashboard.
  *As built:* `tileVM`, the `.hubtile` CSS and the `tileMenu` state went with the view. The Settings → General → Reset the dashboard layout row counts and resets `shown` and `sizes` too.
- [x] **3.2 Docs: the brief §11.4, §11.5 and §11.11 (an "As built (overview-bento)" block: sizes, defaults, Customize), §4.1's pointer, `web/PATCHES.md`, `docs/structure.md` (the new files), `docs/plans/README.md` (status).**
  *Done when:* the docs tests pass and the plan's status is Done.

**Checks & deliverables — Phase 3**
- [x] `uv run pytest` is green, and the installed hub's Overview shows the bento layout after `gaifa restart`.
- [x] Delivered: the changed shell, docs and tests.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Bento grid | sizes, spans, saved layout helpers, `BentoGrid`, `Tile`, drag to reorder | `web/bento.js` |
| Tiles | Needs you, Running now, Memory, the numbers, Services, Today, Recent chats | `web/overview-tiles.js` |
| Dashboard | the tile list, defaults, Customize on the grid | `web/dashboard.js` |
| Config | `[ui.dashboard] sizes`, `shown` | `utils/config.py`, `utils/api_models.py`, `config.example.toml` |
| Shell | no Services view, alerts in Needs you | `web/Hub.dc.html` |
| Tests | grid maths, tile rows, layout, settings round trip | `utils/tests/web/bento.test.mjs`, `overview-tiles.test.mjs`, `dashboard-layout.test.mjs`, `utils/tests/settings/` |
