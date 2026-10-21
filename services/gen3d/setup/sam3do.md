<!-- aihub-setup
id = "gen3d-sam3do"
title = "SAM 3D Objects (3D Generate)"
models = ["3d/sam-3d-objects", "3d/moge-vitl"]
scan = []
summary = "3D Generate: one picture to a mesh, the quickest full shape, with Meta's SAM 3D Objects (gated weights)"
gpu = true
disk_gb = 1.5
needs = ["podman", "git", "uv"]
after = ["gen3d-cubeart", "gen3d-img3d"]
check = ".venv/bin/python -m gen3d.doctor | grep -Eq 'ok +SAM 3D Objects \\(image engine\\) +ready'"

[[steps]]
run = "uvx --from huggingface_hub hf auth whoami >/dev/null 2>&1 || uvx --from huggingface_hub hf auth login"
what = "logs in to Hugging Face once (your token goes to ~/.cache/huggingface/token), for the gated weights; skipped when you're logged in"
ask = "SAM 3D Objects' weights are gated: accept the SAM Licence on https://huggingface.co/facebook/sam-3d-objects and wait until access is granted. Is access granted?"

[[steps]]
run = "scripts/install-runtime.sh"
what = "the runtime installer again (it skips what the other gen3d docs built): clones sam-3d-objects and DINOv2 at the pinned commits and builds runtime/sam3do/.venv inside the image, layered on img3d's and CubeArt's (about 1.5 GB; pytorch3d is built from source, CPU ops only; no GPU devices passed)"

[[suggest]]
name = "SAM 3D Objects"
repo = "facebook/sam-3d-objects"
files = ["checkpoints/pipeline.yaml", "checkpoints/ss_generator.ckpt", "checkpoints/ss_generator.yaml", "checkpoints/ss_decoder.ckpt",
  "checkpoints/ss_decoder.yaml", "checkpoints/ss_encoder.yaml", "checkpoints/slat_generator.ckpt", "checkpoints/slat_generator.yaml",
  "checkpoints/slat_decoder_mesh.ckpt", "checkpoints/slat_decoder_mesh.yaml", "checkpoints/slat_decoder_gs.ckpt",
  "checkpoints/slat_decoder_gs.yaml", "checkpoints/slat_decoder_gs_4.yaml", "checkpoints/slat_encoder.yaml", "LICENSE", "README.md"]
dest = "3d/sam-3d-objects"
kind = "3d"
size_gb = 12.28
good_for = "the engine's checkpoints (geometry only)"
licence = "SAM Licence"
required = true
gated = true

[[suggest]]
name = "MoGe v1 ViT-L"
repo = "Ruicheng/moge-vitl"
files = ["model.pt"]
dest = "3d/moge-vitl"
kind = "3d"
size_gb = 1.26
good_for = "the depth / point-map model SAM 3D Objects reads the picture with"
licence = "MIT"
required = true
-->

# SAM 3D Objects: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

