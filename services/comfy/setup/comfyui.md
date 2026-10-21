<!-- aihub-setup
id = "comfyui"
title = "ComfyUI in the Strix Halo toolbox"
models = ["comfyui/**"]
scan = ["workflows/*/workflow.json"]
-->

# ComfyUI: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

Two environments. The adapter (`python -m comfy`, port 5070) runs in `.venv/` in this folder and never touches the GPU. ComfyUI itself (port 8199) runs in a podman toolbox named `strix-halo-comfyui`, made from kyuz0's ROCm image for gfx1151. `bin/comfyui start` creates the toolbox when it's missing and launches ComfyUI in it; the hub does this when the mod loads. Every image, edit and video pack in `workflows/` needs this environment, and so do two of 3D Generate's engines (TRELLIS.2 and SAM 3D Body, packs `trellis2-*` and `sam3d-body`). The pack format is in [docs/workflows.md](../../../docs/workflows.md).

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151, podman 5.8.9, toolbox 0.3):

| Part | Version |
|---|---|
| Image | `docker.io/kyuz0/amd-strix-halo-comfyui:latest`, digest `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2` (image id `0708f33c4c3e`, built 2026-05-29, 15.1 GB) |
| Inside the image | Python 3.13, torch `2.13.0a0+rocm7.14.0a20260529`, ROCm `7.14.0a20260529` (`rocm-sdk-libraries-gfx1151`), ComfyUI **0.22.0** |
| The toolbox container | created 2026-07-25 from that image; ComfyUI in it updated in place to **0.37.0** (commit `93810483a4739a1588236919a3128d3070244146`, a fast-forward of `/opt/ComfyUI` on 2026-09-24), `comfyui_manager` 4.2.2, `comfyui-frontend-package` 1.53.6 |
| Adapter `.venv` | Python 3.12.13 (uv-managed), fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, websockets 17.2, pydantic 2.13.5, pillow 12.3.0, tomlkit 0.15.1 |

The container's versions were read from its overlay layer while it was stopped (`podman unshare`, see Check it works), not from a running ComfyUI.

**Custom nodes** in `custom_nodes/` (gitignored; each a git checkout, none with local changes):

| Folder | Repo | Commit (date) |
|---|---|---|
| `ComfyUI-GGUF` | https://github.com/leejet/ComfyUI-GGUF | `edd981b10e107d3b8f58e16c498f2d08f631bc47` (2026-09-22) |
| `ComfyUI-KJNodes` | https://github.com/kijai/ComfyUI-KJNodes.git | `7f43f2ce910a27971bdbbf3fb5a52081457f32e2` (2026-06-18) |
| `ComfyUI-VideoHelperSuite` | https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git | `4ee72c065db22c9d96c2427954dc69e7b908444b` (2026-05-13) |
| `ComfyUI-WanVideoWrapper` | https://github.com/kijai/ComfyUI-WanVideoWrapper.git | `088128b224242e110d3906c6750e9a3a348a659b` (2026-05-24) |
| `rgthree-comfy` | https://github.com/rgthree/rgthree-comfy.git | `27b4f4cdcf3b127c29d5d8135ac1536ecbd4c383` (2026-06-20) |

AIHub's own nodes are tracked in git: `nodes/aihub_nodes/` (a faster Qwen-VL patch embed, a Qwen-Image 2.1 text encode that can skip the negative, a SAM 3D Body dtype fix). ComfyUI loads them with the custom nodes.

## Prerequisites

