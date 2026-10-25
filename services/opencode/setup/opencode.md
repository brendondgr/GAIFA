<!-- gaifa-setup
id = "opencode"
title = "OpenCode"
models = []
scan = []
summary = "OpenCode: a coding agent behind the relay's agent model, plus OpenCode Zen's free hosted models"
gpu = false
disk_gb = 0.2
needs = ["curl", "tar"]
after = []
check = "gaifa check opencode --start"

[[steps]]
run = '[ -x "$HOME/.opencode/bin/opencode" ] || curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path'
what = "OpenCode's official installer: the newest 1.x release, one binary of about 170 MB, into ~/.opencode/bin/ (no root; --no-modify-path leaves ~/.bashrc alone); skipped when it's there"

[[steps]]
run = 'PATH="$HOME/.opencode/bin:$PATH" opencode auth login'
skip_if = '[ -s "$HOME/.local/share/opencode/auth.json" ] || grep -qs "^OPENCODE_API_KEY=." .env'
what = "logs OpenCode in to a provider (OpenCode Zen or another): it asks which and for the key, stored in ~/.local/share/opencode/auth.json; skipped when you're logged in or this folder's .env sets OPENCODE_API_KEY"
interactive = true

[[steps]]
run = 'set -a; [ -f .env ] && . ./.env; set +a; ROOT="$PWD"; . ./auth.sh'
what = "mints the Basic credential in opencode-auth.env (what the first start does; kept when it's there), so the relay can register the agent endpoint; opencode serve itself starts once its folder is set, the question after install"

[[steps]]
run = '''if [ -x ../relay/web/backend/.venv/bin/python ]; then gaifa restart relay; else echo "the relay is not installed yet; its own setup starts it with this credential"; fi'''
what = "restarts the relay (starting it if it's stopped), so it registers the agent endpoint with the new credential; skipped when the relay isn't installed yet"

[[config]]
key = "services.opencode.env.OPENCODE_PROJECT_DIR"
text = "Which folder should OpenCode work in? Its shell, edit and write tools act there, for every caller of the relay's agent model: a folder you choose, outside GAIFA (a git checkout you can review), created if it's missing. run.sh refuses to start without one, or with one inside GAIFA."
choices = "folder"
required = true
restart = "opencode relay"

[[variants]]                    # plan 39.1: no GPU work, so one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# OpenCode: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `opencode` mod runs `opencode serve` on `127.0.0.1:4096`. It's the upstream behind the relay's `agent` model, and it gives the relay OpenCode Zen's free hosted models (`opencode/…-free`). The mod is only a manifest and two scripts: `run.sh` sources `.env`, loads or mints the HTTP Basic credential (`auth.sh`) and runs `opencode serve` in `OPENCODE_PROJECT_DIR`, a folder you choose outside GAIFA (it refuses to start without one). The `opencode` binary itself is installed outside GAIFA, in `~/.opencode/bin` (allowed by plan Phase 12.4), by OpenCode's own installer. The mod is optional: nothing else in GAIFA needs it.

## Tested with

Read from this machine on 2026-10-21:

| Part | Version |
|---|---|
| `opencode` | 1.17.13, `~/.opencode/bin/opencode` (a single 168 MB binary) |
| `@opencode-ai/plugin` | 1.17.13 (`~/.opencode/package.json`) |
| Credentials | `~/.local/share/opencode/auth.json`: one, provider OpenCode, type api |

## Prerequisites

