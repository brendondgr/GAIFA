# AIHub

One local app (FastAPI hub on `127.0.0.1:7000`) that controls every AI service on this machine. Each service is a **mod**: a folder in `services/<id>/`, run as its own process. Design: [docs/architecture.md](docs/architecture.md). Build plan: [docs/backend-plan.md](docs/backend-plan.md). UI brief: [docs/design-brief-ui.md](docs/design-brief-ui.md).

**Status:** Phase 1 in progress: 1.2–1.6 done (`utils/` paths, config, db, events, server, cli; `app.py`; `bin/aihub`, installed as `aihub.service`). Next: 1.7. What exists today: [docs/structure.md](docs/structure.md).

**Skills:** load `aihub` before working here (doc map, invariants, how to work a plan step). Use `plan` to write or change plans.

## Layout
- `utils/`: hub code (Python package) · `services/`: mods · `web/`: the UI (Claude Design `.dc.html` export)
- `data/models/` (only `registry.json` is tracked) · `data/databases/` · `outputs/<mod>/<date>/`
- `docs/`: architecture, plan, UI brief, `reference/` UI exports

## Commands
- `uv sync`: install hub dependencies into `.venv/`
- `uv run pytest`: the test suite (`utils/tests/`)
- `uv run python app.py`: run the hub in the foreground on 127.0.0.1:7000 (`/api/docs` for the API)
- `aihub status | start | stop | restart | logs [-f] | doctor | open`: the hub as a systemd user service (`aihub install` writes `~/.config/systemd/user/aihub.service` and links `~/.local/bin/aihub`). After changing hub code, `aihub restart`.

## Mod contract
1. `services/<id>/service.toml`, with `id` matching `[a-z][a-z0-9-]{1,31}` and the folder name.
2. An HTTP server on `127.0.0.1:<port>`, in any language.
3. A health route that returns 2xx when ready.
4. Optional extras (memory, status, outputs, UI, widgets) are listed in architecture §4.2.
5. Deleting `services/<id>/` removes the mod completely.

## Rules
- **Never run `git clean -x` or `git clean -X`.** They delete ignored files, which here means ~190 GB of model weights.
- Nothing is written outside the project root, except the allowlist in plan Phase 12.4.
- Mods talk to the hub only over HTTP.
- No import-time side effects.
- Tests pass before every commit. Commit message style: `AIHub (2.3): Service state machine with health checks`.
- Keep `docs/` in sync with behavior, in the same commit. That includes `docs/structure.md` when files are added, moved or removed.
- Files under ~500 lines; split any that pass 800.