One of 3D Generate's picture engines (`engine = sam3d_objects`): Meta's **SAM 3D Objects**, geometry only, from one picture (its alpha is the mask) to a mesh. It's the quickest full shape, with a rougher surface. It runs in a `gen3d-worker-*` container of the ROCm image, with the venv `runtime/sam3do/.venv`, the upstream code in `runtime/sam3d-objects/`, and DINOv2's code in `runtime/sam3do/dinov2/`. Its depth model is **MoGe v1** (`Ruicheng/moge-vitl`). The server venv, the image and how the venvs are layered are in [cubeart.md](cubeart.md). **Licence:** the SAM Licence; the weights are **gated** on Hugging Face. MoGe is MIT. SAM 3D Body (people) is a different model and runs in ComfyUI: see [ComfyUI](../../comfy/setup/comfyui.md).

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest` at `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2`; torch `2.13.0a0+rocm7.14.0a20260529` from its `/opt/venv` (see [cubeart.md](cubeart.md#tested-with)) |
| `runtime/sam3do/.venv` | Python 3.13.13 inside the image; `_layers.pth` puts img3d's, CubeArt's, then `/opt/venv`'s site-packages on its path; `locks/sam3do.txt`: hydra-core 1.3.7, lightning 2.6.6, pyvista 0.49.0, xatlas 0.0.11, roma 1.6.1, pymeshfix 0.18.1, fvcore 0.1.5.post20221221, `utils3d` at `3913c65d81e05e47b9f367250cf8c0f7462a0900`, `moge` at `74fbce054ebed49800de42d0ad0e83495065719a` (MoGe 3.0.0) |
| pytorch3d | 0.7.8, built from https://github.com/facebookresearch/pytorch3d.git at `75ebeeaea0908c5527e7b1e305fbc7681382db47` with `FORCE_CUDA=0` (CPU ops only) |
| Upstream code | https://github.com/facebookresearch/sam-3d-objects.git at `f91db411c50efee93d8db7aeb323885650f6f722` (2026-06-02); https://github.com/facebookresearch/dinov2.git at `7764ea0f912e53c92e82eb78a2a1631e92725fc8` (2026-06-03); no local changes |
| Weights | `facebook/sam-3d-objects` (revision `main`) in `data/models/3d/sam-3d-objects/`: `checkpoints/` (five `.ckpt` files and their yamls), 12.3 GB; `Ruicheng/moge-vitl` `model.pt` in `data/models/3d/moge-vitl/`, 1.3 GB |

## Prerequisites

- [img3d.md](img3d.md) and [cubeart.md](cubeart.md): this venv is layered on both, so `install-runtime.sh` builds them first.
- **Access to the gated repo.** Accept the terms on https://huggingface.co/facebook/sam-3d-objects, then log in once ([host.md §6](../../../docs/setup/host.md#6-accounts-and-licences)). This machine was granted access on 2026-10-10.
- About 14 GB for the weights, and 22 GB of free memory when it runs (`memory_gb = 22` in `gen3d/engines.py`).

## Install

```bash
uvx --from huggingface_hub hf auth login
```

Stores your token in `~/.cache/huggingface/token`; needed once for the gated repo.

```bash
uvx --from huggingface_hub hf download facebook/sam-3d-objects checkpoints/slat_decoder_gs.ckpt checkpoints/slat_decoder_mesh.ckpt checkpoints/slat_generator.ckpt checkpoints/ss_decoder.ckpt checkpoints/ss_generator.ckpt LICENSE README.md checkpoints/pipeline.yaml checkpoints/slat_decoder_gs.yaml checkpoints/slat_decoder_gs_4.yaml checkpoints/slat_decoder_mesh.yaml checkpoints/slat_encoder.yaml checkpoints/slat_generator.yaml checkpoints/ss_decoder.yaml checkpoints/ss_encoder.yaml checkpoints/ss_generator.yaml --local-dir data/models/3d/sam-3d-objects
```

From the project folder: the checkpoints the registry lists (12.3 GB).

```bash
uvx --from huggingface_hub hf download Ruicheng/moge-vitl model.pt --local-dir data/models/3d/moge-vitl
```

MoGe v1 ViT-L (1.3 GB). Nothing in git downloads either model; they're the block's required suggestions.

```bash
services/gen3d/scripts/install-runtime.sh
```

After CubeArt and img3d, it clones sam-3d-objects into `runtime/sam3d-objects/` and DINOv2 into `runtime/sam3do/dinov2/` at the commits above, then inside the image (no GPU devices passed) makes `runtime/sam3do/.venv`, writes `_layers.pth` and `constraints.txt`, installs `locks/sam3do.txt`, builds pytorch3d from source if it doesn't import (CPU ops only, `--no-build-isolation`, `MAX_JOBS=16`), and checks the imports (`sam3do ok`). It wasn't re-run for this doc.

## Choosing models

SAM 3D Objects runs fixed weights: its checkpoints from `facebook/sam-3d-objects` in `data/models/3d/sam-3d-objects/checkpoints/`, and MoGe v1 in `data/models/3d/moge-vitl/` (the engine loads v1 by that path; keep it v1: MoGe v3's code path imports FlexGEMM's Triton kernels, see What to look for). DINOv2's weights are inside the checkpoints. There's nothing to swap. The engine is optional within 3D Generate: without it, the engine picker lists `sam3d_objects` with what's missing.

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| SAM 3D Objects (`facebook/sam-3d-objects`, 16 files, gated) | 12.28 GB | the engine's checkpoints | SAM Licence | yes, for this engine |
| MoGe v1 ViT-L (`Ruicheng/moge-vitl`, `model.pt`) | 1.26 GB | its depth model | MIT | yes, for this engine |

## Configuration

Nothing of its own: the worker reads `GEN3D_WEIGHTS` and `GEN3D_RUNTIME`, runs with `PYTHONPATH=workers/shims:runtime/sam3d-objects:workers` and `LIDRA_SKIP_INIT=true`. Per-job options are the job's `sam3d_objects` group (`Sam3dObjectsOptions` in `gen3d/image_options.py`).

## Check it works

```bash
cd services/gen3d && .venv/bin/python -m gen3d.doctor
```

Checks files only. Expect `ok      SAM 3D Objects (image engine)    ready`. When something is missing, the line lists it (the code folders, `runtime/sam3do/.venv`, the checkpoints or `models/3d/moge-vitl/model.pt`) with the fix.

```bash
git -C services/gen3d/runtime/sam3d-objects rev-parse HEAD
```

Expect `f91db411c50efee93d8db7aeb323885650f6f722`.

```bash
git -C services/gen3d/runtime/sam3do/dinov2 rev-parse HEAD
```

Expect `7764ea0f912e53c92e82eb78a2a1631e92725fc8`.

## What to look for

- **The shims.** spconv, gsplat, kaolin and open3d have no ROCm or Python 3.13 build. `workers/shims/` comes first on the worker's path: spconv is a pure-PyTorch stand-in for what SAM 3D Objects uses, kaolin provides only `utils.testing.check_tensor`, and gsplat and open3d are import-only (the geometry-only path never calls them; any real use raises).
- **MIOpen is off** (`torch.backends.cudnn.enabled = False`), as ComfyUI does on gfx1151. torch.compile, the 4-Gaussian decoder and mesh post-processing (its hole filling needs a CUDA rasteriser) are off too.
- **Patched configs.** On load the worker writes `runtime/sam3do/config/`: copies of the checkpoint yamls pointing DINOv2 at the local clone with `pretrained: false` (its weights are in the checkpoints), and links to the `.ckpt` files. Delete the folder to have it written again.
- **MoGe 3.0 brings FlexGEMM** (Triton kernels) as a dependency. Only MoGe v3's sparse U-Net imports it; this engine loads MoGe v1, so it never runs. Keep it that way. The same install also pulled `pipeline`, `utils3d-moge` and `moderngl`, which the lock doesn't list.
- **GPU safety.** Use the stock image, the pinned commits and the locks. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- No script downloads the weights; the repo is gated, and the registry records its revision as `main`.
- `locks/sam3do.txt` pins this venv's direct packages only. MoGe pins FlexGEMM, `pipeline` and `utils3d-moge` to commits itself; the rest of the transitive packages (`moderngl`, vtk, matplotlib, …) are resolved fresh on each install.
- pytorch3d is built from source on every fresh install (no wheel is kept).
