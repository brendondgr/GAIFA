<!-- aihub-setup
id = "gen3d"
title = "3D Generate: the server, the image and the runtimes"
models = []
scan = []
summary = "3D Generate: text or a picture to 3D meshes, named parts and game rigs (the server, the ROCm image and every engine's runtime; the engines' weights are their own setups)"
gpu = true
disk_gb = 6.5
images = { "docker.io/kyuz0/amd-strix-halo-comfyui" = 15.1 }
needs = ["podman", "git", "uv"]
after = ["comfyui"]
check = "out=$(.venv/bin/python -m gen3d.doctor); for l in 'podman' 'ROCm image' 'upstream clone' 'CubePart code' 'worker venv'; do grep -Eq \"ok +$l\" <<<\"$out\" || exit 1; done; ! grep 'image engine)' <<<\"$out\" | grep -q ' runtime/'"

[[steps]]
run = "aihub install gen3d"
what = "makes .venv/ in this folder with Python 3.12 from requirements.txt: the server only (about 50 MB, a minute)"

[[steps]]
run = "podman image exists docker.io/kyuz0/amd-strix-halo-comfyui:latest || { podman pull docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 && podman tag docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 docker.io/kyuz0/amd-strix-halo-comfyui:latest; }"
what = "the ROCm image for gfx1151 (15.1 GB, shared with the comfy mod, whose setup runs first and pulls it), pulled by the digest in Tested with only when :latest is missing, then tagged :latest: the worker venvs are built on its torch, so a newer :latest wouldn't match them"

[[steps]]
run = "scripts/install-runtime.sh"
what = "clones every local engine's code at its pinned commit (Roblox/cube, Hunyuan3D 2.1, SAM 3D Objects, DINOv2) and builds all three worker venvs inside the image (runtime/CubeArt, runtime/img3d, runtime/sam3do: about 6.5 GB, pytorch3d from source, no GPU devices passed); no weights: each engine's licence applies when you use that engine, and the engine's own setup asks about it before its weights download; time not measured here"
-->

# 3D Generate: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The 3D Generate mod (`gen3d`, port 5050) has a server and GPU workers. The server, `python -m gen3d`, runs in `.venv/` in this folder and never touches the GPU. Each job's GPU work runs in a worker: a `podman run -i` of the ROCm image (`gen3d-worker-*`), with one of three venvs from `runtime/` layered on the image's own torch. This doc is the base every engine needs: the server venv, the image, and every local engine's code and venv, which `scripts/install-runtime.sh` builds in one run. It installs no weights, so on its own the mod runs but no engine is ready; `rig` and `preview` run on the CPU. The engines, each with its licence question and its weights, are their own setups:

| Engine | Setup | Runs |
|---|---|---|
| Cube3D and CubePart (text to mesh, named parts) | [cubeart.md](cubeart.md) | here, `runtime/CubeArt/` |
| Hunyuan3D 2.1 (one picture, characters) | [img3d.md](img3d.md) | here, `runtime/img3d/` |
| SAM 3D Objects (one picture, the quickest) | [sam3do.md](sam3do.md) | here, `runtime/sam3do/` |
| TRELLIS.2, SAM 3D Body | [ComfyUI](../../comfy/setup/comfyui.md) | ComfyUI packs in the comfy mod |

