# The hub

The hub is the FastAPI app on `127.0.0.1:7000` that starts the mods, proxies their APIs, keeps the models registry and serves the UI. It needs no GPU, and it's the one part you can install on any Linux machine with systemd.

Do [the host](host.md) first.

## Tested with

Python 3.12+ (uv's managed CPython; the hub's venv is `.venv/`), uv 0.12.23, FastAPI, uvicorn, httpx, pydantic 2 (the versions are in `uv.lock`), systemd 259 user services, Fedora 44.

## Install

```bash
git clone https://github.com/brendondgr/AIHub.git ~/AIHub
```

```bash
cd ~/AIHub && uv sync
```

```bash
bin/aihub install
```

`uv sync` makes `.venv/` from `uv.lock` (about 100 MB; it downloads Python 3.12+ if you don't have it). `bin/aihub install` then:

1. writes `~/.config/systemd/user/aihub.service` from `bin/aihub.service.in`, with this clone's path filled in;
2. links `~/.local/bin/aihub` to `bin/aihub`, so `aihub` works from anywhere (make sure `~/.local/bin` is on your `PATH`);
3. enables and starts the unit, waits for the hub to answer, and prints `AIHub is up at http://127.0.0.1:7000/`;
4. warns if lingering is off (see [host §4](host.md#4-keep-your-services-running)).

Open <http://127.0.0.1:7000>. The Overview lists the mods it found in `services/`; none of them are installed yet.

## Check it works

```bash
aihub doctor
```

On a fresh clone with no mods installed, expect the first five lines `ok`:

```
ok   hub venv      …/.venv/bin/python
ok   config.toml   parses
ok   systemd unit  ~/.config/systemd/user/aihub.service
ok   linger        on
ok   hub           0.1.0 pid … at http://127.0.0.1:7000
```

followed by the checks over every mod and model (`aihub doctor -v` lists the ones that passed). What each area means:

| Area | Checks | A problem means |
|---|---|---|
| `models` | every registered model's files are on disk, whole, and match their recorded hashes | a model you haven't downloaded (expected until you do), a partial download, or a file that changed |
| `manifests` | each `services/<id>/service.toml` parses, with no clashes between mods | a mod folder with a broken manifest |
| `paths` | no mod's command, folder or environment points outside the project, except the allowlist (`/usr`, `~/.config/tts-engines`, `~/.local/bin` tools, podman images) | a `.env` or setting that points elsewhere (a warning, not a failure) |
| `ports` | each mod's port is free or held by that mod | another program on a mod's port |
| `units` | no mod is failed or degraded; enabled autostart mods are running | a mod that crashed: `aihub logs <id>` |
| `disk` | enough free space on the project's disk | — |
| `offline` | mods that run with `HF_HUB_OFFLINE=1` have their models | a mod that will fail to load until its models are downloaded |

`aihub doctor` doesn't check a mod's own environment (its venv, container image or runtime). Each environment doc gives its own check.

## Configuration

`config.toml` at the root holds the hub's settings; the Settings page edits it and keeps its comments. The defaults work. The ones you may change on a new machine:

| Setting | Default | Change it when |
|---|---|---|
| `memory.reserve_gb` | `12` | you run without a desktop (lower) or with heavy apps open (higher) |
| `memory.auto_make_room` | `false` | you'd rather the hub unload idle mods without asking |
| `services.<id>.autostart` | per mod | a mod you haven't installed shouldn't start with the hub |

Paths (`paths.models`, `paths.databases`, `paths.outputs`) must stay inside the project folder.

## Installing the mods

`aihub install <id>` runs that mod's own installer (`[run] install` in its `service.toml`, by default `install.sh`) in its folder. That's all it does: it doesn't pull container images, build GPU runtimes or download models. Those are in each environment's doc, in this order:

| Order | Mod | Environment docs | Needs a GPU |
|---|---|---|---|
| 1 | `relay` (LLM Relay) | [relay](../../services/relay/setup/relay.md) | no |
| 2 | `opencode` (optional) | [opencode](../../services/opencode/setup/opencode.md) | no |
| 3 | `lcpp` (LLM Launcher) | [llama.cpp](../../services/lcpp/setup/llama-cpp.md) | yes (Vulkan) |
| 4 | `vllm` | [vLLM](../../services/vllm/setup/vllm.md) | yes |
| 5 | `agent` (Chat) | [agent](../../services/agent/setup/agent.md) | no, but it needs an LLM from 3, 4 or a remote one |
| 6 | `comfy` (Images & Video) | [ComfyUI](../../services/comfy/setup/comfyui.md) | yes |
| 7 | `tts` (Speech) | [Kokoro](../../services/tts/setup/kokoro.md), [Breeze TTS 2](../../services/tts/setup/breeze.md) | yes |
| 8 | `gen3d` (3D Generate) | [CubeArt](../../services/gen3d/setup/cubeart.md), [Hunyuan3D 2.1](../../services/gen3d/setup/img3d.md), [SAM 3D Objects](../../services/gen3d/setup/sam3do.md) | yes; two of its engines run in ComfyUI (6) |
| 9 | `web` (Web search) | [web](../../services/web/setup/web.md) (SearXNG runs outside AIHub) | no |
| 10 | `stt` (Speech to Text) | [faster-whisper](../../services/stt/setup/stt.md) | no; much faster with one |

The relay comes first because the LLM mods publish themselves to it and the agent talks to models through it. ComfyUI comes before 3D Generate because TRELLIS.2 and SAM 3D Body run as ComfyUI workflows. Skip any mod you don't want: set `services.<id>.autostart = false` and it stays stopped.

After each one:

```bash
aihub start <id>
```

```bash
aihub check <id>
```

`aihub check` passes when the mod's health route answers and its manifest, status and tools are valid.

## What to look for

- **`aihub: …/.venv/bin/python is missing; run uv sync`.** The CLI found no hub venv; run `uv sync` in the clone.
- **`aihub: ~/.local/bin/aihub exists and points elsewhere`.** Another clone is installed. `aihub uninstall` there first, or remove the link.
- **The hub stops when you log out.** Lingering is off.
- **Changed hub code doesn't show.** The service runs the venv's Python directly; `aihub restart` after every change.
- **The hub refuses to start with a non-loopback `hub.host`.** By design: AIHub has no authentication and listens only on `127.0.0.1`.
- **Never run `git clean -x` or `git clean -X` in the clone.** Ignored files include every model weight, venv and runtime.

Next: the mods, in the order above. Each model you download has its own doc in [models/](models/).
