# OpenCode (AIHub mod)

`opencode serve` on `127.0.0.1:4096`, the upstream behind the relay's `agent` model. AIHub only starts, stops and health-checks it (TCP: every route needs HTTP Basic auth).

- `run.sh`: sources `.env`, loads or mints the Basic credential (`auth.sh`), and runs `opencode serve` in `OPENCODE_PROJECT_DIR`.
- `.env` (gitignored): `OPENCODE_*` settings and provider keys (`OPENCODE_API_KEY`, …). The relay reads the same credential (its `.env`, or `OPENCODE_AUTH_FILE` = this folder's `opencode-auth.env`).
- `opencode` itself is installed in `~/.opencode/bin` (outside AIHub; allowed by plan Phase 12.4).
- Setup on a new machine: [setup/opencode.md](setup/opencode.md); the keys `.env` takes are in `.env.example`.
