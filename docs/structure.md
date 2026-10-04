# AIHub — Repository structure

What is in the repo **today**, and where each planned piece goes. The full target layout and the reasons behind it are in [architecture.md §3](architecture.md#3-directory-layout). Update this file in the same commit whenever a file or folder is added, moved or removed.

**Status key:** ✅ exists · 🧱 placeholder folder (empty, `.gitkeep`) · ⏳ planned (with the plan step that creates it)

## Top level

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `CLAUDE.md` | ✅ | Short rules for agents, true today |
| `.claude/skills/aihub/` | ✅ | Project skill: how to work on AIHub (doc map, invariants, step workflow) |
| `.claude/skills/plan/` | ✅ | Project skill: how to write and amend plans in this repo's format |
| `.gitignore` | ✅ | Keeps models, databases, outputs and venvs out of git |
| `pyproject.toml` | ✅ | Hub dependencies (uv) |
| `uv.lock` | ✅ | Locked hub dependencies; `uv sync` builds `.venv/` (ignored) from it |
| `app.py` | ⏳ 1.5 | `python app.py` starts the hub |
| `config.toml` | ✅ | User settings (architecture §9); a missing file means defaults |
| `bin/` | 🧱 | `aihub` command (1.6) and `aihub.service.in` systemd template (1.6) |
| `docs/` | ✅ | Design, plan, UI brief, this file, `reference/` UI exports |
| `utils/` | ✅ | The hub's Python package (below) |
| `services/` | 🧱 | One folder per mod; `_template/` is filled in 2.8 |
| `data/` | ✅ | Models, databases (below); `logs/` and `state/` arrive in Stage D |
| `outputs/` | 🧱 | `<mod>/<YYYY-MM-DD>/…`, ignored by git |
| `web/` | 🧱 | The UI, copied from the Claude Design export in 1.8 |

## `docs/`

| File | Purpose |
| :--- | :--- |
| `architecture.md` | The agreed design: decisions, layout, mod contract, runtime, API, memory, registry, config, metrics, Stage D |
| `backend-plan.md` | The build plan: Phases 0–16 with steps, checks and deliverables; steps are ticked as they land |
| `design-brief-ui.md` | UI brief for Claude Design; §6 and §11.7 are the UI-facing API contract |
| `structure.md` | This file |
| `reference/ui-export-2026-10-04/` | Claude Design's Part A v1 export, the UI baseline (read-only reference) |

## `utils/` — the hub package

Small subsystems are single files directly in `utils/`; anything that grows into several modules gets its own sub-package with an `__init__.py` (as `backends/` and `routes/` already do).

| File / folder | Status | Purpose |
| :--- | :--- | :--- |
| `__init__.py` | ✅ | Package marker; nothing runs at import time |
| `paths.py` | ✅ | `Paths` (root, configurable dirs kept inside the root), `write_atomic()` |
| `config.py` | ✅ | `Config` (pydantic, §9), `load()`, `save()` via tomlkit, `service_override()`, loopback check |
| `db.py` | ✅ | `Database`: `hub.db` (WAL), migrations by `user_version`, one writer thread, async helpers |
| `events.py` | ✅ | `EventBus` (per-subscriber queue, overflow → resync), `ActivityLog`, `Alerts`, `sse_stream()` |
| `server.py` | ⏳ 1.5 | `create_app()`, lifespan, static `web/`, error envelope |
| `cli.py` | ⏳ 1.6 | Standard-library CLI behind `bin/aihub` |
| `manifest.py` | ⏳ 2.1 | `service.toml` schema, discovery, placeholders |
| `backends/` | ✅ pkg · ⏳ 2.2 | `base.py`, `systemd.py`, `subprocess.py` |
| `services.py` | ⏳ 2.3 | Mod state machine, health and status polling |
| `proxy.py` | ⏳ 2.5 | `/api/s/<id>/*` passthrough |
| `operations.py` | ⏳ 2.6 | Mod OpenAPI → `Operation[]` |
| `registry.py` | ⏳ 3 | Models registry |
| `outputs.py` | ⏳ 4 | Outputs watcher and index |
| `memory.py`, `proc.py` | ⏳ 5 | Memory sampling and make-room plans; per-process memory |
| `metrics.py` | ⏳ 6.1 | Time series recorder and rollups |
| `tools.py` | ⏳ 13 | Agent tool catalog and approvals |
| `routes/` | ✅ pkg | One FastAPI router per area, added with each area: `events.py` (`GET /api/events`) |
| `tests/` | ✅ | pytest suite (below) |

## `utils/tests/`

Tests stay inside the hub package, as the plan specifies. Group them by area as they grow, so no folder becomes a flat dump:

```text
utils/tests/
├── conftest.py                 ⏳ 1.7  temp project root, app on SubprocessBackend, ASGI client
├── fixtures/
│   ├── mods/                   🧱     fake_ok, fake_slow, fake_crash, fake_mem (1.7)
│   └── openapi/                🧱     real OpenAPI captures from Phase 0.5
├── core/test_<behavior>.py     ✅     paths, config, db, events (server follows)
├── services/test_<behavior>.py        manifest, backends, state machine, proxy, operations
└── <area>/test_<behavior>.py          registry, outputs, memory, metrics, …
```

## `data/`

| Path | Tracked | Purpose |
| :--- | :--- | :--- |
| `data/models/registry.json` | yes | The models registry (architecture §8) |
| `data/models/<kind>/…` | no | Model weights (~190 GB once moved in) |
| `data/databases/` | no | `hub.db`, `relay.db`, `gen3d.db`, later `agent.db` |

## Conventions

- **File length:** aim for under 500 lines; split any file that passes 800.
- **Packages:** `uv` only (`uv add`, `uv sync`, `uv run`).
- **No `libs/`:** shared code lives in `utils/`, and mods share nothing with the hub except HTTP.
- **Mods** follow their own internal layout; the agent mod (Stage D) follows the LangGraph layout noted in architecture §14.1.
