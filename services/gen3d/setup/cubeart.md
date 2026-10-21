<!-- aihub-setup
id = "gen3d-cubeart"
title = "CubeArt: Cube3D and CubePart (3D Generate)"
models = ["3d/cube3d-v0.5", "3d/cubepart", "3d/clip-vit-large-patch14", "3d/Qwen3-VL-4B-Instruct", "3d/Qwen-Image"]
scan = []
-->

# CubeArt (Cube3D and CubePart): setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The 3D Generate mod (`gen3d`, port 5050) has a server and GPU workers. The server, `python -m gen3d`, runs in `.venv/` in this folder and never touches the GPU. Each job's GPU work runs in a worker: a `podman run -i` of the ROCm image (`gen3d-worker-*`), with one of three venvs from `runtime/` layered on the image's own torch. This doc covers the server venv, the image, and **CubeArt** (`runtime/CubeArt/`): Roblox's **Cube3D v0.5** (text to mesh, with a CLIP-L text encoder) and **CubePart** (named parts, with a Qwen3-VL-4B text encoder). The `shape` stage with `engine = cube3d` and the `parts` stage need it; `rig` and `preview` run on the CPU. The picture engines are in [img3d.md](img3d.md) (Hunyuan3D 2.1) and [sam3do.md](sam3do.md) (SAM 3D Objects). TRELLIS.2 and SAM 3D Body run as ComfyUI packs: see [ComfyUI](../../comfy/setup/comfyui.md). Cube3D's licence is the research-only RAIL-MS.

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Server `.venv` | Python 3.12.13 (uv-managed), fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.13.5, pillow 12.3.0 |
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest`, digest `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2` (built 2026-05-29, 15.1 GB; the same image as ComfyUI) |
| The image's `/opt/venv` | Python 3.13.13, `torch==2.13.0a0+rocm7.14.0a20260529`, `torchvision==0.28.0a0+rocm7.14.0a20260529`, `torchaudio==2.11.0+rocm7.14.0a20260529`, `triton==3.7.0+gita0718cfe.rocm7.14.0a20260529`, numpy 2.4.3, diffusers 0.38.0 (these pins are `runtime/CubeArt/.venv/constraints.txt`) |
| `runtime/CubeArt/.venv` | Python 3.13.13 inside the image, layered on `/opt/venv` by `_opt_venv.pth`, with `locks/cubeart.txt`: transformers 4.57.6, trimesh 5.1.0, pymeshlab 2025.7.post1, scikit-image 0.26.0, fpsample 1.0.2, warp-lang 1.17.0, gradio 6.17.3 |
| Upstream code | https://github.com/Roblox/cube.git at `3c6d06ddbef3160a1e1950cb13ab63dd12a61e50` (2026-05-27) in `runtime/CubeArt/cube/` (five example GLBs under `cubepart/examples/inputs/` show as modified; the code is unchanged) |
| Blender (previews) | 5.2.2 LTS at `~/.local/bin/blender` |

The weights, all in `data/models/3d/` (about 29 GB):

| Folder | Hugging Face repo | Files | Size |
|---|---|---|---|
| `cube3d-v0.5` | `Roblox/cube3d-v0.5` | `shape_gpt.safetensors`, `shape_tokenizer.safetensors` | 8.3 GB |
| `cubepart` | `Roblox/cubepart` | `multi_part_dit.safetensors`, `vae.safetensors` | 9.9 GB |
| `clip-vit-large-patch14` | `openai/clip-vit-large-patch14` | `model.safetensors` and its configs | 1.7 GB |
| `Qwen3-VL-4B-Instruct` | `Qwen/Qwen3-VL-4B-Instruct` | two safetensors shards and their configs | 8.9 GB |
| `Qwen-Image` | `Qwen/Qwen-Image` | `transformer/config.json` only (CubePart reads its architecture) | 4 kB |

No revision is recorded for them.

## Prerequisites

- [host.md](../../../docs/setup/host.md): podman, the `video` and `render` groups, the kernel settings in [§1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory) with the IOMMU on, and optionally Blender at `~/.local/bin/blender` for previews.
- git, uv, and about 30 GB for the weights.

## Install

```bash
aihub install gen3d
```

Runs `aihub-install.sh`: makes `.venv/` with Python 3.12 from `requirements.txt` (the server only).

```bash
podman pull docker.io/kyuz0/amd-strix-halo-comfyui:latest
```

The ROCm image (15.1 GB), shared with the comfy mod. The installer stops without it.

The weights have **no downloader in git** (CubeArt's old `scripts/download_weights.sh` sits in the gitignored `runtime/`, and nothing recreates it). From the project folder, one command each (the lists come from the registry; each model's doc in [docs/setup/models/](../../../docs/setup/models/) has the same):

```bash
uvx --from huggingface_hub hf download Roblox/cube3d-v0.5 shape_gpt.safetensors shape_tokenizer.safetensors --local-dir data/models/3d/cube3d-v0.5
```

```bash
uvx --from huggingface_hub hf download Roblox/cubepart multi_part_dit.safetensors vae.safetensors --local-dir data/models/3d/cubepart
```

```bash
uvx --from huggingface_hub hf download openai/clip-vit-large-patch14 config.json merges.txt model.safetensors preprocessor_config.json special_tokens_map.json tokenizer.json tokenizer_config.json vocab.json --local-dir data/models/3d/clip-vit-large-patch14
```

```bash
uvx --from huggingface_hub hf download Qwen/Qwen3-VL-4B-Instruct chat_template.json config.json generation_config.json merges.txt model-00001-of-00002.safetensors model-00002-of-00002.safetensors model.safetensors.index.json preprocessor_config.json tokenizer.json tokenizer_config.json video_preprocessor_config.json vocab.json --local-dir data/models/3d/Qwen3-VL-4B-Instruct
```

```bash
uvx --from huggingface_hub hf download Qwen/Qwen-Image transformer/config.json --local-dir data/models/3d/Qwen-Image
```

```bash
services/gen3d/scripts/install-runtime.sh
```

Builds all three worker venvs. For CubeArt: clones Roblox/cube into `runtime/CubeArt/cube/` and checks out the commit above, links `runtime/CubeArt/weights` to `data/models/3d`, then inside the image (`podman run --rm`, no GPU devices passed) makes `runtime/CubeArt/.venv` with the image's Python 3.13, adds a `.pth` pointing at `/opt/venv`'s site-packages, writes the image's torch/torchvision/torchaudio/triton/numpy versions to `constraints.txt` so pip never replaces them, installs `locks/cubeart.txt`, and checks the imports. Then it builds [img3d](img3d.md) and [sam3do](sam3do.md). Re-running is safe; finished steps are skipped. It wasn't re-run for this doc.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `GEN3D_WEIGHTS` | `service.toml` | yes (set) | `{models}/3d`, mounted read-only into the workers |
| `GEN3D_CUBEART` | `service.toml` | yes (set) | `runtime/CubeArt` (code, venv, caches) |
| `GEN3D_DATA`, `GEN3D_DB`, `GEN3D_OUTPUTS`, `GEN3D_STATE_DIR` | `service.toml` | yes (set) | the jobs folder, `gen3d.db`, `outputs/gen3d`, `data/state/gen3d` (the page's settings) |
| `GEN3D_IMAGE`, `GEN3D_PODMAN` | `config.toml [services.gen3d].env` | optional | the ROCm image (default `…/amd-strix-halo-comfyui:latest`) and the podman binary |
| `GEN3D_BLENDER` | `service.toml` | optional | `~/.local/bin/blender`; empty disables previews |
| `GEN3D_PREVIEW_DEVICE` | `service.toml` | optional | `cpu` (set): previews on Mesa llvmpipe; `gpu` is faster. A choice saved on the page wins |
| `GEN3D_IDLE_UNLOAD_S` | from `[memory] idle_unload_s` | optional | stop the worker after this many idle seconds (600) |

`gen3d.env.example` lists the rest for standalone use; under AIHub, `service.toml` and `config.toml` set them.

## Check it works

```bash
aihub check gen3d
```

Expect `gen3d: all checks passed` (2026-10-21).

```bash
cd services/gen3d && .venv/bin/python -m gen3d.doctor
```

Checks files and podman only; nothing loads. Expect 17 `ok` lines and exit 0: the seven CubeArt weight files, `upstream clone (cube/)`, `CubePart code`, `worker venv (.venv)`, `Hunyuan3D 2.1 (image engine) ready`, `SAM 3D Objects (image engine) ready`, the two ComfyUI engines as `runs in the comfy mod`, `podman`, `ROCm image`, and `Blender (previews, optional)`. A `MISSING` line names the file or the fix.

```bash
curl -s http://127.0.0.1:7000/api/s/gen3d/v1/status
```

A GET, so nothing loads. Expect `"loaded": false`, `"worker": {"state": "stopped", …}` while idle, and the stat `{"label": "Previews", "value": "CPU", …}`.

## What to look for

- **The worker runs in the image, the server on the host.** The venvs under `runtime/` point at the image's `/usr/bin/python3.13` and `/opt/venv`; they can't run on the host.
- **Mounts must be real paths.** The worker mounts `runtime/`, the jobs folder and the weights by their resolved paths; a symlink pointing outside a mount is broken inside the container.
- **Previews run on the CPU by default** (since 2026-10-21): the one GPU fault in a night of 3D runs was Blender drawing a preview. With `cpu`, Blender starts with `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` and refuses to render on anything but llvmpipe or softpipe.
- **The first CubePart job is slower**: torch.compile builds its kernels once (about 25 s), cached in `runtime/CubeArt/.cache`, where the worker also keeps its Triton and MIOpen caches. Workers run with `HF_HUB_OFFLINE=1`: they never download.
- **Worker settings** (`gen3d/worker.py`): `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`, `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`, `ROCPROFILER_REGISTER_ENABLED=0`, `--network none`, and `HSA_OVERRIDE_GFX_VERSION` unset.
- **Memory:** the Quality preset peaks at about 52 GB (`[memory] estimate_gb`); out of memory is the usual cause of "worker exited" when ComfyUI or an LLM holds the unified memory.
- **GPU safety.** Use the stock image and the locks. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- No script downloads the weights; the commands above are manual.
- The image is `:latest`, not pinned by digest in code; the venvs' `constraints.txt` record the torch they were built against.
- `install-runtime.sh` checks out Roblox/cube's commit only on the first clone.
- CubeArt's own scripts (`cubeart`, `cube-run`, `scripts/`) in `runtime/CubeArt/` came from the old `~/Models/3D/CubeArt` and aren't recreated; the mod doesn't need them.