**Licences:** `install-runtime.sh` always clones the code of all three local engines, each under its own licence (Roblox's Cube3D Research-Only RAIL-MS, Tencent's Hunyuan 3D 2.1 Community License, Meta's SAM Licence). Each applies when you use that engine; its setup quotes it and asks before downloading its weights. Choosing `gen3d` in `aihub setup` sets up this base only; add the engines by their setup ids (`gen3d-cubeart`, `gen3d-img3d`, `gen3d-sam3do`).

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Server `.venv` | Python 3.12.13 (uv-managed), fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.13.5, pillow 12.3.0 |
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest`, digest `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2` (built 2026-05-29, 15.1 GB; the same image as ComfyUI) |
| The image's `/opt/venv` | Python 3.13.13, `torch==2.13.0a0+rocm7.14.0a20260529`, `torchvision==0.28.0a0+rocm7.14.0a20260529`, `torchaudio==2.11.0+rocm7.14.0a20260529`, `triton==3.7.0+gita0718cfe.rocm7.14.0a20260529`, numpy 2.4.3, diffusers 0.38.0 (each venv's `constraints.txt` records these) |
| Worker venvs | `runtime/CubeArt/.venv` (`locks/cubeart.txt`), `runtime/img3d/.venv` (`locks/img3d.txt`), `runtime/sam3do/.venv` (`locks/sam3do.txt`); each engine's doc lists its own packages and commits |
| Blender (previews) | 5.2.2 LTS at `~/.local/bin/blender` |

## Prerequisites

- [host.md](../../../docs/setup/host.md): podman, the `video` and `render` groups, the kernel settings in [§1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory) with the IOMMU on, and optionally Blender at `~/.local/bin/blender` for previews.
- git, uv, and about 6.5 GB for the server and the venvs (the image is 15.1 GB more, counted once with ComfyUI's).
- [ComfyUI](../../comfy/setup/comfyui.md) first (`after = ["comfyui"]`): two of 3D Generate's engines, TRELLIS.2 and SAM 3D Body, run as ComfyUI packs in the comfy mod, and its setup pulls the image this one shares. So choosing 3D Generate in `aihub setup` sets up ComfyUI too.

## Install

```bash
aihub install gen3d
```

Runs `aihub-install.sh`: makes `.venv/` with Python 3.12 from `requirements.txt` (the server only).

```bash
podman image exists docker.io/kyuz0/amd-strix-halo-comfyui:latest || { podman pull docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 && podman tag docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 docker.io/kyuz0/amd-strix-halo-comfyui:latest; }
```

The ROCm image (15.1 GB), shared with the comfy mod, pulled by the digest in Tested with only when `:latest` is missing, then tagged `:latest` (the name `install-runtime.sh` and the workers use, `GEN3D_IMAGE`'s default): the worker venvs are built on its torch, and a newer `:latest` wouldn't match them. The installer stops without it. If that digest can't be pulled any more, see ComfyUI's What to look for ("The image's digest is the pin").

```bash
services/gen3d/scripts/install-runtime.sh
```

Builds all three worker venvs; it needs the image but not the weights. CubeArt: clones Roblox/cube into `runtime/CubeArt/cube/` at its pinned commit, links `runtime/CubeArt/weights` to `data/models/3d`, then inside the image (`podman run --rm`, no GPU devices passed) makes `runtime/CubeArt/.venv` with the image's Python 3.13, adds a `.pth` pointing at `/opt/venv`'s site-packages, writes the image's torch/torchvision/torchaudio/triton/numpy versions to `constraints.txt` so pip never replaces them, installs `locks/cubeart.txt`, and checks the imports. Then the image engines: clones Hunyuan3D 2.1, SAM 3D Objects and DINOv2 at their commits, makes `runtime/img3d/.venv` (layered on CubeArt's) and `runtime/sam3do/.venv` (layered on img3d's), builds pytorch3d from source (CPU ops only), and checks `img3d ok` and `sam3do ok`. Re-running is safe; finished steps are skipped. It wasn't re-run for this doc.

## Choosing models

None here: each engine runs fixed weights, chosen in its own setup ([cubeart.md](cubeart.md#choosing-models), [img3d.md](img3d.md#choosing-models), [sam3do.md](sam3do.md#choosing-models)), and TRELLIS.2's and SAM 3D Body's belong to ComfyUI packs ([comfyui.md](../../comfy/setup/comfyui.md#choosing-models)). Without an engine's weights, the engine picker lists it with what's missing, and the others are unaffected. The weights go in `data/models/3d/<folder>/` (`GEN3D_WEIGHTS`, mounted read-only into the workers).

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
cd services/gen3d && .venv/bin/python -m gen3d.doctor
```

Checks files and podman only; nothing loads. For this base, expect `ok` on `upstream clone (cube/)`, `CubePart code`, `worker venv (.venv)`, `podman` and `ROCm image`, and no `runtime/…` in a `MISSING … (image engine)` line (those lines also list the engine's weights, which come with its setup). The setup's `check` reads exactly that. The weight lines are `MISSING` until the engines' setups run; with every engine set up, expect 17 `ok` lines and exit 0 (2026-10-21).

```bash
aihub check gen3d --start
```

Starts the server if it's stopped (a stopped mod's live checks are skipped; the server never touches the GPU) and checks it. Expect `gen3d: all checks passed` (2026-10-21, with every engine set up).

```bash
curl -s http://127.0.0.1:7000/api/s/gen3d/v1/status
```

A GET, so nothing loads. Expect `"loaded": false`, `"worker": {"state": "stopped", …}` while idle, and the stat `{"label": "Previews", "value": "CPU", …}`.

## What to look for

- **The worker runs in the image, the server on the host.** The venvs under `runtime/` point at the image's `/usr/bin/python3.13` and `/opt/venv`; they can't run on the host.
- **The layer order matters.** `sam3do` sits on `img3d`, which sits on CubeArt's venv, which sits on `/opt/venv`; rebuilding one against another image changes what the others import. Rebuild them together with `install-runtime.sh`.
- **Mounts must be real paths.** The worker mounts `runtime/`, the jobs folder and the weights by their resolved paths; a symlink pointing outside a mount is broken inside the container.
- **Previews run on the CPU by default** (since 2026-10-21): the one GPU fault in a night of 3D runs was Blender drawing a preview. With `cpu`, Blender starts with `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` and refuses to render on anything but llvmpipe or softpipe.
- **Worker settings** (`gen3d/worker.py`): `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`, `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`, `ROCPROFILER_REGISTER_ENABLED=0`, `--network none`, `HF_HUB_OFFLINE=1` (workers never download), and `HSA_OVERRIDE_GFX_VERSION` unset.
- **Memory:** the Quality preset peaks at about 52 GB (`[memory] estimate_gb`); out of memory is the usual cause of "worker exited" when ComfyUI or an LLM holds the unified memory.
- **GPU safety.** Use the stock image and the locks. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- The image is pinned only by the setup step's digest; the code runs `:latest` (`GEN3D_IMAGE`), and the venvs' `constraints.txt` record the torch they were built against.
- `install-runtime.sh` always clones and builds all three local engines, also for a person who wants only one; their licences still apply only when used.
- `install-runtime.sh` checks out Roblox/cube's commit only on the first clone.
- CubeArt's own scripts (`cubeart`, `cube-run`, `scripts/`) in `runtime/CubeArt/` came from the old `~/Models/3D/CubeArt` and aren't recreated; the mod doesn't need them.
