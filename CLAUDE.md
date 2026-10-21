# AIHub

One local app (FastAPI hub on `127.0.0.1:7000`) that controls every AI service on this machine. Each service is a **mod**: a folder in `services/<id>/`, run as its own process. Design: [docs/architecture.md](docs/architecture.md). Build plan: [docs/backend-plan.md](docs/backend-plan.md). UI brief: [docs/design-brief-ui.md](docs/design-brief-ui.md).

**Status:** Phase 6 built: the metrics recorder and chart routes (`utils/metrics/`), mod widgets, `GET /api/overview`, `GET/PUT /api/settings`, the final alert list, the contract test, and UI revision 2 built by hand (6.5: compact default, four Overview views, the dashboard and chart kit in `web/`), approved by the user on 2026-10-06; on top of Phase 5's memory manager, Phase 4's outputs index, Phase 3's models registry and Phase 2's mods. Live areas: everything in Part A except `tools`. Stage B done (Phases 7–10): tts (LocalTTS), gen3d (3DGenerate), relay (DashLLM), opencode and lcpp (LLMs) are mods with their pages; their old units are disabled. Phase 11 done: comfy (Images & Video) runs ComfyUI workflow packs (`services/comfy/workflows/<id>/`, guide [docs/workflows.md](docs/workflows.md)), with task tools for the agent; held-out results in [docs/comfy-transfer-report.md](docs/comfy-transfer-report.md). Phase 12 done: the speech engines (`services/tts/runtime/`) and CubeArt (`services/gen3d/runtime/`) run inside their mods, the transition symlinks are gone, plus `aihub doctor` and `aihub backup`. Phases 13–16 done (overnight 2026-10-07; report: `docs/report/report.pdf`, local only: it, its data and images are gitignored): the agent tool catalog with risk levels and approvals (`utils/tools/`, `/api/tools`, `/api/approvals`, `/mcp`), the relay's model facts, the chat agent mod `services/agent` (our own loop; eval in `services/agent/evals/`, results in [docs/agent-eval.md](docs/agent-eval.md)), the Chat page (`web/chat/`), sessions (`utils/sessions.py`), logs in `data/logs/`, lcpp state in `data/state/`, `aihub doctor --inventory`. Phase 19 done (2026-10-19): the Chat page draws each turn as one activity fold (a live status header, plain step rows from `registerStep`, an output strip, approvals and questions docked on the composer); screenshots in `docs/reference/chat-activity-2026-10/`. Phase 20 built (2026-10-19): engines and workflow packs declare what they can do as `x-options` on their tools' enums (`utils/tools/options.py`; brief §11.12), the hub fills the default that fits and refuses pairings that don't with a fix, the model reads the choices as text (`/api/tools?view=model`), and the card lists only what fits (`web/mod-options.js`). Phases 21–22 built (2026-10-20): complete tool records and hub-side preferences filled into every caller's cards (`utils/prefs.py`, `/api/prefs`; the miner in `services/agent/agent/learn/mine.py`), and a learner after Harness² that improves the agent's harness (`services/agent/harness/`, `agent/harness.py`, `agent/learn/`), with the Learning page at `#/s/agent/learning`. Phase 20's live runs passed on 2026-10-20 (`docs/agent-eval.md`). Stage J done (Phases 24–30, 2026-10-20/21; live checks run overnight on the installed hub): documents, text and code in Chat (`utils/outputs/text.py`, reading tools, citations, the viewer), permission tiers `network`/`execute` and grants (`utils/tools/grants.py`), the `web` and `searxng` mods (SearXNG in Docker outside AIHub), the `workspace` mod (folders with levels, edits in place with undo, a podman sandbox, the five chat modes Plan/Manual/Accept edits/Auto/Bypass), the `embed` mod (EmbeddingGemma 2: search by meaning, conversation lookup), the `stt` mod (faster-whisper, dictation), and the Auto judge (`utils/tools/judge.py`, rules + a model; the `decide` mod for decision models; page screening); this machine's judge is gemma4-26B (Settings → Agent). Open: where opencode's `OPENCODE_PROJECT_DIR` should point; lcpp's CLI installed as a uv tool (outside the folder). What exists: [docs/structure.md](docs/structure.md).

**Skills:** load `aihub` before working here (doc map, invariants, how to work a plan step). Use `plan` to write or change plans, `aihub-mod` to build or port a mod (guide: [docs/mods.md](docs/mods.md)), and `comfy-workflow` for ComfyUI workflow packs (guide: [docs/workflows.md](docs/workflows.md)).

## Layout
- `utils/`: hub code (Python package) · `services/`: mods · `web/`: the UI (Claude Design `.dc.html` format; revision 2 built here, see `web/PATCHES.md`)
- `data/models/` (only `registry.json` is tracked) · `data/databases/` · `outputs/<mod>/<date>/`
- `docs/`: architecture, plan, UI brief, `reference/` UI exports

## Commands
- `uv sync`: install hub dependencies into `.venv/`
- `uv run pytest`: the test suite (`utils/tests/`)
- `uv run python app.py`: run the hub in the foreground on 127.0.0.1:7000 (`/api/docs` for the API)
- `aihub new <id>`: a new mod from `services/_template/`, installed and loaded; `aihub rescan` after adding or removing mod folders by hand.
- `aihub models list | show <id> | scan [--add] | verify <id>… | --all`: the models registry.
- `aihub status | start | stop | restart | logs [id] [-f] | doctor [--inventory] | open`: the hub as a systemd user service (logs read `data/logs/<id>.log`) (`aihub install` writes `~/.config/systemd/user/aihub.service` and links `~/.local/bin/aihub`). After changing hub code, `aihub restart`. `aihub doctor` checks the whole install (also Settings → About).
- `aihub backup <folder>`: databases, registry, `config.toml` and the mods' `.env` files in a dated archive.

## Mod contract
Full how-to: [docs/mods.md](docs/mods.md). A mod is done when `aihub check <id>` passes.
1. `services/<id>/service.toml`, with `id` matching `[a-z][a-z0-9-]{1,31}` and the folder name.
2. An HTTP server on `127.0.0.1:<port>`, in any language.
3. A health route that returns 2xx when ready.
4. Optional extras (memory, status, outputs, UI, widgets) are listed in architecture §4.2.
5. Deleting `services/<id>/` removes the mod completely.

## Rules
- **Never run `git clean -x` or `git clean -X`.** They delete ignored files, which here means ~190 GB of model weights.
- Nothing is written outside the project root, except the allowlist in plan Phase 12.4 and folders the user set to Edit or above in the workspace mod (plan Phase 27). The allowlist includes SearXNG's `settings.yml` and its `settings.yml.aihub-<date>` backups, written by the `searxng` mod (plan 26.3). The AIHub folder and `data/models/` never go above Read.
- Mods talk to the hub only over HTTP.
- No import-time side effects.
- Tests pass before every commit. Commit message style: `AIHub (2.3): Service state machine with health checks`.
- Keep `docs/` in sync with behavior, in the same commit. That includes `docs/structure.md` when files are added, moved or removed.
- Files under ~500 lines; split any that pass 800.
