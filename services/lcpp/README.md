# lcpp: llama.cpp model launcher

lcpp runs any of the GGUF models in this directory as a llama.cpp server, on
any port you choose, from a command line (`lcpp`) or a web UI. Each server can
publish itself to the [DashLLM relay](https://github.com/brendondgr/Relay) and
remove itself again. A small background daemon (`lcppd`) does the work. It
starts at boot, loads no models, and sits idle (about 60 MB, 0% CPU) until you
ask for one.

Everything is bound to `127.0.0.1`. It is meant for this machine only.

```text
 lcpp CLI ─┐                                                 ┌─ DashLLM relay :4000
 browser  ─┴─▶ lcppd 127.0.0.1:7710 ── PUT/DELETE lcpp:<port> ─▶ /admin/registrations
               │                                             └─ /v1 ──▶ ┐
               └─ systemd-run ─▶ lcpp-<name>.service ─▶ llama-server :<port>
```

## Install

> **Under GAIFA** this is the `lcpp` mod: `gaifa install lcpp` makes its venv, and llama.cpp itself is unpacked by hand. Setup: [setup/llama-cpp.md](setup/llama-cpp.md). `scripts/install.sh` below is the old standalone installer.

```bash
scripts/install.sh
```

The script is idempotent. It does four things:

1. Syncs the venv.
2. Installs the `lcpp` command to `~/.local/bin`.
3. Installs and starts `lcpp.service` as a systemd user unit. Linger is on, so it starts at boot.
4. Removes the old `llamacpp-*` commands and `llamacpp-router.service`.

## Use

```bash
lcpp status                               # what is running (bare `lcpp` does this too)
lcpp models                               # the catalog; --discovered for GGUFs not in it yet
lcpp start minicpm --port 7072            # waits until ready, prints the URL
lcpp start gemma4-26B -c 32768 -s parallel=2 --alias g26
lcpp start --router --port 7070           # router mode: every model, loaded on demand
lcpp start ornith --dry-run               # preflight + memory estimate + exact command
lcpp logs 7072 -f                         # targets are instance names or ports
lcpp chat 7072 "hello" --no-think         # one prompt, with ttft and tok/s
lcpp relay add 7072 --alias mini          # publish / `relay remove` / `relay cleanup`
lcpp restart 7072
lcpp stop 7072 | lcpp stop all
lcpp service status|restart|logs          # the daemon itself
lcpp doctor                               # check binary, models, service, relay
lcpp ui                                   # open http://127.0.0.1:7710
```

The web UI (`http://127.0.0.1:7710`) does the same things. It has five views:

- **Instances:** launch with a live port check and memory estimate; stop, restart and view logs.
- **Models:** edit the catalog, add discovered GGUFs, and download GGUFs from Hugging Face.
- **Playground:** chat directly or through the relay, with metrics.
- **Relay:** registrations and orphans.
- **Settings:** the options in `data/lcpp.json`.

## How it behaves

- **Nothing runs at boot.** Each instance is a transient systemd user unit
  (`lcpp-<name>.service`). Units and runtime state
  (`$XDG_RUNTIME_DIR/lcpp`) do not survive a reboot.
- **Daemon restarts are harmless.** Instances are not children of the daemon.
  A restarted daemon finds them again, and relay registrations stay put.
- **Relay publishing is automatic.** This is set by `relay.auto_register`;
  override it per launch with `--no-relay`.
  - An instance registers as `lcpp:<port>` once it is ready, and is removed
    when it stops. If the relay is down, the registration waits as `pending`
    and is retried.
  - A dedicated instance takes its model's name from a router.
  - The relay's old hand-added `llama.cpp · local` endpoint on `:7070` was
    adopted by the lcpp router there. It keeps its id, alias and history.
- **Memory is measured, not guessed.** An instance's footprint includes the
  GPU memory (GTT + VRAM) its process tree holds, which on unified memory is
  most of it. Launch estimates read KV-cache geometry from the GGUF header.

## Layout

| Path | What |
| --- | --- |
| `models/` | GGUF weights, one folder per model (gitignored `*.gguf`) |
| `data/lcpp.json` | daemon, llama.cpp, port range, relay and scan-dir settings |
| `data/models.json` | model defaults + catalog (paths, nicknames, mmproj/draft sidecars, per-model params) |
| `data/generated/` | rendered router presets (gitignored) |
| `runtime/llama.cpp/` | llama.cpp binaries: `bin/current → llama-bNNNN` (gitignored) |
| `web/` | the UI, static with no build step (Claude Design handoff; see `web/README.md`) |
| `src/lcpp/` | daemon (`daemon/`), supervisor, backends, catalog, relay registrar, CLI |
| `src/tests/` | pytest suite: fake llama-server, fake relay; no GPU or systemd needed |
| `deploy/systemd/lcpp.service` | unit template installed by `lcpp service install` |
| `utils/` | live checks: `smoke_supervisor.py`, `measure_idle.sh`, `e2e_live.sh`, `ui_smoke.md` |
| `docs/api.md` | the HTTP API; `docs/plans/` has the plan and the UI brief |

Models outside `models/` (e.g. `~/Models/Nemotron3Super/`) work by absolute
or `~/` path. Discovery scans `scan_dirs`, which is `models/` and `~/Models`
here.

### Adding a model

**From Hugging Face:** open **Models → Add model → Hugging Face**. Enter one of:

- a repo id, e.g. `unsloth/gemma-4-E4B-it-GGUF`
- a link to one file, e.g. `https://huggingface.co/<repo>/resolve/main/<file>.gguf?download=true`

A repo lists its quants (split parts grouped) and its `mmproj`/`mtp` sidecars
to pick from. A link selects its file. The download goes to
`models/<folder>/`, is checked against the Hub's sha256, and is added to the
catalog. Gated or private repos use the token from `hf auth login`.

llama-server runs only GGUF. A repo with only safetensors, AWQ or GPTQ
weights (e.g. `openbmb/MiniCPM5-1B`) is reported as such, with a link to
search for a GGUF conversion.

**By hand:** put the GGUF in `models/<Name>/`. Then either use
**Models → Discovered → Add to catalog** in the UI, or add an entry to
`data/models.json`:

```json
"my-model": {
  "nicknames": ["mymodel"],
  "path": "models/MyModel/MyModel-Q4_K_M.gguf",
  "mmproj": "models/MyModel/mmproj.gguf",
  "draft": "models/MyModel/mtp.gguf", "spec_type": "draft-mtp",
  "params": {"ctx-size": 65536}
}
```

`params` are llama-server flags without the dashes. `true`/`false` map to
`on`/`off` or `--x`/`--no-x` as the flag expects. Precedence, from lowest to
highest:

1. `llama.server_params`
2. `defaults`
3. per-model `params`
4. per-launch overrides

## Develop

```bash
make test         # 81 tests, ~20 s
make dev          # throwaway daemon on :7790 running instances as child processes
make smoke        # real llama-server under systemd (MiniCPM on :7071)
make idle-check   # startup time, RSS, idle CPU
utils/e2e_live.sh # everything, against the real daemon and relay
```
