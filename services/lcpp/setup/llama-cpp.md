<!-- aihub-setup
id = "lcpp"
title = "llama.cpp (LLM Launcher)"
models = ["llm/**"]
scan = ["data/models.json"]
summary = "LLM Launcher: run any GGUF chat model with llama.cpp on the GPU (Vulkan), published to the relay"
gpu = true
disk_gb = 0.15
needs = ["uv", "curl", "tar", "sha256sum", "systemd-run"]
check = "aihub check lcpp"

[[steps]]
run = "aihub install lcpp"
what = "makes the daemon's .venv/ from uv.lock (about 29 MB); it doesn't fetch llama.cpp"

[[steps]]
run = "mkdir -p runtime/llama.cpp/vendor runtime/llama.cpp/bin && curl -L -o runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz https://github.com/ggml-org/llama.cpp/releases/download/b11445/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz"
what = "downloads llama.cpp build 11445, the Vulkan release asset (32 MB, from GitHub)"

[[steps]]
run = 'echo "dd98daa1df6ae680e69a0b5e27789b00d90715e712d007bd14c2c35d3841faf6  runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz" | sha256sum -c && tar xzf runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz -C runtime/llama.cpp/bin && ln -sfn llama-b11445 runtime/llama.cpp/bin/current'
what = "checks the archive's sha256, unpacks llama-b11445/ (about 90 MB) and points runtime/llama.cpp/bin/current at it"

[[suggest]]
name = "Qwen3 8B (Q4_K_M)"
op = "POST /api/downloads"
body = { repo = "Qwen/Qwen3-8B-GGUF", revision = "7c41481f57cb95916b40956ab2f0b139b296d974", choice = "Qwen3-8B-Q4_K_M.gguf" }
size_gb = 5.03
good_for = "an everyday chat model with tool calls and thinking, small enough to run beside other mods"
licence = "Apache-2.0"

[[suggest]]
name = "Gemma 4 26B-A4B (Q8_0, with vision and MTP)"
op = "POST /api/downloads"
body = { repo = "ggml-org/gemma-4-26B-A4B-it-GGUF", revision = "9cf8c8db0f83fb4582f15381f8fb1a7c1b0b9ca2", choice = "gemma-4-26B-A4B-it-Q8_0.gguf", mmproj = "mmproj-gemma-4-26B-A4B-it-Q8_0.gguf", draft = "mtp-gemma-4-26B-A4B-it-Q8_0.gguf" }
size_gb = 28.13
good_for = "a strong agent and judge model (mixture of experts, about 4B active), images in, an MTP draft"
licence = "Apache-2.0"
-->

