# Edits to the Claude Design export

`web/` holds Claude Design's export (`Hub.dc.html`, `OutputCard.dc.html`, `JsonView.dc.html`, `mock.js`, `support.js`), copied from [docs/reference/ui-export-2026-10-04/](../docs/reference/ui-export-2026-10-04/README.md) in plan step 1.8. Every hand edit to those files is listed here, so a new export can be checked against the list. Revision 2 (plan Phase 6) asks Claude Design to build these in, and the list goes back to empty.

**Never edit `support.js`.** It's generated.

**Not edits (done by the hub as it serves the page, in `utils/routes/web.py`):**
- `/vendor/react*.js` and `/config.js` `<script>` tags are added before `support.js` on `GET /`.
- The Google Fonts `<link>`s become `/vendor/fonts.css` in every `.dc.html`.

## Edits

| # | File(s) | Edit | Why | Step |
|---|---|---|---|---|
| 1 | `Hub.dc.html`, `mock.js` | `Hub` → `AIHub` in visible text (`the Hub` → `AIHub`); identifiers such as `setHubDown` unchanged | The product is AIHub | 1.8 |
| 2 | `Hub.dc.html`, `mock.js` | `bin/hub` → `aihub` | The CLI is `aihub` (`bin/aihub`, linked into `~/.local/bin`) | 1.8 |
| 3 | `Hub.dc.html` (`componentDidMount`) | `import('mock.js')` → `createMockApi()` replaced by `createApi({base, liveAreas, mock})` from `api.js`; `?mock` forces all-mock | The hybrid mode switch (brief §6.1) | 1.9 |
| 4 | `Hub.dc.html` (sidebar footer, Settings → About) | Hard-coded `v0.1.0` → the hub's version from `getSystem()` (`sb.version`, `v.versions`) | Show the real version | 1.9 |
| 5 | `Hub.dc.html` (Settings) | A **MOCK** note above each Settings section whose data comes from a mocked area (`SETTINGS_AREAS`, `se.mock`, `se.mockText`) | Brief §6.1: sections show a MOCK badge while their area is mocked | 1.9 |
| 6 | `Hub.dc.html` (service page, `onEvent`, `componentDidMount`) | The hard-coded Example **Hello** tab (`CUSTOM_TABS`, `sayHello`, `sv.hello`) is gone. A mod with `has_page` gets its tabs from its page module (`loadPage` imports `page_url`, or `/ui/services/_template/page.js` in mock mode), rendered by the new `<dc-import name="ModPage">` host (`web/ModPage.dc.html`, ours) with `ctx` from brief §5 (`ctx.ui` = `web/mod-ui.js`, ours). Events also go to page modules (`modListeners`), and `resync` refetches the overview and the open service | Plan 2.9: mod pages come from the mods' own folders. `<dc-import>` takes only a literal `name`, and `<x-import>` only a literal `from`, so one static host loads every page module | 2.9 |
| 7 | `Hub.dc.html` (`onEvent`, `modelBlocked`, `vmModels`) | Handles the new `model_deleted` event and refetches totals when a model is added or deleted elsewhere; the status badge and the drawer's Verify button show `progress` ("verifying 42%"); `modelBlocked` matches the hub's in-use rule (a running mod that is loading, loaded, unloading or busy; `n/a` counts as loaded) | Plan Phase 3 wire: live registry events and verify progress (brief §6.4 `Model.progress`) | 3 |
| 8 | `Hub.dc.html` (`onEvent`, `vmOutputs` drawer, `cardVM`, `deleteOutput`) | The drawer plays live videos in a `<video>` (with the poster) instead of the mock placeholder, and offers Download for files the hub serves (`/api/…` URLs); an `output` event for an output already shown replaces its card instead of adding a second; live totals and filter-chip counts follow added and deleted outputs; text cards fall back to `meta.excerpt`; the delete dialog says the output moves to `outputs/.trash` (emptied after 30 days); the drawer's 3D and video boxes get `flex:none` (they collapsed to 0 px when the drawer's content overflowed, in the mock too); navigating to another page closes an open output drawer (`enterRoute`; it used to stay open over the Overview) | Plan Phase 4 wire: live outputs (a changed file is re-published; deletes go to the trash) | 4 wire |

## Known export behavior (not edits)

- The browser parses the raw template before `support.js` renders it, so the console shows `<path> attribute d: Expected moveto…"{{ ic.x }}"` errors and requests for `/{{ sv.api.r.url }}`, and since patch 8 `/{{ odr.url }}` and `/{{ odr.poster }}` (404s on 127.0.0.1, from `<video src>`/`poster` in the raw markup). They're harmless and come from the export format; revision 2 can avoid them (e.g. `<template>`-wrapped markup).
