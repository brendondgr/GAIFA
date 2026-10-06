# lcpp web UI

Static, no build step. Serve `web/` from any static server (or the lcpp daemon) and open `index.html`.

```
web/
├── index.html            page shell: sidebar, header, view root, toasts, drawer
├── tokens.json           design tokens (source of truth; assets/tokens.css is generated from it)
└── assets/
    ├── tokens.css        CSS custom properties: dark (default) and light themes
    ├── components.css    component styles (buttons, badges, cards, dialogs, tables…)
    ├── app.css           layout: sidebar, header, views, drawer, responsive rules
    ├── components.js     window.Lcpp — vanilla DOM factories for every component
    ├── utils.js          formatting helpers (bytes, durations, argv → command)
    ├── api.js            ApiError + createHttpApi(base) — the live HTTP client
    ├── mock.js           createMockApi() — in-memory daemon with simulated time
    └── app.js            store, poller, hash router, dialogs, and the five views
```

Mode: served by lcppd (`http://127.0.0.1:7710/`) the UI talks to the live daemon, because the daemon's `/config.js` sets `window.LCPP_API_BASE`. Served by any other static server it runs against the built-in mock (`?live` forces live mode).
In mock mode press `Shift+D` for the scenario panel (Relay reachable, daemon down, seed/empty/busy, speed).

Because `app.js` is an ES module, open the page over http(s), not `file://`.
