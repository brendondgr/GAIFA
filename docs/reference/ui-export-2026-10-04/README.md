# Claude Design export — Part A v1 (2026-10-04)

This is a reference copy of the first UI that Claude Design built from [design-brief-ui.md](../../design-brief-ui.md). It is the **baseline** for later work. The plan copies it into `web/` in step 1.8 of [backend-plan.md](../../backend-plan.md), and Part A revision 2 (brief §11) builds on it.

To view it, serve this folder over HTTP and open `Hub.dc.html`:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/reference/ui-export-2026-10-04
```

Opening it with `file://` doesn't work, because the runtime `fetch`es its components. Press `Shift+D` to open the mock scenario panel.

| File | What it is |
|---|---|
| `Hub.dc.html` | The whole shell and every core page: the template plus one `class Component extends DCLogic` |
| `OutputCard.dc.html`, `JsonView.dc.html` | Shared components, loaded with `<dc-import name="…">` from `./<Name>.dc.html` |
| `mock.js` | `createMockApi()`, which implements the brief's Section 6 contract |
| `support.js` | Claude Design's runtime. It is generated, so don't edit it. It renders the templates with React 18. |
| `thumbnail.webp` | A preview image |

How it differs from what the brief asked for. The plan already accounts for all of this:
- **React is loaded from unpkg at runtime.** `support.js` skips that download if `window.React` and `window.ReactDOM` already exist, so GAIFA serves local copies from `web/vendor/`. Babel is only needed for `.jsx`/`.tsx` imports, and this UI has none.
- **The page always runs on the mock** (`import('mock.js')` → `createMockApi()`). There's no `?live` switch yet. Step 1.9 adds the switch between mock and live data, area by area, and revision 2 builds it in.
- **It still says "Hub" and `bin/hub`**, so it needs renaming to GAIFA and `gaifa`.
- **The density setting defaults to "comfortable".** Revision 2 makes the UI compact by default and adds charts and multiple Overview views.
