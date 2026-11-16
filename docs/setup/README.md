# Setting up GAIFA

How to install GAIFA on a new machine: the host, the hub, then **the mods you want**, each with the models **you** choose for it. It's written for the hardware GAIFA is built on: an **AMD Strix Halo** (Ryzen AI MAX+ 395, Radeon 8060S, `gfx1151`) with 128 GB of unified memory, on **Fedora Linux**. Everything in the repository (the container images, the PyTorch wheels, the engines' settings) is built and tuned for that chip, so on that hardware these docs should be all you need.

**Other hardware.** GAIFA was built on Linux with an AMD Strix Halo, and runs elsewhere through each mod's variants (plan 38): `bin/gaifa hardware` shows what your machine has, and the setup picks the variant that fits, says which ones haven't been tested on that kind of machine, and lists the mods it can't run. Windows works through WSL2; macOS is untested (CI was turned off on 2026-10-22). What runs where: [platforms.md](../platforms.md); the host for your machine: the table below.

## The quick way

```bash
bin/gaifa setup
```

From a fresh clone, that's the whole process, in this order: choosing mods from a list; the host checks (any fix that needs `sudo` is printed for you to run, never run for you); the plan, with every step, size and question; your answers (licences, which models); the hub; install; the models you chose; the agent's model, from your relay's; each mod's check; a report. Run it again after a stop: it resumes. `--plan` shows the plan without installing anything (it does check out the chosen mods that are submodules, since their setup docs are inside them); `bin/gaifa setup relay agent` sets up only those (and what they need).

**Your hardware decides each mod's variant** (plan 38.2). `gaifa hardware` shows what GAIFA finds: the GPUs and the accelerators it can use (ROCm, CUDA, Intel XPU, Apple MPS, Vulkan, CPU). For each mod, the plan names the variant it will install, and marks it when it hasn't been tested on this kind of machine. A mod your machine can't run is listed as not available, with the reason. `--accel <mod>=cpu` (or another accel) picks a different variant, and `--smoke` runs each mod's smoke after the checks: real work that proves the GPU path.

**Having an agent do it.** An AI agent follows the same process for you: it reads the plan (`bin/gaifa setup --plan --json <mods>`), asks you the same questions, passes your answers (`--answers <file>`, or `--accept`, `--decline`, `--models`, `--set`), hands you any `sudo` command and any step that prompts (a login), and reads one JSON report. `bin/gaifa setup --help` lists the exit codes and the report's shape; agents in this repo have the `gaifa-setup` skill. The rest of this guide is what the wizard reads, for when you want to know what it does or do a step by hand.

**Testing on another machine** (plan 40.3). To find out what breaks on a new kind of machine, run the setup with `--smoke` and keep notes as you go: `gaifa report note "what happened" --setup <id> --cmd "<command>" --output <file> --tried "<what you tried>"`. Then `gaifa report` writes `data/state/reports/<date>-<host>.md`: the machine (with a recording that replays its detection), the commit and any local changes, the host checks, the setup run with its variants, each failure with the setup doc line, the command, its log and a likely cause, the mods, the doctor. Hand that file to whoever fixes GAIFA. Agents in this repo do all of it with the `gaifa-field-test` skill.

## The order