- [host.md](../../../docs/setup/host.md): podman, toolbox, the `video` and `render` groups, and the kernel settings in [§1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory), with the IOMMU on.
- **The clone sits under `$HOME`.** The toolbox shares your home folder, and ComfyUI reads models, custom nodes, `extra_model_paths.yaml` and `nodes/` from the project through that share, at the same paths.
- About 15 GB for the image, plus the models (64 GB for the 15 ComfyUI models in the registry today).
- A Hugging Face token only for gated models ([host.md §6](../../../docs/setup/host.md#6-accounts-and-licences)).

## Install

```bash
aihub install comfy
```

Runs `install.sh`: makes `.venv/` with Python 3.12 from `requirements-dev.txt` (the adapter only).

```bash
podman pull docker.io/kyuz0/amd-strix-halo-comfyui:latest
```

Pulls the ROCm image (15.1 GB). 3D Generate's workers use the same image. `:latest` moves; compare the digest with the one above (`podman image inspect … --format '{{.Digest}}'`).

The toolbox is created by the first `bin/comfyui start` (or the first load from the hub), with `toolbox create strix-halo-comfyui --image <image> -- --device /dev/dri --device /dev/kfd --group-add video --group-add render --security-opt seccomp=unconfined`. On each start it pip-installs `gguf` and `comfyui_manager` into the container's venv if they're missing (never torch), then launches:

```
python main.py --listen 127.0.0.1 --port 8199 --extra-model-paths-config <mod>/extra_model_paths.yaml
  --output-directory <AIHub>/outputs/comfy --input-directory <mod>/input --user-directory <mod>/user
  --database-url sqlite:///<mod>/user/comfyui.db --disable-mmap --fp32-vae --enable-manager
```

with `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`. `--disable-mmap` avoids ROCm's slow mmap path above 64 GB, which hangs model loading (kyuz0's default for gfx1151); `--fp32-vae` keeps the FLUX.2 small-decoder VAE numerically safe; `--enable-manager` loads ComfyUI-Manager 4.x (a pip package, not a `custom_nodes` checkout). `--listen` must stay a loopback address: ComfyUI-Manager refuses node installs otherwise.

**Custom nodes.** Nothing in AIHub installs them, because they run code. One clone per node, at the commit above:

```bash
git clone https://github.com/leejet/ComfyUI-GGUF services/comfy/custom_nodes/ComfyUI-GGUF && git -C services/comfy/custom_nodes/ComfyUI-GGUF checkout edd981b10e107d3b8f58e16c498f2d08f631bc47
```

```bash
git clone https://github.com/kijai/ComfyUI-KJNodes.git services/comfy/custom_nodes/ComfyUI-KJNodes && git -C services/comfy/custom_nodes/ComfyUI-KJNodes checkout 7f43f2ce910a27971bdbbf3fb5a52081457f32e2
```

```bash
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git services/comfy/custom_nodes/ComfyUI-VideoHelperSuite && git -C services/comfy/custom_nodes/ComfyUI-VideoHelperSuite checkout 4ee72c065db22c9d96c2427954dc69e7b908444b
```

```bash
git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git services/comfy/custom_nodes/ComfyUI-WanVideoWrapper && git -C services/comfy/custom_nodes/ComfyUI-WanVideoWrapper checkout 088128b224242e110d3906c6750e9a3a348a659b
```

```bash
git clone https://github.com/rgthree/rgthree-comfy.git services/comfy/custom_nodes/rgthree-comfy && git -C services/comfy/custom_nodes/rgthree-comfy checkout 27b4f4cdcf3b127c29d5d8135ac1536ecbd4c383
```

Their Python dependencies go into the container's venv. Here they were installed through ComfyUI-Manager (in ComfyUI: Manager → Custom Nodes Manager, or Install via Git URL), which runs each node's `requirements.txt`; installing through the Manager and then checking out the commit above works too. Only some packs need them (GGUF loaders, KJNodes, the Wan wrapper); the Qwen-Image 2.1, TRELLIS.2 and SAM 3D Body packs use core nodes only.

**Models** go in `data/models/comfyui/<folder>/` (`checkpoints`, `diffusion_models`, `text_encoders`, `vae`, `loras`, …). Three ways in:
- the page: a pack's review screen has a **Download** button for each missing file whose workflow recorded a URL (`POST /v1/downloads`: into `<folder>/<name>.part`, renamed when done, then registered with the hub; `HF_TOKEN` is sent only to huggingface.co);
- `scripts/download_qwen_image_2.1.sh` and `scripts/download_qwen_image_2.1_turbo.sh` (the Qwen-Image 2.1 packs; resumable, sha256-checked);
- each model's doc in [docs/setup/models/](../../../docs/setup/models/) has its fetch command.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `COMFY_URL` | `service.toml` | yes (set) | ComfyUI, `http://127.0.0.1:8199` |
| `COMFY_MODELS` | `service.toml` | yes (set) | `{models}/comfyui`; passed into the toolbox and read by `extra_model_paths.yaml` |
| `COMFY_CONTROL` | `service.toml` | yes (set) | `bin/comfyui`, which the adapter calls to start and stop ComfyUI |
| `COMFY_DATA`, `COMFY_DB`, `COMFY_OUTPUTS`, `COMFY_WORKFLOWS` | `service.toml` | yes (set) | the adapter's cache and ComfyUI's log (`data/`), `comfy.db`, `outputs/comfy`, the packs |
| `COMFY_IDLE_UNLOAD_S` | from `[memory] idle_unload_s` | optional | stop ComfyUI after this many idle seconds (600); the toolbox keeps running |
| `COMFY_TOOLBOX`, `COMFY_PORT_UI` | env of `bin/comfyui` | optional | the container name and ComfyUI's port |
| `HF_TOKEN` | env | optional | gated Hugging Face downloads from the page |

`extra_model_paths.yaml` maps ComfyUI's model folders onto `$COMFY_MODELS` (`is_default: true`, so downloads made in ComfyUI land there too) and adds `custom_nodes/` and `nodes/` as node folders. `[models] dirs = ["comfyui"]` makes the registry list every file there as used by `comfy`.

## Check it works

```bash
aihub check comfy
```

With the mod stopped (as on 2026-10-21), expect `ok` for manifest, command, port and page and the live checks skipped: `comfy: no failures, but 6 checks skipped`. The live checks need the adapter running; this wasn't run here while GPU work is paused.

```bash
services/comfy/bin/comfyui status
```

Expect the image, the mod, models and outputs paths, then `Toolbox: stopped`, `ComfyUI: not running`, `Web UI : not responding` when it isn't loaded (it reads podman's state only).

