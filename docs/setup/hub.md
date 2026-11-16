# The hub

The hub is the FastAPI app on `127.0.0.1:7000` that starts the mods, proxies their APIs, keeps the models registry and serves the UI. It needs no GPU, and it's the one part you can install on any Linux machine; with systemd it runs as a user service, and on WSL2 and macOS as described below.

Do [the host](host.md) first.

## Tested with

Python 3.12+ (uv's managed CPython; the hub's venv is `.venv/`), uv 0.12.23, FastAPI, uvicorn, httpx, pydantic 2 (the versions are in `uv.lock`), systemd 259 user services, Fedora 44.

## Install

```bash
git clone --recurse-submodules https://github.com/brendondgr/GAIFA.git ~/GAIFA
```

`relay`, `lcpp`, `tts` and `gen3d` are git submodules of their own repositories; without `--recurse-submodules` their folders are empty, and `gaifa setup <id>` checks out the ones you pick (the private two, LLMs and 3DGenerate, need an SSH key with access). `gaifa repos` shows them and keeps them up to date ([mods.md §10](../mods.md#10-mods-with-their-own-repository)).

```bash
cd ~/GAIFA && uv sync
```

```bash
bin/gaifa install
```

`uv sync` makes `.venv/` from `uv.lock` (about 100 MB; it downloads Python 3.12+ if you don't have it). `bin/gaifa install` then:

1. writes `~/.config/systemd/user/gaifa.service` from `bin/gaifa.service.in`, with this clone's path filled in;
2. links `~/.local/bin/gaifa` to `bin/gaifa`, so `gaifa` works from anywhere (make sure `~/.local/bin` is on your `PATH`);
3. enables and starts the unit, waits for the hub to answer, and prints `GAIFA is up at http://127.0.0.1:7000/`;
4. warns if lingering is off (see [host §4](host.md#4-keep-your-services-running)).

Open <http://127.0.0.1:7000>. The Overview lists the mods it found in `services/`; none of them are installed yet.

**On other systems** (plan 37.2):
- **WSL2 (Windows):** the same, once WSL runs systemd. If it doesn't, `gaifa install` prints the fix: `[boot] systemd=true` in `/etc/wsl.conf`, then `wsl --shutdown` in Windows. The Windows browser reaches the hub at <http://127.0.0.1:7000> through WSL's localhost forwarding, and `gaifa open` opens it there.
- **macOS:** `gaifa install` writes the launchd agent to `data/state/hub/com.gaifa.hub.plist`. It then prints the commands that copy it to `~/Library/LaunchAgents/` and load it, so GAIFA runs at login; nothing outside the project is written for you.
- **Without systemd:** `gaifa start`, `stop` and `status` run the hub in the background with a pidfile (`data/state/hub/gaifa.json`, its output in `gaifa.out`). Mods then run detached and outlive it (`[hub] backend = "auto"`, plan 37.1).
- **Logs:** `gaifa logs [-f]` reads `data/logs/` the same way everywhere.

## Check it works

```bash
gaifa doctor
```

On a fresh clone with no mods installed, expect the first five lines `ok`:

```
ok   hub venv      …/.venv/bin/python
ok   config.toml   parses
ok   systemd unit  ~/.config/systemd/user/gaifa.service
ok   linger        on
ok   hub           0.1.0 pid … at http://127.0.0.1:7000
```

followed by the checks over every mod and model (`gaifa doctor -v` lists the ones that passed). What each area means:

| Area | Checks | A problem means |
|---|---|---|
| `models` | every registered model's files are on disk, whole, and match their recorded hashes | a model you haven't downloaded (expected until you do), a partial download, or a file that changed |
| `manifests` | each `services/<id>/service.toml` parses, with no clashes between mods | a mod folder with a broken manifest |
| `paths` | no mod's command, folder or environment points outside the project, except the allowlist (`/usr`, `~/.config/tts-engines`, `~/.local/bin` tools, podman images) | a `.env` or setting that points elsewhere (a warning, not a failure) |
| `ports` | each mod's port is free or held by that mod | another program on a mod's port |
| `units` | no mod is failed or degraded; enabled autostart mods are running | a mod that crashed: `gaifa logs <id>` |
| `disk` | enough free space on the project's disk | — |
| `offline` | mods that run with `HF_HUB_OFFLINE=1` have their models | a mod that will fail to load until its models are downloaded |

`gaifa doctor` doesn't check a mod's own environment (its venv, container image or runtime). Each environment doc gives its own check.

## Configuration

`config.toml` at the root holds the hub's settings. It's yours and not in git: the first `gaifa` command copies it from `config.example.toml`, the defaults every clone starts from. The Settings page edits it and keeps its comments. The defaults work. The ones you may change on a new machine:

| Setting | Default | Change it when |
|---|---|---|
| `memory.reserve_gb` | `12` | you run without a desktop (lower) or with heavy apps open (higher) |
| `memory.auto_make_room` | `false` | you'd rather the hub unload idle mods without asking |
| `services.<id>.autostart` | per mod | a mod you've installed shouldn't start with the hub (one that isn't installed yet never autostarts) |

Paths (`paths.models`, `paths.databases`, `paths.outputs`) must stay inside the project folder.

## Installing the mods

`gaifa install <id>` runs that mod's own installer (`[run] install` in its `service.toml`, by default `install.sh`) in its folder. That's all it does: it doesn't pull container images, build GPU runtimes or download models. Those are in each environment's doc, in this order:

| Order | Mod | Environment docs | Needs a GPU |
|---|---|---|---|
| 1 | `relay` (LLM Relay) | [relay](../../services/relay/setup/relay.md) | no |
| 2 | `opencode` (optional) | [opencode](../../services/opencode/setup/opencode.md) | no |
| 3 | `lcpp` (LLM Launcher) | [llama.cpp](../../services/lcpp/setup/llama-cpp.md) | yes (Vulkan) |
| 4 | `vllm` | [vLLM](../../services/vllm/setup/vllm.md) | yes |
| 5 | `agent` (Chat) | [agent](../../services/agent/setup/agent.md) | no, but it needs an LLM from 3, 4 or a remote one |
| 6 | `comfy` (Images & Video) | [ComfyUI](../../services/comfy/setup/comfyui.md) | yes |
| 7 | `tts` (Speech) | [Kokoro](../../services/tts/setup/kokoro.md), [Breeze TTS 2](../../services/tts/setup/breeze.md) | yes |
| 8 | `gen3d` (3D Generate) | [the base](../../services/gen3d/setup/gen3d.md) (the server, the image, every engine's runtime), then the engines: [CubeArt](../../services/gen3d/setup/cubeart.md), [Hunyuan3D 2.1](../../services/gen3d/setup/img3d.md), [SAM 3D Objects](../../services/gen3d/setup/sam3do.md) | yes; two of its engines run in ComfyUI (6) |
| 9 | `searxng` (search: your SearXNG, or GAIFA's own in a container) | [searxng](../../services/searxng/setup/searxng.md) | no |
| 10 | `web` (Web: pages and search) | [web](../../services/web/setup/web.md) | no |
| 11 | `stt` (Speech to Text) | [faster-whisper](../../services/stt/setup/stt.md) | no; much faster with one |
| 12 | `workspace` (your folders, the sandbox) | [workspace](../../services/workspace/setup/workspace.md) | no; the sandbox needs podman |
| 13 | `decide` (decisions: the Auto judge) | [decide](../../services/decide/setup/decide.md) | no; quicker with one |
| 14 | `embed` (search by meaning) | [embed](../../services/embed/setup/embed.md) | no; quicker with one |
| 15 | `mcp` (other MCP servers' tools) | [mcp](../../services/mcp/setup/mcp.md), [Blender](../../services/mcp/setup/blender.md) | no |
| 16 | `calendar` | [calendar](../../services/calendar/setup/linux.md) | no |
| 17 | `voice` (voice mode on a speech-to-speech model) | [llama.cpp](../../services/voice/setup/llama-cpp.md) | yes |

Mods 1 (the relay), 9, 10 and 12–16 are the set recommended for chat (`gaifa setup --recommended`; [turning-things-on.md](../turning-things-on.md) says what each gives and what its state means).

The relay comes first because the LLM mods publish themselves to it and the agent talks to models through it. ComfyUI comes before 3D Generate because TRELLIS.2 and SAM 3D Body run as ComfyUI workflows, and its setup pulls the image both use. The setup docs say so in their blocks (`after`: `lcpp`, `vllm` and `agent` after `relay`, 3D Generate's base after `comfyui` and each of its engines after the base), so `gaifa setup <ids>` puts them in this order and sets up what a choice needs. Skip any mod you don't want: a mod that isn't installed yet (its command doesn't exist) isn't autostarted, and the hub shows it as "not installed: run gaifa setup <id>" (plan 23.12).

After each one:

```bash
gaifa check <id> --start
```

`--start` starts the mod first if it's stopped; then `gaifa check` checks its manifest, command, port and page module, and, with the mod running, its health route, status, widgets and tools. **A stopped mod's live checks are skipped**, not failed (`no failures, but N checks skipped`), so a plain `gaifa check <id>` on a stopped mod proves little; the setup docs' checks all use `--start`.

## What to look for

- **`gaifa: …/.venv/bin/python is missing; run uv sync`.** The CLI found no hub venv; run `uv sync` in the clone.
- **`gaifa: ~/.local/bin/gaifa exists and points elsewhere`.** Another clone is installed. `gaifa uninstall` there first, or remove the link.
- **The hub stops when you log out.** Lingering is off.
- **Changed hub code doesn't show.** The service runs the venv's Python directly; `gaifa restart` after every change.
- **The hub refuses to start with a non-loopback `hub.host`.** By design: GAIFA has no authentication and listens only on `127.0.0.1`.
- **Never run `git clean -x` or `git clean -X` in the clone.** Ignored files include every model weight, venv and runtime.

Next: the mods you want, in the order above. Each mod's setup doc says which models it can run; the choice is yours.
