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

## Known export behavior (not edits)

- The browser parses the raw template before `support.js` renders it, so the console shows `<path> attribute d: Expected moveto…"{{ ic.x }}"` errors and one request for `/{{ sv.api.r.url }}` (a 404 on 127.0.0.1). They're harmless and come from the export format; revision 2 can avoid them (e.g. `<template>`-wrapped markup).