```bash
services/comfy/bin/comfyui workflows check qwen21-turbo-t2i trellis2-shape sam3d-body
```

Expect `qwen21-turbo-t2i: ready`, `trellis2-shape: ready`, `sam3d-body: ready`. `check --all` lists every pack; a pack whose models aren't on disk shows `broken` with one `missing_model` line per file. `missing_node` means a node type isn't installed: the fix line names the custom-node package when the workflow recorded it (install it as above, then reload comfy). `missing_model` names the file and its folder under `data/models/comfyui/`, with the URL when the workflow recorded one. The check reads the node list cached at ComfyUI's last start (`data/object_info.json`), so it works while ComfyUI is down. The other problem codes are in [docs/workflows.md §7](../../../docs/workflows.md#7-problems-and-their-fixes).

```bash
podman image inspect docker.io/kyuz0/amd-strix-halo-comfyui:latest --format '{{.Digest}} {{.Created}}'
```

Expect `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 2026-05-29 09:13:12…`.

```bash
podman unshare cat "$(podman container inspect strix-halo-comfyui --format '{{.GraphDriver.Data.UpperDir}}')/opt/ComfyUI/comfyui_version.py"
```

Reads ComfyUI's version from the container's own layer without starting it. Expect `__version__ = "0.37.0"`. (On a container that was never updated the file isn't in that layer; then the version is the image's, 0.22.0.)

## What to look for

- **The container's ComfyUI is newer than the image.** `/opt/ComfyUI` was updated in place (0.22.0 → 0.37.0). TRELLIS.2 and SAM 3D Body are core nodes only since then (`comfy_extras/nodes_trellis2.py`, `nodes_sam3d_body.py` aren't in the image). **Recreating the toolbox from the image loses them**, and with them the `trellis2-*` and `sam3d-body` packs and two of 3D Generate's engines. That includes `bin/comfyui update`, which pulls `:latest` and recreates the container, and `podman rm strix-halo-comfyui`. On a new machine, update ComfyUI inside the new toolbox to the commit above (from ComfyUI-Manager, or `git` in `/opt/ComfyUI`) and check the packs again.
- **A wedged container** (seen 2026-10-10 and 2026-10-21): podman says it's Up, but `podman exec` fails with "crun: the container … is not running", so ComfyUI can't be started or stopped inside it. `bin/comfyui start` and `quit` now recover by themselves: they stop ComfyUI's process from the host, then stop and start the container. If exec still fails, they stop with a message; check `podman ps -a`.
- **`--disable-mmap` stays.** Without it, loading goes through ROCm's slow mmap path once more than 64 GB is mapped, and can hang.
- **Hybrid scaled-FP8 files** (for example abenzerps' Qwen-Image 2.1 Turbo FP8) render noise until their metadata is fixed with `scripts/fix_fp8_quant_metadata.py SRC DEST`.
- **GPU safety.** Use the stock image and the pinned nodes. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for) before running anything else.

## Known gaps

- Nothing installs the custom nodes or their Python packages; the clones above and ComfyUI-Manager are manual.
- Nothing pins the image or ComfyUI's version in code: `bin/comfyui` uses `:latest`, and the in-place update to 0.37.0 isn't scripted.
- The Z-Image and Wan 2.1 packs (`zimage-turbo`, `zimage-intorealism`, `qwen-edit-refine-zimage`, `wan21-t2v`, `wan21-i2v`) have `agent = false`: their models were deleted on 2026-10-20 to free disk space. The workflows are kept; `check` shows them `broken` until the models are downloaded again. The Flux 2 Klein, Krea 2 and Qwen-Image-Edit packs are also `broken` here (their models aren't on disk) but still have the agent on; a broken pack isn't offered to it.