- [The hub](../../../docs/setup/hub.md). No GPU, no models. `curl` and `tar` for OpenCode's installer.
- An OpenCode Zen API key, or a key for another provider OpenCode supports ([host.md §6](../../../docs/setup/host.md#6-accounts-and-licences)).
- Install it before the [relay](../../relay/setup/relay.md) starts, or restart the relay afterwards: the relay looks for the credential only at start.

## Install

Install OpenCode with its official installer ([opencode.ai/docs](https://opencode.ai/docs/)):

```bash
curl -fsSL https://opencode.ai/install | bash
```

It needs `curl` and `tar`, no root. It downloads the newest 1.x release (one binary, about 170 MB) into `~/.opencode/bin/` and, unless you pass `--no-modify-path` (as `gaifa setup` does: `curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path`), adds that folder to `PATH` in your shell's rc file (`~/.bashrc` here). `--version <1.x version>` installs a given release (this machine runs the one in Tested with). `run.sh` adds `~/.opencode/bin` to `PATH` itself, since a systemd unit doesn't read `~/.bashrc`; without the rc change, run it as `~/.opencode/bin/opencode` in your shell.

Give OpenCode a provider key, either once interactively (it asks which provider, then the key; `gaifa setup` hands this step to you):

```bash
~/.opencode/bin/opencode auth login
```

(`auth` is an alias of `opencode providers`; the key goes to `~/.local/share/opencode/auth.json`), or as `OPENCODE_API_KEY` in this folder's `.env` (below). `gaifa setup` skips this step when either is there (its `skip_if`).

There's no `gaifa install opencode` step: the mod has no venv. Choose its folder (Configuration: `OPENCODE_PROJECT_DIR`, which `gaifa setup` asks for after install), then start it:

```bash
gaifa start opencode
```

On its first start `auth.sh` writes `opencode-auth.env` in this folder (gitignored, mode 600) with `OPENCODE_SERVER_USERNAME=opencode` and a random password (24 random bytes in base64, letters and digits only: up to 32 characters). Every later start reuses it; delete the file to rotate it. (`gaifa setup` mints it earlier, without starting the mod, by sourcing `auth.sh` from the block's third step, since the folder is asked for only after install.) Then restart the relay so it registers the `agent` endpoint with that credential (it publishes the endpoint's models once OpenCode answers):

```bash
gaifa restart relay
```

## Choosing models

The mod downloads no model, so it has no suggestions. OpenCode calls hosted providers: with an OpenCode Zen key, the relay serves its free models (`opencode/…-free`) and the `agent` alias; the relay drops paid ids. Which model `agent` runs is set on the relay's Endpoints view. Local models belong to [llama.cpp](../../lcpp/setup/llama-cpp.md) or [vLLM](../../vllm/setup/vllm.md).

## Configuration

`service.toml` `[run.env]` sets `OPENCODE_PORT = "{port}"` (4096). `OPENCODE_PROJECT_DIR` is required; `gaifa setup` saves it through the hub, which writes it to `config.toml` (`[services.opencode.env]`) and applies it at once. Everything else is optional, in `.env` here (gitignored; start from `.env.example`), and a line in `.env` wins over `config.toml`, since `run.sh` sources it after GAIFA's environment:

| Key | Required | Meaning |
|---|---|---|
| `OPENCODE_PROJECT_DIR` | yes | the folder OpenCode's bash, edit and write tools act in: an absolute path outside GAIFA. Unset or inside GAIFA, `run.sh` refuses to start (see below) |
| `OPENCODE_API_KEY` | one of this or `opencode auth login` | OpenCode Zen's key; `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` for those providers |
| `OPENCODE_SERVER_USERNAME`, `OPENCODE_SERVER_PASSWORD` | optional | pin the Basic credential instead of minting one. Set the same two in `services/relay/.env` |
| `OPENCODE_AUTH_FILE` | optional | where the minted credential is kept (default `opencode-auth.env` here; the relay's `service.toml` points to the same file) |
| `OPENCODE_ENABLED` | optional | `0` makes `run.sh` exit without starting |
| `OPENCODE_PORT` | don't | `run.sh` sources `.env` after GAIFA's environment, so a value here wins; keep it 4096 or leave it out |

**Set `OPENCODE_PROJECT_DIR` to a folder you choose, outside GAIFA.** `gaifa setup` asks for it (an absolute folder outside GAIFA, created if missing), saves it through the hub (into `config.toml`, applied at once), restarts the mod, then restarts the relay so it finds OpenCode Zen's free models (it looks for them only for a while after its own start). `run.sh` refuses to start when it's unset or resolves inside the GAIFA folder (exit 1, with how to set it): the agent's shell, edit and write tools would start inside GAIFA, which the rest of GAIFA keeps read-only. By hand, pick (or make) the project you want the `agent` model to work on, for example:

```bash
mkdir -p ~/Projects/agent-work
```

```bash
cp -n services/opencode/.env.example services/opencode/.env
```

Then set the line in `services/opencode/.env` to that folder's absolute path (no `~` and no `$HOME`: the file takes plain `KEY=value`), such as `OPENCODE_PROJECT_DIR=/home/you/Projects/agent-work` (`run.sh` reads `.env` on every start). Or put `OPENCODE_PROJECT_DIR = "…"` under `[services.opencode.env]` in `config.toml`; the hub reads that file only when it starts, so run `gaifa restart` first. Then restart the mod, and the relay so it finds OpenCode Zen's free models:

```bash
gaifa restart opencode && gaifa restart relay
```

`gaifa logs opencode` then prints `opencode serve --port 4096 in /home/you/Projects/agent-work`. A folder that doesn't exist stops the mod (exit 78, What to look for). It's not a sandbox: OpenCode runs as you, so give it a folder whose changes you can review or undo (a git checkout). One server works in one folder; to switch projects, change the line and restart.

This machine's `.env` also has `OPENCODE_ENDPOINT_NAME`, `OPENCODE_ALIAS`, `OPENCODE_MODELS` and `OPENCODE_MODEL`, copied from DashLLM. Nothing in this mod reads them; the first two belong in the relay's `.env`. Which model the `agent` alias runs is set on the relay's Endpoints view.

## Check it works

```bash
gaifa check opencode --start
```

Starts the mod if it's stopped (a stopped mod's live checks are skipped), then checks it. Expect `opencode: no failures, but 1 check skipped`: the health check is TCP (`tcp answered`), and `openapi` is skipped because every route needs the Basic credential.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4096/
```

Expect `401`: it's up and refuses callers without the credential.

```bash
~/.opencode/bin/opencode providers list
```

Lists the stored credentials (here: `OpenCode api`, `1 credentials`).

```bash
curl -s http://127.0.0.1:7000/api/s/relay/admin/endpoints
```

The `opencode` endpoint (`alias` `agent`, `protocol` `opencode`) with `health` `healthy` and its `available_models` (twelve free models here, 2026-10-21).

## What to look for

- **`opencode is not on PATH (looked in ~/.opencode/bin)`** in `gaifa logs opencode`, exit 127: the binary isn't installed there.
- **`OPENCODE_PROJECT_DIR is not set`** or **`OPENCODE_PROJECT_DIR is inside GAIFA`**, exit 1: choose a folder outside GAIFA (`gaifa setup opencode` asks again, or Configuration), then `gaifa restart opencode`.
- **`OPENCODE_PROJECT_DIR does not exist`**, exit 78: the folder in `.env` or `config.toml` is gone.
- **The relay has no `agent` model.** It started before the credential existed, or `OPENCODE_SERVER_PASSWORD` differs between the two `.env` files. Restart the relay; if you pinned a password, set it in both.
- **It's a shell for whoever reaches it.** `opencode serve` runs commands in `OPENCODE_PROJECT_DIR` for every caller of the relay's `agent` model. That's why it's never served without the Basic credential and why the relay stays on `127.0.0.1`.
- **Only free models are served.** The relay drops OpenCode model ids without `free` in them, so a paid key isn't spent through the relay.
- OpenCode keeps its own state outside the project: `~/.local/share/opencode/` (sessions database, logs, snapshots, `auth.json`).

## Known gaps

- The version isn't pinned: the installer takes the newest 1.x, and `opencode upgrade` moves it.
- This machine's `.env` still points `OPENCODE_PROJECT_DIR` at the old DashLLM clone, `~/Tools/DashLLM`; which project it should be here is the user's choice.
