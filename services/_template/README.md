# __NAME__

An AIHub mod, made with `aihub new __ID__`. The full guide is [docs/mods.md](../../docs/mods.md).

## The contract on one page

**Required:**
1. **This folder**, `services/__ID__/`, with a `service.toml` whose `id` is the folder name.
2. **An HTTP server on `127.0.0.1:$AIHUB_PORT`**, in any language (here: `server.py`, FastAPI).
3. **A health route**, `/health`, that answers 2xx once the mod is ready. Plain binaries can use `health = "tcp"` instead.

**Optional; each one unlocks more of the UI:**

| Add | You get |
|---|---|
| `status = "/v1/status"` returning `{loaded, busy, idle_s, stats, jobs}` | load state, a busy dot, KPIs on the Overview tile (numeric stats are charted over time), jobs in the header |
| Files written to `$AIHUB_OUTPUTS/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext>` (+ `[outputs]`) | they appear on the Outputs page |
| `[memory]` with `load` / `unload` operations and `estimate_gb` | the memory panel; AIHub can unload it to make room |
| `[[ui.widgets]]` pointing at a route that returns `WidgetData` | charts on the Overview dashboard |
| `ui/page.js` (`[ui] page`) | its own tab(s) inside the mod's page |
| `[tools]` | operations the agent may call |

Every mod also gets, for free: start/stop/restart, health monitoring with restart on failure, logs, a Settings tab, and an **API tab** built from its `/openapi.json`.

## Working on it

```bash
aihub check __ID__        # validates the manifest, health, OpenAPI, status shape, widgets and page
aihub restart __ID__      # after editing server.py
aihub logs __ID__ -f
./install.sh              # after changing requirements.txt
```

- Calls through AIHub: `http://127.0.0.1:7000/api/s/__ID__/v1/hello?name=you`
- Directly: `http://127.0.0.1:__PORT__/v1/hello`
- Deleting this folder removes the mod completely (then `aihub restart`).
