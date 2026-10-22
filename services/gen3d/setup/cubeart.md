<!-- aihub-setup
id = "gen3d-cubeart"
title = "CubeArt: Cube3D and CubePart (3D Generate)"
models = ["3d/cube3d-v0.5", "3d/cubepart", "3d/clip-vit-large-patch14", "3d/Qwen3-VL-4B-Instruct", "3d/Qwen-Image"]
scan = []
summary = "3D Generate: text to 3D meshes with Cube3D, and named parts with CubePart (Roblox's research-only licence)"
gpu = true
disk_gb = 0
after = ["gen3d"]
check = "out=$(.venv/bin/python -m gen3d.doctor); for l in 'Cube3D GPT' 'Cube3D shape tokenizer' 'CLIP-L text encoder' 'CubePart DiT' 'CubePart shape VAE' 'Qwen3-VL-4B text encoder' 'Qwen-Image transformer config' 'upstream clone' 'CubePart code' 'worker venv'; do grep -Eq \"ok +$l\" <<<\"$out\" || exit 1; done"

[[steps]]
run = "test -d runtime/CubeArt/cube/cube3d && test -d runtime/CubeArt/cube/cubepart/cube_part && test -e runtime/CubeArt/.venv/bin/activate && test -e runtime/CubeArt/weights || { echo 'runtime/CubeArt is not built: run aihub setup gen3d (scripts/install-runtime.sh)' >&2; exit 1; }"
what = "checks that the gen3d setup built CubeArt (the Roblox/cube clone, runtime/CubeArt/.venv and its weights link to data/models/3d); nothing is installed here: this setup's own part is the five weight repos below, downloaded only after a yes"
ask = "Cube3D and CubePart come under Roblox's Cube3D Research-Only RAIL-MS licence (the LICENSE of https://github.com/Roblox/cube, which the gen3d setup cloned; the weights' card, https://huggingface.co/Roblox/cube3d-v0.5, is tagged openrail): its Permitted Purpose is 'for academic or research purposes only'. Download and use Cube3D's and CubePart's weights under that licence?"

[[suggest]]
name = "Cube3D v0.5"
repo = "Roblox/cube3d-v0.5"
files = ["shape_gpt.safetensors", "shape_tokenizer.safetensors"]
dest = "3d/cube3d-v0.5"
kind = "3d"
size_gb = 8.27
good_for = "text to mesh (the shape GPT and its shape tokenizer)"
licence = "Cube3D Research-Only RAIL-MS (academic or research purposes only; the card's tag says openrail)"
required = true

[[suggest]]
name = "CubePart"
repo = "Roblox/cubepart"
files = ["multi_part_dit.safetensors", "vae.safetensors"]
dest = "3d/cubepart"
kind = "3d"
size_gb = 9.9
good_for = "splitting a mesh into named parts"
licence = "OpenRAIL (model card)"
required = true

[[suggest]]
name = "CLIP ViT-L/14"
repo = "openai/clip-vit-large-patch14"
files = ["config.json", "merges.txt", "model.safetensors", "preprocessor_config.json", "special_tokens_map.json",
  "tokenizer.json", "tokenizer_config.json", "vocab.json"]
dest = "3d/clip-vit-large-patch14"
kind = "text-encoder"
size_gb = 1.71
good_for = "Cube3D's text encoder"
licence = "not stated on the model card"
required = true

[[suggest]]
name = "Qwen3-VL-4B-Instruct"
repo = "Qwen/Qwen3-VL-4B-Instruct"
files = ["chat_template.json", "config.json", "generation_config.json", "merges.txt", "model-00001-of-00002.safetensors",
  "model-00002-of-00002.safetensors", "model.safetensors.index.json", "preprocessor_config.json", "tokenizer.json",
  "tokenizer_config.json", "video_preprocessor_config.json", "vocab.json"]
dest = "3d/Qwen3-VL-4B-Instruct"
kind = "text-encoder"
size_gb = 8.89
good_for = "CubePart's text encoder"
licence = "Apache-2.0"
required = true

[[suggest]]
name = "Qwen-Image transformer config"
repo = "Qwen/Qwen-Image"
files = ["transformer/config.json"]
dest = "3d/Qwen-Image"
size_gb = 0.0
good_for = "CubePart reads its architecture from this one file (371 bytes)"
licence = "Apache-2.0"
required = true

[[variants]]                    # plan 39.7: where gen3d's base setup runs (ROCm image, or the host with CUDA)
accel = "rocm"
os = ["linux"]
tested = true

[[variants]]
accel = "cuda"
os = ["linux", "wsl"]
-->

