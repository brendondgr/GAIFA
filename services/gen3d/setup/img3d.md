<!-- aihub-setup
id = "gen3d-img3d"
title = "Hunyuan3D 2.1 (3D Generate)"
models = ["3d/Hunyuan3D-2.1"]
scan = []
summary = "3D Generate: one picture to a watertight mesh with Hunyuan3D 2.1 (best for characters)"
gpu = true
disk_gb = 3
needs = ["podman", "git"]
after = ["gen3d-cubeart"]
check = ".venv/bin/python -m gen3d.doctor | grep -Eq 'ok +Hunyuan3D 2.1 \\(image engine\\) +ready'"

[[steps]]
run = "scripts/install-runtime.sh"
what = "the runtime installer again (it skips what gen3d-cubeart built): clones Hunyuan3D-2.1 at the pinned commit and builds runtime/img3d/.venv inside the image, layered on CubeArt's (about 3 GB, no GPU devices passed)"

[[suggest]]
name = "Hunyuan3D 2.1 (shape)"
repo = "tencent/Hunyuan3D-2.1"
files = ["hunyuan3d-dit-v2-1/model.fp16.ckpt", "hunyuan3d-vae-v2-1/model.fp16.ckpt", "hunyuan3d-dit-v2-1/config.yaml",
  "hunyuan3d-vae-v2-1/config.yaml", "LICENSE", "Notice.txt", "README.md"]
dest = "3d/Hunyuan3D-2.1"
kind = "3d"
size_gb = 8.02
good_for = "the engine's shape model and VAE (the repo's texture model isn't used)"
licence = "Tencent Hunyuan 3D 2.1 Community Licence (excludes the EU, the UK and South Korea)"
required = true
-->

# Hunyuan3D 2.1: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

One of 3D Generate's picture engines (`engine = hunyuan21`): Tencent's **Hunyuan3D 2.1**, shape only (no texture), from one picture to a watertight mesh. It's the one to pick for characters. It runs in a `gen3d-worker-*` container of the ROCm image, with the venv `runtime/img3d/.venv` and the upstream code in `runtime/hunyuan3d-2.1/` (only `hy3dshape/` is used). The same worker also reduces meshes from other engines to a face budget (`target_faces`). The server venv, the image and how the venvs are layered are in [cubeart.md](cubeart.md). **Licence:** the Tencent Hunyuan 3D 2.1 Community Licence, which excludes the EU, the UK and South Korea.

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest` at `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2`; torch `2.13.0a0+rocm7.14.0a20260529` from its `/opt/venv` (see [cubeart.md](cubeart.md#tested-with)) |
| `runtime/img3d/.venv` | Python 3.13.13 inside the image; `_layers.pth` puts CubeArt's site-packages, then `/opt/venv`'s, on its path (torch, diffusers, transformers, trimesh and pymeshlab come from there); its own packages are exactly `locks/img3d.txt`: timm 1.0.30, fast-simplification 0.2.0 |
| Upstream code | https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git at `82920d643c0dc2f7bfd7255f45f62d386edfe60c` (2025-10-17), no local changes |
| Weights | `tencent/Hunyuan3D-2.1` (revision `main`, recorded 2026-10) in `data/models/3d/Hunyuan3D-2.1/`: `hunyuan3d-dit-v2-1/model.fp16.ckpt` and `hunyuan3d-vae-v2-1/model.fp16.ckpt` with their `config.yaml`, 8.0 GB |

## Prerequisites

- [cubeart.md](cubeart.md): the server venv, the pulled image, and `runtime/CubeArt/.venv` (this venv is layered on it).
- About 8 GB for the weights, and 14 GB of free memory when it runs (`memory_gb = 14` in `gen3d/engines.py`).

## Install

```bash
uvx --from huggingface_hub hf download tencent/Hunyuan3D-2.1 hunyuan3d-dit-v2-1/model.fp16.ckpt hunyuan3d-vae-v2-1/model.fp16.ckpt LICENSE Notice.txt README.md hunyuan3d-dit-v2-1/config.yaml hunyuan3d-vae-v2-1/config.yaml --local-dir data/models/3d/Hunyuan3D-2.1
```

From the project folder: the shape model and its VAE (8.0 GB). The repo also holds the texture (paint) model, which isn't used; this command leaves it out. Nothing in git downloads these weights; they're the block's required suggestion.

```bash
services/gen3d/scripts/install-runtime.sh
```

After CubeArt (see [cubeart.md](cubeart.md#install)), it clones Hunyuan3D-2.1 into `runtime/hunyuan3d-2.1/` and checks out the commit above, then inside the image (no GPU devices passed) makes `runtime/img3d/.venv`, writes `_layers.pth` and `constraints.txt` (the image's torch family), installs `locks/img3d.txt`, and checks `import hy3dshape, timm, fast_simplification` (`img3d ok`). It wasn't re-run for this doc.

## Choosing models

Hunyuan3D 2.1 runs fixed weights: the shape model and its VAE from `tencent/Hunyuan3D-2.1`, in `data/models/3d/Hunyuan3D-2.1/`, which the worker loads by these paths (`gen3d/engines.py`). There's nothing to swap. The engine is optional within 3D Generate: without it, the engine picker lists `hunyuan21` with what's missing, and the other engines are unaffected.

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| Hunyuan3D 2.1, shape only (`tencent/Hunyuan3D-2.1`, 7 files) | 8.02 GB | the engine's weights | Tencent Hunyuan 3D 2.1 Community (not the EU, UK or South Korea) | yes, for this engine |

## Configuration

Nothing of its own: the worker reads `GEN3D_WEIGHTS` and `GEN3D_RUNTIME` (set by the server) and runs with `PYTHONPATH=runtime/hunyuan3d-2.1/hy3dshape`. The engine's options (steps, guidance, octree resolution, face budget) are per job, in the job's `hunyuan21` group (`Hunyuan21Options` in `gen3d/image_options.py`; the API schema and the `make_3d` tool list them).

## Check it works

```bash
cd services/gen3d && .venv/bin/python -m gen3d.doctor
```

Checks files only. Expect `ok      Hunyuan3D 2.1 (image engine)     ready`. When something is missing, the line lists it (`runtime/hunyuan3d-2.1/hy3dshape/hy3dshape`, `runtime/img3d/.venv`, or the two `models/3d/Hunyuan3D-2.1/…` checkpoints) with the fix.

```bash
git -C services/gen3d/runtime/hunyuan3d-2.1 rev-parse HEAD
```

Expect `82920d643c0dc2f7bfd7255f45f62d386edfe60c`.

## What to look for

- **fp16 on the GPU** (`dtype=torch.float16`, as upstream ships `model.fp16.ckpt`).
- **FlashVDM** is switched on through the VAE (`enable_flashvdm_decoder`); the pipeline's own `enable_flashvdm` looks for a turbo VAE that 2.1 doesn't have.
- **The layer order matters.** `img3d` sits on CubeArt's venv, which sits on `/opt/venv`; rebuilding CubeArt's venv against another image changes what this one imports. Rebuild them together with `install-runtime.sh`.
- **GPU safety.** Use the stock image, the pinned commit and the locks. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- No script downloads the weights, and the registry records the revision as `main`, not a commit.
- The lock lists only the two packages this venv adds; everything else comes from the layers below it.