# llama.cpp (LLM Launcher): setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `lcpp` mod (port 7710) starts and stops llama.cpp servers for GGUF models and publishes each to the [relay](../../relay/setup/relay.md). It has two parts:
- **The daemon**, `.venv/` in this folder (FastAPI, uvicorn, httpx). It loads no model. Each instance it launches is its own transient systemd user unit (`lcpp-<name>.service`), so instances survive a daemon restart.
- **`llama-server`**, a prebuilt **Vulkan** build of llama.cpp from the [ggml-org releases](https://github.com/ggml-org/llama.cpp/releases), unpacked by hand under `runtime/` (gitignored). It runs on the GPU through Mesa's RADV driver; no ROCm is needed.

The LLM Launcher page, any local GGUF the agent or the Auto judge uses (on this machine, `gemma4-26B`), and the agent's `list_llms` / `start_llm` tools need this environment.

## Tested with

Read from this machine on 2026-10-21:

| Part | Version |
|---|---|
| llama.cpp | build 11445, commit `58cb9138e` (`llama-server --version`: `version: 0.6.0-dev (build 11445, commit 58cb9138e)`, built with GNU 11.4.0) |
| Release asset | `llama-b11445-bin-ubuntu-vulkan-x64.tar.gz`, 31,637,791 bytes, sha256 `dd98daa1df6ae680e69a0b5e27789b00d90715e712d007bd14c2c35d3841faf6` |
| Previous build kept | `llama-b9692` (and its tarball), for rolling back |
| Vulkan | Mesa 26.2.4 RADV (`AMD Radeon 8060S Graphics (RADV STRIX_HALO)`, API 1.4.354), `vulkan-loader` 1.4.341 |
| The daemon | Python 3.14.6 (uv-managed), fastapi 0.141.1, uvicorn 0.53.0, httpx 0.28.1 |

`runtime/` takes 262 MB with both builds and both tarballs.

## Prerequisites

- [host.md](../../../docs/setup/host.md): the kernel parameters (GTT), the `video` and `render` groups, `mesa-vulkan-drivers`, the IOMMU **on**.
- The [relay](../../relay/setup/relay.md), if instances should be reachable from Chat and the agent.
- `systemd-run`, `systemctl` and `journalctl` (instances are user units).

## Install

```bash
aihub install lcpp
```

Runs `aihub-install.sh`: `uv sync --python 3.14` makes `.venv/` from `uv.lock` (about 29 MB). It doesn't fetch llama.cpp. Do that by hand, from the repo root:

```bash
mkdir -p services/lcpp/runtime/llama.cpp/vendor services/lcpp/runtime/llama.cpp/bin
curl -L -o services/lcpp/runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz https://github.com/ggml-org/llama.cpp/releases/download/b11445/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz
```

32 MB from GitHub. Use the `ubuntu-vulkan-x64` asset, not a ROCm or CPU one.

```bash
sha256sum services/lcpp/runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz
```

Expect the sha256 above.

```bash
tar xzf services/lcpp/runtime/llama.cpp/vendor/llama-b11445-bin-ubuntu-vulkan-x64.tar.gz -C services/lcpp/runtime/llama.cpp/bin
```

The archive holds one folder, `llama-b11445/` (`llama-server`, the other tools and the `libggml-*.so` libraries).

```bash
ln -sfn llama-b11445 services/lcpp/runtime/llama.cpp/bin/current
```

`data/lcpp.json` runs `runtime/llama.cpp/bin/current/llama-server`, so moving `current` is how you upgrade or roll back (`aihub restart lcpp` afterwards; running instances keep their binary).

## Choosing models

llama.cpp runs **any GGUF** chat model; which ones is your choice, and none is needed to install the mod. GGUFs live in `data/models/llm/<Folder>/` (`LCPP_MODELS_DIR`); the catalog is `data/models.json`, with paths relative to that folder. How much fits is set by the GTT ([host.md](../../../docs/setup/host.md)): on 128 GB of unified memory, a model's file plus its context's KV cache should leave room for the other mods. Summary of [README.md → Adding a model](../README.md#adding-a-model):
- **From Hugging Face:** the page's **Models → Add model → Hugging Face**, with a repo id or a link to one `.gguf` file. It lists the quants and the `mmproj` / `mtp` sidecars, downloads into `data/models/llm/<folder>/`, checks the Hub's sha256, adds it to the catalog and registers it in AIHub's models registry.
- **By hand:** put the GGUF in `data/models/llm/<Name>/`, then **Models → Discovered → Add to catalog** (or an entry in `data/models.json`), and `aihub models scan --add` to register it.

Only GGUF runs here; safetensors, AWQ and GPTQ repos go to [vLLM](../../vllm/setup/vllm.md).

Two optional starting points, which `aihub setup` offers (the page's form does the same with a repo id and a quant); sizes from Hugging Face, 2026-10-21:

| Model | Size | Good for | Licence |
|---|---|---|---|
| [Qwen3 8B](https://huggingface.co/Qwen/Qwen3-8B-GGUF), Q4_K_M | 5.0 GB | an everyday chat model with tool calls and thinking, small enough to run beside other mods | Apache-2.0 |
| [Gemma 4 26B-A4B](https://huggingface.co/ggml-org/gemma-4-26B-A4B-it-GGUF), Q8_0 with its `mmproj` (images) and `mtp` (draft) files | 28.1 GB | a strong agent and judge model (a mixture of experts, about 4B active per token); a QAT Q4_K_M variant of it is the agent's fallback and the judge on this machine | Apache-2.0 |

Each joins the catalog under a suggested id; a nickname on the page sets the name the relay lists it under.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `LCPP_HOME` | `service.toml` | yes (set) | this folder |
| `LCPP_MODELS_DIR` | `service.toml` | yes (set) | `{models}/llm` |
| `LCPP_STATE_DIR` | `service.toml` | yes (set) | `data/state/lcpp`: instance records |
| `LCPP_BACKEND` | `service.toml` | yes (set) | `systemd` |
| `llama.binary` | `data/lcpp.json` | yes | `runtime/llama.cpp/bin/current/llama-server` |
| `llama.environment` | `data/lcpp.json` | yes | `AMD_VULKAN_ICD=RADV` (Mesa's RADV driver), `GPU_MAX_HW_QUEUES=8` |
| `llama.server_params` | `data/lcpp.json` | optional | flags for every instance: `jinja`, `reasoning: auto`, `reasoning-format: deepseek`, `reasoning-budget: -1` |
| `ports` | `data/lcpp.json` | optional | instances take ports 7071–7199 |
| `relay` | `data/lcpp.json` | optional | `http://127.0.0.1:4000`, `auto_register: true` |
| `defaults`, per-model `params` | `data/models.json` | optional | here: context 262144, q8_0 KV cache, all layers on the GPU, flash attention |

The page's Settings view edits `data/lcpp.json`.

## Check it works

```bash
services/lcpp/runtime/llama.cpp/bin/current/llama-server --version
```

Expect `version: 0.6.0-dev (build 11445, commit 58cb9138e)`. It loads no model.

```bash
aihub check lcpp
```

Expect `lcpp: all checks passed`.

```bash
cd services/lcpp && LCPP_HOME=$PWD LCPP_MODELS_DIR=$PWD/../../data/models/llm .venv/bin/lcpp doctor
```

Read-only. Expect `[ok  ]` for settings, llama-server, catalog (`2 models, 0 with missing files` here), daemon and relay. `[warn] service lcpp.service not installed` is expected under AIHub: the daemon runs as AIHub's unit, not as `lcpp.service`.

```bash
cd services/lcpp && .venv/bin/python -m pytest -q
```

A fake llama-server, no GPU and no systemd: expect `91 passed` (2026-10-21).

## What to look for

- **Use the stock, pinned build.** Run the ggml-org release as published; don't build llama.cpp with custom kernels or flags, and keep the IOMMU on ([host.md, the IOMMU warning](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). On this chip the GPU writes into the same memory as everything else, and in October 2026 experimental GPU compute corrupted files on this machine.
- **`lcpp doctor` without the two variables** looks for models in `services/lcpp/models/` and reports every model's file as not found. Pass `LCPP_HOME` and `LCPP_MODELS_DIR` as above.
- **Two Vulkan devices.** `vulkaninfo --summary` lists the Radeon (`driverName = radv`) and `llvmpipe` (Mesa's CPU renderer). If the Radeon is missing, check the `video`/`render` groups and `mesa-vulkan-drivers`. `llama.environment` (`AMD_VULKAN_ICD=RADV`, `GPU_MAX_HW_QUEUES=8`) is passed to every instance; keep it as it is.
- **Memory.** A launch asks AIHub for memory first (`POST /api/memory/acquire`); a `needs_room` answer means other mods would have to unload. `lcpp start <model> --dry-run` (or the page's launch form) shows the estimate without starting anything. The GPU can only use the GTT the kernel parameters give it (host.md).
- **Instances aren't on the relay.** The relay was down when they became ready: registrations wait as `pending` and retry. The page's Relay view shows them.

## Known gaps

- Nothing downloads or unpacks llama.cpp; the steps above are by hand. The build isn't pinned anywhere but the `current` link.
- `aihub-install.sh` and `.gitignore` point to `runtime/README.md`, which doesn't exist (`runtime/` is gitignored). This doc replaces it.
- The `lcpp` command on `PATH` is a uv tool (`~/.local/bin/lcpp`, editable install of this folder) installed by the old `scripts/install.sh`, outside the project.