# CubeArt (Cube3D and CubePart): setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The text engine of 3D Generate: **CubeArt** (`runtime/CubeArt/`), Roblox's **Cube3D v0.5** (text to mesh, with a CLIP-L text encoder) and **CubePart** (named parts, with a Qwen3-VL-4B text encoder). The `shape` stage with `engine = cube3d` and the `parts` stage need it; `rig` and `preview` run on the CPU. It runs in a `gen3d-worker-*` container of the ROCm image with `runtime/CubeArt/.venv`. The server venv, the image and every engine's code and venv come from [gen3d.md](gen3d.md); this setup is the licence and the weights. The picture engines are [img3d.md](img3d.md) (Hunyuan3D 2.1) and [sam3do.md](sam3do.md) (SAM 3D Objects); TRELLIS.2 and SAM 3D Body run as ComfyUI packs ([ComfyUI](../../comfy/setup/comfyui.md)). **Licence:** Roblox's code repo, [Roblox/cube](https://github.com/Roblox/cube), is under the **Cube3D Research-Only RAIL-MS** licence, whose Permitted Purpose is "for academic or research purposes only" (its listed artifacts are Cube3D and its inference code; CubePart's README says its code is under the same licence). The weights' Hugging Face cards are tagged only `openrail`, with no licence text. `aihub setup` asks before downloading them.

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest` at `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2`; its `/opt/venv` torch family is in [gen3d.md](gen3d.md#tested-with) (these pins are `runtime/CubeArt/.venv/constraints.txt`) |
| `runtime/CubeArt/.venv` | Python 3.13.13 inside the image, layered on `/opt/venv` by `_opt_venv.pth`, with `locks/cubeart.txt`: transformers 4.57.6, trimesh 5.1.0, pymeshlab 2025.7.post1, scikit-image 0.26.0, fpsample 1.0.2, warp-lang 1.17.0, gradio 6.17.3 |
| Upstream code | https://github.com/Roblox/cube.git at `3c6d06ddbef3160a1e1950cb13ab63dd12a61e50` (2026-05-27) in `runtime/CubeArt/cube/` (five example GLBs under `cubepart/examples/inputs/` show as modified; the code is unchanged) |

The weights are the five repos in Choosing models, all in `data/models/3d/` (about 29 GB), with the files the block lists; no revision is recorded for them.

## Prerequisites

- [gen3d.md](gen3d.md) (`after = ["gen3d"]`): the server venv, the image, and `runtime/CubeArt/` (the clone, the venv and the `weights` link), all built by its `install-runtime.sh`.
- About 30 GB for the weights.

## Install

```bash
cd services/gen3d && test -d runtime/CubeArt/cube/cube3d && test -e runtime/CubeArt/.venv/bin/activate && test -e runtime/CubeArt/weights
```

The setup's one step: checks that [gen3d.md](gen3d.md#install) built CubeArt; it installs nothing. The licence question comes with it.

The weights have **no downloader in git** (CubeArt's old `scripts/download_weights.sh` sits in the gitignored `runtime/`, and nothing recreates it); they're the block's required suggestions (Choosing models), each with its repo, files and folder, and `aihub setup` downloads them. By hand, from the project folder, one command per repo with the files and folder the block gives, for example:

```bash
uvx --from huggingface_hub hf download Roblox/cube3d-v0.5 shape_gpt.safetensors shape_tokenizer.safetensors --local-dir data/models/3d/cube3d-v0.5
```

## Choosing models

CubeArt runs fixed weights, all five repos below, in `data/models/3d/<folder>/` (`GEN3D_WEIGHTS`, mounted read-only into the worker; `runtime/CubeArt/weights` links to it). There's nothing to swap: the code loads these exact files, and `gen3d.doctor` checks them. Cube3D and CLIP-L make the mesh from text; CubePart, Qwen3-VL-4B and Qwen-Image's config split it into parts.

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| Cube3D v0.5 (`Roblox/cube3d-v0.5`, 2 files) | 8.27 GB | text to mesh | Cube3D Research-Only RAIL-MS | yes |
| CubePart (`Roblox/cubepart`, 2 files) | 9.90 GB | named parts | OpenRAIL (model card) | yes |
| CLIP ViT-L/14 (`openai/clip-vit-large-patch14`) | 1.71 GB | Cube3D's text encoder | not stated on the card | yes |
| Qwen3-VL-4B-Instruct (`Qwen/Qwen3-VL-4B-Instruct`) | 8.89 GB | CubePart's text encoder | Apache-2.0 | yes |
| Qwen-Image config (`Qwen/Qwen-Image`, `transformer/config.json`) | 371 bytes | CubePart's architecture | Apache-2.0 | yes |

## Configuration

Nothing of its own beyond [gen3d.md's](gen3d.md#configuration): `GEN3D_CUBEART` (`runtime/CubeArt`: code, venv, caches) and `GEN3D_WEIGHTS` are set in `service.toml`. Per-job options are the job's `shape` and `parts` groups (`ShapeOptions` and `PartsOptions` in `gen3d/options.py`; the API schema and the `make_3d` tool list them).

## Check it works

```bash
cd services/gen3d && .venv/bin/python -m gen3d.doctor
```

Checks files only; nothing loads. Expect `ok` on the seven CubeArt weight lines (`Cube3D GPT`, `Cube3D shape tokenizer`, `CLIP-L text encoder`, `CubePart DiT`, `CubePart shape VAE`, `Qwen3-VL-4B text encoder`, `Qwen-Image transformer config`) and on `upstream clone (cube/)`, `CubePart code` and `worker venv (.venv)`; the setup's `check` reads exactly those ten. A `MISSING` line names the file or the fix.

```bash
git -C services/gen3d/runtime/CubeArt/cube rev-parse HEAD
```

Expect `3c6d06ddbef3160a1e1950cb13ab63dd12a61e50`.

## What to look for

- **The first CubePart job is slower**: torch.compile builds its kernels once (about 25 s), cached in `runtime/CubeArt/.cache`, where the worker also keeps its Triton and MIOpen caches.
- **The `weights` link** (`runtime/CubeArt/weights` → `data/models/3d`) is resolved when it's mounted; a weights folder moved elsewhere needs the link pointed at it.
- **GPU safety.** Use the stock image and the locks. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- No script in the mod downloads the weights: `aihub setup` downloads them from the block's suggestions, and by hand it's the commands above.
- `install-runtime.sh` checks out Roblox/cube's commit only on the first clone.
