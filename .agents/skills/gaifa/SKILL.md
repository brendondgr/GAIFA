---
name: gaifa
description: Project guide for GAIFA. Use before any work in this repo — implementing a plan step, adding or changing a mod, touching the hub API or UI wiring, or answering "where does X go / how does X work". Maps every question to the doc section that answers it, lists the invariants, and gives the step-by-step workflow for working a plan in docs/plans/.
---

# Working on GAIFA

GAIFA is one local app (FastAPI hub on `127.0.0.1:7000`, no auth) that controls every AI service on this machine. Each service is a **mod**: a folder in `services/<id>/` with a `service.toml`, run as its own process (a transient systemd user unit `gaifa-<id>.service`). The hub supervises mods, proxies their APIs at `/api/s/<id>/*`, keeps a models registry, indexes outputs, manages the 121 GB of shared memory, records metrics, and serves the UI from `web/`.

The docs are the source of truth. Read the section you need before acting; don't work from memory of them.

## Where to look

| Question | Read |
| --- | --- |
| Why is it built this way? | architecture §2 (decisions table) |
| Where does a file go? | architecture §3, then [docs/structure.md](../../../docs/structure.md) for what exists today |
| Building, porting or fixing a mod (how-to) | [docs/mods.md](../../../docs/mods.md) and the `gaifa-mod` skill; `gaifa check <id>` |
| What must a mod provide? `service.toml` fields? | architecture §4.1–4.3 |
| Placeholders, env vars, ports | architecture §4.4–4.5 |
| Status route shape, stats → charts | architecture §4.6 |
| Where and how mods write outputs | architecture §4.7 |
| Boot order, request flow, processes | architecture §5 |
| Hub-only routes, error envelope | architecture §6 |
| UI-facing API contract (methods, types, errors) | design-brief-ui §6, §11.7 |
| Memory sampling and make-room rule | architecture §7 |
| Models registry format | architecture §8 |
| `config.toml` | architecture §9 |
| Each existing app → mod (ports, paths, changes) | architecture §10, backend-plan Phases 7–11 |
| Risks and gotchas | architecture §12 |
| Metrics tables, retention, widgets | architecture §13, brief §11.5–11.7 |
| Chat agent, approvals, sessions | architecture §14, backend-plan Phases 14–16 |
| What to build next, and its checks | [docs/plans/README.md](../../../docs/plans/README.md) (the open plans), then that plan's first unticked step |
| Why something was built the way it was (Phases 0–51) | [docs/backend-plan.md](../../../docs/backend-plan.md) (closed: history only) |
| Mod page modules (`page.js`, `Page.dc.html`) | brief §5 |
| UI states that must be reachable | brief §8, §11.10 |
| The UI baseline | `docs/reference/ui-export-2026-10-04/README.md` |
| ComfyUI workflow packs (`workflow.toml`, tasks, the CLI) | [docs/workflows.md](../../../docs/workflows.md); skill `comfy-workflow` |
| Setting up a machine, or some mods (`gaifa setup`) | [docs/setup/README.md](../../../docs/setup/README.md), each mod's `services/<id>/setup/*.md`; skill `gaifa-setup` |
| A mod's setup doc and its `gaifa-setup` block | [docs/mods.md §9](../../../docs/mods.md#9-setup-docs) |

## Invariants (never break these)
- **Never run `git clean -x` or `-X`.** Ignored files include ~190 GB of model weights.
- **`relay`, `lcpp`, `tts` and `gen3d` are submodules** of their own repositories (plan mod-repos): commit in the mod first (its tests, push), then the pin in GAIFA (`gaifa repos pin <id>`); `gaifa repos status` before a GAIFA commit; never an unpushed pin, a force push to a mod, or `git submodule update` over a mod's changes. docs/mods.md §10.
- **The Auto judge is a decision model only**, in the `decide` mod: d3-lite by default or any decision model the user sets up there (its test advises, never blocks; plan capability-enablement), never a chat model through the relay (plan web-approvals).
- **Loopback by default.** The hub refuses a non-loopback `hub.host`; other devices on your own network get in only when the user opens it (`[hub.lan]`, plan lan-access), through `utils/lan/guard.py`: a password, their own Host and Origin rules, never the internet, and what widens GAIFA's reach stays on this machine (`utils/lan/limits.py`). Mods always listen on 127.0.0.1 only.
- **Mods talk to the hub only over HTTP.** No hub imports in mods, no mod imports in the hub. Adding a mod never needs a hub code change.
- **No import-time side effects.** Everything starts in `create_app()`'s lifespan, in the §5 order.
- **Nothing written outside the project root**, except the Phase 12.4 allowlist and folders the user set to Edit or above (the `workspace` mod, plan Phase 27). The GAIFA folder and `data/models/` stay at Read.
- **`web/support.js` is generated; never edit it.** Any change to an export goes in `web/PATCHES.md`.
- **Errors use the envelope** `{detail, code, data?}`; proxied mod responses pass through unchanged.
- **Mod ids and ports are fixed** (architecture §2): `relay` 4000, `opencode` 4096, `lcpp` 7710, `tts` 5040, `gen3d` 5050, `comfy` 5070; new mods 5100–5199.
- **The existing apps keep running until their cutover step.** Stopping their services, moving models, or deleting anything in the old repos needs the user's approval.

## Working a plan step
1. Find the plan in `docs/plans/README.md` (the user names it, or it's the one in progress) and its first unticked step. Check its phase's earlier steps are ticked.
2. Read the architecture and brief sections the step cites.
3. Build it, with tests in `utils/tests/<area>/test_<behavior>.py` (fake mods in `utils/tests/fixtures/mods/`).
4. `uv run pytest` must be green. It includes the Node tests for `web/api.js` (`utils/tests/web/`); inside the toolbox they use the host's Node via `flatpak-spawn --host node`.
   To check against the installed hub, run `gaifa restart` and reload the page (changing only the `#/…` hash doesn't reload it).
   For UI checks with fake mods, run a second hub: `uv run python app.py --port 7077 --dev --demo-mods` (child processes; the installed hub on 7000 and its units are untouched). Tests never touch the real root or hub: `conftest.py` points `GAIFA_ROOT`/`GAIFA_URL` at throwaway values.
5. In the same commit: tick the step in the plan, keep its status in `docs/plans/README.md` current, update `docs/structure.md` for new files, and update architecture / brief §6 / §11.7 if behavior differs from what they say.
6. Commit as `GAIFA (<plan-slug> <phase>.<step>): <what was done>`. Push when the user asks or at the end of a phase.
7. At the end of a phase, run its **Wire** and **Checks & deliverables** lists before starting the next phase.

To write or change a plan, use the `plan` skill. New work always gets a new file in `docs/plans/`; `docs/backend-plan.md` is closed and never gains phases.

## Code conventions
- Python ≥ 3.12, FastAPI + uvicorn + httpx, pydantic v2, SQLite; dependencies via `uv` only.
- Files under ~500 lines, 800 max. Small subsystems are single files in `utils/`; larger ones become a sub-package with `__init__.py`.
- One FastAPI router per area in `utils/routes/`; each area registers itself as live for `/config.js`.
- `utils/cli.py` is standard library only.
- Atomic writes (`paths.write_atomic`) for registry and config; `config.save()` goes through `tomlkit` to keep comments.
