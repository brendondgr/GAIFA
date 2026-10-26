---
name: gaifa-mod
description: >-
  Use when asked to build, port, fix or extend a GAIFA mod: "make a mod for X", "add <app> to GAIFA", "give my mod a page / chart / status", or when `gaifa check <id>` fails. Covers the mod contract, the new → edit → check → restart loop, status/widgets/page modules, outputs, memory and tools.
---

# Building a GAIFA mod

A mod is a folder `services/<id>/` with a `service.toml` and an HTTP server on `127.0.0.1:$GAIFA_PORT`. The hub supervises it, proxies `/api/s/<id>/*`, and builds UI from its OpenAPI. **Read [docs/mods.md](../../../docs/mods.md) first.** It's the whole contract on one page. The reference behind it is architecture §4.

## The loop (always)
1. **Start from the template:** `gaifa new <id> [--name "…"] [--port N]`. Never hand-copy `services/_template/`, which has `__ID__` tokens.
2. **Edit** `services/<id>/server.py` and `service.toml`.
3. **Reload:** `gaifa restart <id>` after code changes; `gaifa rescan` after manifest changes or adding/removing folders.
4. **Check:** run `gaifa check <id> --start` and fix every `FAIL` (the fix table is in docs/mods.md §8). Repeat until it prints **"all checks passed"**. Don't call a mod done before that.
5. **Look at it:** `gaifa url "#/s/<id>"`. Use the API tab to try each operation, and the Logs tab for errors.

## Rules
- **Talk to the hub only over HTTP:** `$GAIFA_URL`. Never import hub code into a mod, or mod code into the hub. Adding a mod must not need a hub change. If it seems to, stop and ask.
- **Read the port and folders from the environment:** `GAIFA_PORT`, `GAIFA_OUTPUTS`, `GAIFA_MODELS`, `GAIFA_DATABASES`. Listen on 127.0.0.1 only.
- **Ports and ids:** new mods use 5100–5199 (`gaifa new` picks one). The ids and ports of existing apps are fixed (architecture §2).
- **Python mods** keep their venv in the mod folder (`install.sh`, uv-managed Python) and run `.venv/bin/python`.
- **Outputs** follow architecture §4.7: `<date>/<HHMMSS>-<slug>.<ext>`, `.part` then rename, optional sidecar JSON.
- **Page modules** use only `ctx` (`ctx.call`, `ctx.api`, `ctx.ui`, `ctx.on`): no `fetch`, no raw colors, and a Start button when the mod is stopped.
- **Don't stop or move the existing apps' services, models or data** without the user's approval (see the `gaifa` skill's invariants).
- **`relay`, `lcpp`, `tts`, `gen3d` are their own repositories** (submodules): work on a branch in the mod's repository (or a worktree of it, outside GAIFA), run its tests, push, then `gaifa repos pin <id>` and commit GAIFA. To make a new mod a repository of its own, docs/mods.md §10 (preflight, push, adopt).
- **Ship a setup doc:** `services/<id>/setup/<env>.md` from the template (`gaifa new` copies one), with its `gaifa-setup` block filled in (summary, steps, check, a few optional model suggestions) so `gaifa setup <id>` can install it; describe the mod, not this machine's models (docs/mods.md §9). `gaifa docs --check --strict` must pass.

## Choosing how much UI
Each level is optional; pick the least that serves the user (docs/mods.md §5):
1. **Level 0:** nothing extra. The generic page and the API tab come from the OpenAPI. Add `[api.responses]` for audio, image or file routes.
2. **Level 1:** a `status` route. Load state, busy, up to 4 stats (numeric ones are auto-charted) and jobs.
3. **Level 2:** `[[ui.widgets]]` + a route returning `WidgetData`, for Overview dashboard charts.
4. **Level 3:** `ui/page.js`, for the mod's own tabs.

## Porting an existing app
Follow docs/mods.md §7. Map its port and output settings to placeholders in `[run].env`, pick a cheap health route, and use `kind = "external"` only when the app must keep running outside GAIFA. For the apps already planned (tts, gen3d, relay, opencode, lcpp, comfy), follow their phase in `docs/backend-plan.md` (Phases 7–11). Those phases carry approvals and cutover steps.
