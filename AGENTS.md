# AGENTS.md

Working notes for agents in this repo. Product docs: [README.md](README.md),
[docs/api.md](docs/api.md). The relay this publishes to is
`~/Tools/DashLLM` (its own AGENTS.md applies there).

## Commands

```bash
uv run pytest -q                    # all tests; fake llama-server + fake relay
utils/e2e_live.sh                   # real daemon + relay + llama-server
uv run python utils/smoke_supervisor.py minicpm 7071
systemctl --user restart lcpp       # pick up backend changes (web/ is read live)
```

Commit only after `uv run pytest` passes. For supervisor, backend or relay
changes, also run `utils/e2e_live.sh`.

## Things that will bite you

- **The CLI must stay stdlib-only.** `lcpp.cli`, `lcpp.client`,
  `lcpp.doctor`, `lcpp.service` and everything they import (`settings`,
  `paths`, `catalog`, `proc`) must not import FastAPI, httpx, uvicorn or
  pydantic. `test_cli_import_stays_light` enforces it. That is why `lcpp`
  answers in ~65 ms.
- **Instances are not the daemon's children.** They are transient units
  (`lcpp-<name>.service`) started with `systemd-run --user`, so a daemon
  restart never kills a model. Do not "simplify" this to subprocesses outside
  tests: `SubprocessBackend` exists only for tests and `--dev`, and its
  children die with the daemon.
- **Idle means idle.** Nothing may poll while no instance is starting.
  - A ready instance's exit is detected by a pidfd on the event loop
    (`supervisor._exit_future`).
  - The relay retry loop exists only while something is pending.
  - uvicorn's tick is slowed to 1 s (`QuietServer`).
  - The web UI polls only while its tab is visible.
  - `utils/measure_idle.sh` should show ~0% CPU.
- **Unified memory.** A process's VmRSS misses the model; footprint =
  RSS + DRM GTT/VRAM over the whole process tree (`proc.footprint`).
- **llama-server boolean flags come in three styles** (`--x on|off`,
  `--x/--no-x`, plain switch). See `cmdline.ON_OFF` / `NEGATABLE` before
  adding a param that "doesn't work".
- **Hugging Face downloads run inside the daemon** (`lcpp.downloads`, httpx).
  A daemon restart stops them. The `.part` file stays and a retry resumes it,
  so do not delete `.part` files on failure, only on cancel or a checksum
  mismatch. Tests fake the Hub with `httpx.MockTransport`. Never let one
  reach the network.
- **Relay model names are unique across endpoints.** A router must not
  advertise a model that a published single instance serves.
  - `relay._body` excludes those models.
  - Routers are re-registered when a single comes or goes.
  - `reconcile` registers routers before singles.
  - Tests cover all three; keep that ordering.
- **Registrations are idempotent on the relay side** (PUT upsert, DELETE 204
  when gone). Rely on that and repeat calls freely; never add "does it exist?"
  checks before them.
- **`data/*.json` writes are atomic** (`paths.write_atomic`); never write them
  in place. `data/recent.local.json` is machine-local and gitignored.
- **The web UI's contract is `web/assets/api.js`.** `test_web` checks every
  call there against the daemon's OpenAPI paths. The mock
  (`web/assets/mock.js`) documents the shapes; keep the live API matching it
  (see docs/api.md for deliberate differences).
- **TestClient cannot consume an endless SSE stream** (it buffers the whole
  body). Test followers directly, as `test_log_follow_yields_new_lines` does.
  A per-test timeout (60 s) turns such hangs into failures.
- **Never `pkill -f` a pattern that appears in your own shell command** (e.g.
  `pytest-of-…`): it kills the shell running it.
