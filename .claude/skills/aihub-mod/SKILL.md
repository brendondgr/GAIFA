---
name: aihub-mod
description: Use when asked to build, port, fix or extend an AIHub mod: "make a mod for X", "add <app> to AIHub", "give my mod a page / chart / status", or when `aihub check <id>` fails. Covers the mod contract, the new → edit → check → restart loop, status/widgets/page modules, outputs, memory and tools.
---

# Building an AIHub mod

A mod is a folder `services/<id>/` with a `service.toml` and an HTTP server on `127.0.0.1:$AIHUB_PORT`. The hub supervises it, proxies `/api/s/<id>/*`, and builds UI from its OpenAPI. **Read [docs/mods.md](../../../docs/mods.md) first.** It's the whole contract on one page. The reference behind it is architecture §4.

## The loop (always)
1. **Start from the template:** `aihub new <id> [--name "…"] [--port N]`. Never hand-copy `services/_template/`, which has `__ID__` tokens.
2. **Edit** `services/<id>/server.py` and `service.toml`.
3. **Reload:** `aihub restart <id>` after code changes; `aihub rescan` after manifest changes or adding/removing folders.
4. **Check:** run `aihub check <id> --start` and fix every `FAIL` (the fix table is in docs/mods.md §8). Repeat until it prints **"all checks passed"**. Don't call a mod done before that.
5. **Look at it:** `aihub url "#/s/<id>"`. Use the API tab to try each operation, and the Logs tab for errors.

## Rules
- **Talk to the hub only over HTTP:** `$AIHUB_URL`. Never import hub code into a mod, or mod code into the hub. Adding a mod must not need a hub change. If it seems to, stop and ask.
- **Read the port and folders from the environment:** `AIHUB_PORT`, `AIHUB_OUTPUTS`, `AIHUB_MODELS`, `AIHUB_DATABASES`. Listen on 127.0.0.1 only.
- **Ports and ids:** new mods use 5100–5199 (`aihub new` picks one). The ids and ports of existing apps are fixed (architecture §2).
- **Python mods** keep their venv in the mod folder (`install.sh`, uv-managed Python) and run `.venv/bin/python`.
- **Outputs** follow architecture §4.7: `<date>/<HHMMSS>-<slug>.<ext>`, `.part` then rename, optional sidecar JSON.
- **Page modules** use only `ctx` (`ctx.call`, `ctx.api`, `ctx.ui`, `ctx.on`): no `fetch`, no raw colors, and a Start button when the mod is stopped.
- **Don't stop or move the existing apps' services, models or data** without the user's approval (see the `aihub` skill's invariants).
- **Ship a setup doc:** `services/<id>/setup/<env>.md` from the template (`aihub new` copies one), with its `aihub-setup` block filled in (summary, steps, check, a few optional model suggestions) so `aihub setup <id>` can install it; describe the mod, not this machine's models (docs/mods.md §9). `aihub docs --check --strict` must pass.

## Choosing how much UI
Each level is optional; pick the least that serves the user (docs/mods.md §5):
1. **Level 0:** nothing extra. The generic page and the API tab come from the OpenAPI. Add `[api.responses]` for audio, image or file routes.
2. **Level 1:** a `status` route. Load state, busy, up to 4 stats (numeric ones are auto-charted) and jobs.
3. **Level 2:** `[[ui.widgets]]` + a route returning `WidgetData`, for Overview dashboard charts.
4. **Level 3:** `ui/page.js`, for the mod's own tabs.

## Porting an existing app
Follow docs/mods.md §7. Map its port and output settings to placeholders in `[run].env`, pick a cheap health route, and use `kind = "external"` only when the app must keep running outside AIHub. For the apps already planned (tts, gen3d, relay, opencode, lcpp, comfy), follow their phase in `docs/backend-plan.md` (Phases 7–11). Those phases carry approvals and cutover steps.