| Step | Doc | Time | Disk |
|---|---|---|---|
| 1. The machine | [host.md](host.md) (Linux with AMD), or [NVIDIA](host-linux-nvidia.md), [Intel](host-linux-intel.md), [WSL2](host-wsl2.md), [macOS](host-macos.md): drivers, groups, packages, accounts | 30 min and a reboot | — |
| 2. The hub | [hub.md](hub.md): clone, `uv sync`, `gaifa install`, `gaifa doctor` | 5 min | 100 MB |
| 3. The mods you want | their setup docs (below), in the order in [hub.md](hub.md#installing-the-mods) | 10 min to an hour each | up to about 22 GB each (images, runtimes, containers; the ComfyUI image, 15.1 GB, is shared by Images & Video and 3D Generate and counted once) |
| 4. Their models | each mod's setup doc: what kind of model it runs, a few optional suggestions, how to add your own | the downloads | from nothing to hundreds of GB: your choice |

Pick only the mods you need; each setup doc says what the mod gives you and what it needs. GAIFA doesn't come with a model list to copy: the models are yours to choose, per mod.

## Opening GAIFA to your other devices

GAIFA answers only the machine it runs on until you open it to your network (plan lan-access): then a phone or laptop on the same Wi-Fi or wired network opens it by this machine's address and signs in with a password. It's off by default.

1. `bin/gaifa lan on` asks for the password (at least 12 characters), turns it on, restarts GAIFA and prints the address to open (and `<name>.local`, when your network resolves it). Settings → General → Network does the same.
2. The firewall usually blocks the port: `gaifa lan on` prints the command for yours (Fedora's: `sudo firewall-cmd --permanent --add-port=7000/tcp --add-port=7443/tcp && sudo firewall-cmd --reload`). Run it yourself; GAIFA never runs `sudo`.
3. On the other device, open the address and sign in. Voice mode and dictation need HTTPS there (`https://<address>:7443`); its browser warns once about GAIFA's own certificate unless you trust it (`/lan/trust` on that device has the steps).

Only addresses on this machine's own network get in (a VPN such as Tailscale only when `[hub.lan] allow` names it), never the internet. Bypass, folder levels, the hub's settings and these network settings stay on this machine. `gaifa lan devices` lists who is signed in, `gaifa lan signout --all` signs everyone out, and `gaifa lan off` closes it again.

## How these docs work

- **Environment docs** live in the mod they belong to, `services/<id>/setup/<env>.md`, so a mod's setup goes wherever the mod goes and disappears when it's deleted. Each one has the same sections: what it is, the versions tested, prerequisites, install, configuration, how to check it, what to look for, and known gaps. The format is in [mods.md §9](../mods.md#9-setup-docs).
- **The mods index** below is generated by `gaifa docs` from the setup docs, so a new mod shows up as soon as it has one, and a deleted mod disappears. `gaifa docs --check` (run by the test suite) fails when it's out of date or a setup doc doesn't parse; `--strict` also fails when a mod has no setup doc.
- **What a run saw** (plan 40.1): every step's, check's and smoke's whole output is in `data/state/setup/logs/`, and the last run (the machine, the plan, the report) in `data/state/setup/last-run.json`. A failure names its log and the setup doc's line it comes from; `gaifa report` (plan 40.2) turns all of it into one file for whoever fixes it.
- **Your own models** are listed by `gaifa docs` in `data/state/setup/models/` (local, not in git): one doc per model in your registry, with its files, hashes, source, which setup doc runs it and a download command, plus room for your own notes, which are kept when it regenerates. Set `[docs] regenerate = true` in `config.toml` to keep it current as models are added.

## Mods

<!-- generated by gaifa docs: do not edit between these markers -->
| Mod | What it gives you | GPU | Runs on | Disk | Setup docs |
|---|---|---|---|---|---|
| `agent` | Chat agent: the Chat page's tool loop (files, search, images, speech) on a chat model the relay serves, or a server you already run | no | CPU | 50 MB | [Chat agent](../../services/agent/setup/agent.md) |
| `calendar` | Calendar: events, to-dos and reminders in GAIFA, with in-app alerts and tools for the agent | no | CPU | 100 MB | [Calendar](../../services/calendar/setup/linux.md) |
| `comfy` | Images & Video: ComfyUI in a ROCm toolbox, running any workflow pack (images, edits, video, and two of 3D Generate's engines) | yes | ROCm · CUDA · Intel XPU · Apple MPS · CPU | 4.0 GB | [ComfyUI in the Strix Halo toolbox](../../services/comfy/setup/comfyui.md) |
| `decide` | Decisions: fast yes/no, choice and score answers with probabilities (the Auto judge's d3-lite) | yes | ROCm · CUDA · Intel XPU · Apple MPS · CPU | 6.6 GB | [Decisions: d3-lite](../../services/decide/setup/decide.md) · models compared: [Decision models compared (JEV decision index)](https://huggingface.co/spaces/multimodalart/jev-decision-index) |
| `embed` | Embeddings: search outputs, documents and chats by meaning (text, images, audio, video in one space) | yes | ROCm · CUDA · Intel XPU · Apple MPS · CPU | 6.6 GB | [Embeddings: EmbeddingGemma 2](../../services/embed/setup/embed.md) · models compared: [Embedding models compared (MTEB leaderboard)](https://huggingface.co/spaces/mteb/leaderboard) |
| `gen3d` | 3D Generate: text or a picture to 3D meshes, named parts and game rigs (the server, the ROCm image and every engine's runtime; the engines' weights are their own setups) · 3D Generate: text to 3D meshes with Cube3D, and named parts with CubePart (Roblox's research-only licence) · 3D Generate: one picture to a watertight mesh with Hunyuan3D 2.1 (best for characters) · 3D Generate: one picture to a mesh, the quickest full shape, with Meta's SAM 3D Objects (gated weights) | yes | ROCm · CUDA | 6.5 GB | [3D Generate: the server, the image and the runtimes](../../services/gen3d/setup/gen3d.md), [CubeArt: Cube3D and CubePart (3D Generate)](../../services/gen3d/setup/cubeart.md), [Hunyuan3D 2.1 (3D Generate)](../../services/gen3d/setup/img3d.md), [SAM 3D Objects (3D Generate)](../../services/gen3d/setup/sam3do.md) |
| `lcpp` | LLM Launcher: run any GGUF chat model with llama.cpp on the GPU (Vulkan), published to the relay | yes | CUDA · Apple MPS · Vulkan · CPU | 150 MB | [llama.cpp (LLM Launcher)](../../services/lcpp/setup/llama-cpp.md) |
| `mcp` | Other MCP servers' tools (Blender, and any stdio or HTTP MCP server) in GAIFA's chats, after you approve them · Blender in your chats: the MCP for Blender server and its add-on, with a Blender without a window when yours isn't open | no | CPU | 300 MB | [MCP servers](../../services/mcp/setup/mcp.md), [Blender for the mcp mod (MCP for Blender)](../../services/mcp/setup/blender.md) |
| `opencode` | OpenCode: a coding agent behind the relay's agent model, plus OpenCode Zen's free hosted models | no | CPU | 200 MB | [OpenCode](../../services/opencode/setup/opencode.md) |
| `relay` | LLM Relay: one OpenAI-compatible endpoint for every chat model, local or remote, with usage charts | no | CPU | 350 MB | [LLM Relay](../../services/relay/setup/relay.md) |
| `searxng` | Search for GAIFA: your SearXNG if one answers here, else GAIFA's own in a container; its health, engines and settings | no | CPU | 30 MB | [SearXNG watcher (the searxng mod)](../../services/searxng/setup/searxng.md) |
| `stt` | Speech to text: transcribe audio and video files, live dictation and the Chat microphone (Whisper; runs on the CPU, much faster with the GPU) | no | ROCm · CUDA · CPU | 750 MB | [Speech to Text (faster-whisper)](../../services/stt/setup/stt.md) |
| `tts` | Speech: voice cloning, voice design and delivery directions with Breeze TTS 2 (non-commercial), plus Whisper word timings · Speech: text to speech with Kokoro's fast built-in English voices (the server and its first engine) | yes | ROCm · CUDA · Intel XPU · Apple MPS · CPU | 13.6 GB | [Breeze TTS 2 and Whisper (Speech)](../../services/tts/setup/breeze.md), [Kokoro-82M (Speech)](../../services/tts/setup/kokoro.md) |
| `vllm` | vLLM: serve Hugging Face chat models (safetensors, AWQ) on the GPU, published to the relay | yes | ROCm | 100 MB | [vLLM](../../services/vllm/setup/vllm.md) |
| `voice` | Voice mode on a speech-to-speech model: it hears you and answers aloud itself, on this machine, in a fraction of a second (LFM3-Omni-2B in llama.cpp) | no | CUDA · Vulkan · CPU | 500 MB | [Voice (LFM3-Omni-2B in llama.cpp)](../../services/voice/setup/llama-cpp.md) |
| `web` | Web: search through your SearXNG and fetch pages and PDFs into Outputs, for you and the agent | no | CPU | 100 MB | [Web (SearXNG search and page fetching)](../../services/web/setup/web.md) |
| `workspace` | Workspace: let the agent read and edit your folders at a level you set, and run code in a podman sandbox | no | CPU | 1.1 GB | [Workspace (folders, edits in place, the sandbox)](../../services/workspace/setup/workspace.md) |
<!-- end generated -->
