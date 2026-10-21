<!-- aihub-setup
id = "opencode"
title = "OpenCode"
models = []
scan = []
summary = "OpenCode: a coding agent behind the relay's agent model, plus OpenCode Zen's free hosted models"
gpu = false
disk_gb = 0.2
needs = ["opencode"]
after = []
check = "aihub check opencode --start"

[[steps]]
run = "opencode auth login"
what = "stores a provider key (OpenCode Zen or another) in ~/.local/share/opencode/auth.json; interactive"
ask = "Log OpenCode in to a provider now? Answer no if this folder's .env sets OPENCODE_API_KEY."

[[steps]]
run = "aihub start opencode"
what = "starts opencode serve on 127.0.0.1:4096; the first start mints the Basic credential in opencode-auth.env"

[[steps]]
run = "aihub restart relay"
what = "lets a relay that is already running register the agent endpoint with the new credential"
ask = "Is the relay already set up and running? Yes restarts it now."
-->

# OpenCode: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `opencode` mod runs `opencode serve` on `127.0.0.1:4096`. It's the upstream behind the relay's `agent` model, and it gives the relay OpenCode Zen's free hosted models (`opencode/…-free`). The mod is only a manifest and two scripts: `run.sh` sources `.env`, loads or mints the HTTP Basic credential (`auth.sh`) and runs `opencode serve` in `OPENCODE_PROJECT_DIR`. The `opencode` binary itself is installed outside AIHub, in `~/.opencode/bin` (allowed by plan Phase 12.4). The mod is optional: nothing else in AIHub needs it.

## Tested with

Read from this machine on 2026-10-21:

| Part | Version |
|---|---|
| `opencode` | 1.17.13, `~/.opencode/bin/opencode` (a single 168 MB binary) |
| `@opencode-ai/plugin` | 1.17.13 (`~/.opencode/package.json`) |
| Credentials | `~/.local/share/opencode/auth.json`: one, provider OpenCode, type api |

## Prerequisites

- [The hub](../../../docs/setup/hub.md). No GPU, no models.
- An OpenCode Zen API key, or a key for another provider OpenCode supports ([host.md §6](../../../docs/setup/host.md#6-accounts-and-licences)).
- Install it before the [relay](../../relay/setup/relay.md) starts, or restart the relay afterwards: the relay looks for the credential only at start.

## Install

The `opencode` command must exist before `aihub setup` runs this doc: install OpenCode from <https://opencode.ai> first. Its installer puts the binary in `~/.opencode/bin/` and adds that folder to `PATH` in `~/.bashrc` (here: `export PATH=/home/bdgr/.opencode/bin:$PATH`). `run.sh` adds `~/.opencode/bin` to `PATH` itself, since a systemd unit doesn't read `~/.bashrc`.

Give OpenCode a provider key, either once interactively:

```bash
opencode auth login
```

(`auth` is an alias of `opencode providers`; the key goes to `~/.local/share/opencode/auth.json`), or as `OPENCODE_API_KEY` in this folder's `.env` (below).

There's no `aihub install opencode` step: the mod has no venv. Start it:

```bash
aihub start opencode
```

On its first start `auth.sh` writes `opencode-auth.env` in this folder (gitignored, mode 600) with `OPENCODE_SERVER_USERNAME=opencode` and a random password (24 random bytes in base64, letters and digits only: up to 32 characters). Every later start reuses it; delete the file to rotate it. Then restart the relay so it registers the `agent` endpoint with that credential:

```bash
aihub restart relay
```

## Choosing models

The mod downloads no model, so it has no suggestions. OpenCode calls hosted providers: with an OpenCode Zen key, the relay serves its free models (`opencode/…-free`) and the `agent` alias; the relay drops paid ids. Which model `agent` runs is set on the relay's Endpoints view. Local models belong to [llama.cpp](../../lcpp/setup/llama-cpp.md) or [vLLM](../../vllm/setup/vllm.md).

## Configuration

`service.toml` `[run.env]` sets `OPENCODE_PORT = "{port}"` (4096). Everything else is optional, in `.env` here (gitignored; start from `.env.example`):

| Key | Required | Meaning |
|---|---|---|
| `OPENCODE_PROJECT_DIR` | optional, but set it | the folder OpenCode's bash, edit and write tools act in. Unset, it's `services/opencode/` |
| `OPENCODE_API_KEY` | one of this or `opencode auth login` | OpenCode Zen's key; `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` for those providers |
| `OPENCODE_SERVER_USERNAME`, `OPENCODE_SERVER_PASSWORD` | optional | pin the Basic credential instead of minting one. Set the same two in `services/relay/.env` |
| `OPENCODE_AUTH_FILE` | optional | where the minted credential is kept (default `opencode-auth.env` here; the relay's `service.toml` points to the same file) |
| `OPENCODE_ENABLED` | optional | `0` makes `run.sh` exit without starting |
| `OPENCODE_PORT` | don't | `run.sh` sources `.env` after AIHub's environment, so a value here wins; keep it 4096 or leave it out |

This machine's `.env` also has `OPENCODE_ENDPOINT_NAME`, `OPENCODE_ALIAS`, `OPENCODE_MODELS` and `OPENCODE_MODEL`, copied from DashLLM. Nothing in this mod reads them; the first two belong in the relay's `.env`. Which model the `agent` alias runs is set on the relay's Endpoints view.

## Check it works

```bash
aihub check opencode
```

Expect `opencode: no failures, but 1 check skipped`: the health check is TCP (`tcp answered`), and `openapi` is skipped because every route needs the Basic credential.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4096/
```

Expect `401`: it's up and refuses callers without the credential.

```bash
opencode providers list
```

Lists the stored credentials (here: `OpenCode api`, `1 credentials`).

```bash
curl -s http://127.0.0.1:7000/api/s/relay/admin/endpoints
```

The `opencode` endpoint (`alias` `agent`, `protocol` `opencode`) with `health` `healthy` and its `available_models` (twelve free models here, 2026-10-21).

## What to look for

- **`opencode is not on PATH (looked in ~/.opencode/bin)`** in `aihub logs opencode`, exit 127: the binary isn't installed there.
- **`OPENCODE_PROJECT_DIR does not exist`**, exit 78: the folder in `.env` is gone.
- **The relay has no `agent` model.** It started before the credential existed, or `OPENCODE_SERVER_PASSWORD` differs between the two `.env` files. Restart the relay; if you pinned a password, set it in both.
- **It's a shell for whoever reaches it.** `opencode serve` runs commands in `OPENCODE_PROJECT_DIR` for every caller of the relay's `agent` model. That's why it's never served without the Basic credential and why the relay stays on `127.0.0.1`.
- **Only free models are served.** The relay drops OpenCode model ids without `free` in them, so a paid key isn't spent through the relay.
- OpenCode keeps its own state outside the project: `~/.local/share/opencode/` (sessions database, logs, snapshots, `auth.json`).

## Known gaps

- Nothing installs the `opencode` binary; the official install command isn't recorded in this repo. The version isn't pinned (`opencode upgrade` moves it).
- **Open question:** where `OPENCODE_PROJECT_DIR` should point. This machine's `.env` still points to the old DashLLM clone, `~/Tools/DashLLM`, outside the project.
