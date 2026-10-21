<!-- aihub-setup
id = "comfyui"
title = "ComfyUI in the Strix Halo toolbox"
models = ["comfyui/**"]
scan = ["workflows/*/workflow.json"]
summary = "Images & Video: ComfyUI in a ROCm toolbox, running any workflow pack (images, edits, video, and two of 3D Generate's engines)"
gpu = true
disk_gb = 4
images = { "docker.io/kyuz0/amd-strix-halo-comfyui" = 15.1 }
needs = ["podman", "toolbox", "git"]
check = "aihub check comfy --start && podman image exists docker.io/kyuz0/amd-strix-halo-comfyui:latest"

[[steps]]
run = "aihub install comfy"
what = "makes .venv/ in this folder with Python 3.12 from requirements-dev.txt: the adapter only (about 50 MB, a minute)"

[[steps]]
run = "podman image exists docker.io/kyuz0/amd-strix-halo-comfyui:latest || { podman pull docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 && podman tag docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 docker.io/kyuz0/amd-strix-halo-comfyui:latest; }"
what = "the ROCm image for gfx1151 (15.1 GB, shared with 3D Generate), pulled by the digest in Tested with only when :latest is missing, then tagged :latest, the name bin/comfyui makes the toolbox from on ComfyUI's first start"

[[steps]]
run = '''
clone() { [ -d "custom_nodes/$1/.git" ] || git clone "$2" "custom_nodes/$1"; git -C "custom_nodes/$1" checkout --quiet "$3"; }
clone ComfyUI-GGUF https://github.com/leejet/ComfyUI-GGUF edd981b10e107d3b8f58e16c498f2d08f631bc47
clone ComfyUI-KJNodes https://github.com/kijai/ComfyUI-KJNodes.git 7f43f2ce910a27971bdbbf3fb5a52081457f32e2
clone ComfyUI-VideoHelperSuite https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git 4ee72c065db22c9d96c2427954dc69e7b908444b
clone ComfyUI-WanVideoWrapper https://github.com/kijai/ComfyUI-WanVideoWrapper.git 088128b224242e110d3906c6750e9a3a348a659b
clone rgthree-comfy https://github.com/rgthree/rgthree-comfy.git 27b4f4cdcf3b127c29d5d8135ac1536ecbd4c383
'''
what = "clones the five custom nodes into custom_nodes/ at the commits in Tested with (about 85 MB); optional: a no skips only this step; their Python packages go into the toolbox by hand once it exists (Install, Updating ComfyUI in the toolbox)"
ask = "Custom nodes are third-party code that runs inside ComfyUI. Clone ComfyUI-GGUF, KJNodes, VideoHelperSuite, WanVideoWrapper and rgthree at the pinned commits? A no skips only the nodes, not ComfyUI: then the qwen21-* packs (ComfyUI-GGUF; the Turbo ones also KJNodes) and the scail2-* video packs (VideoHelperSuite) won't run; packs with core nodes only, such as trellis2-* and sam3d-body, still do."
optional = true

[[suggest]]
name = "Qwen-Image 2.1 Turbo Q8_0 (1 of 2: the diffusion model)"
repo = "abenzerps/Qwen-Image-2.1-Turbo-Quantized"
files = ["qwen-image-2.1-turbo-Q8_0.gguf"]
dest = "comfyui/diffusion_models"
kind = "image"
size_gb = 7.59
good_for = "the qwen21-turbo-* packs (instruction edits with references, text to image, background removal), only together with 2 of 2, the encoder and VAE; needs ComfyUI-GGUF; Qwen Research Licence: research or evaluation only, no commercial use"
licence = "Qwen Research Licence (research or evaluation only; https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE)"

[[suggest]]
name = "Qwen-Image 2.1 text encoder and VAE (2 of 2)"
repo = "Comfy-Org/Qwen-Image-2.1"
files = ["text_encoders/qwen3vl_8b_bf16.safetensors", "vae/qwen_image_2.1_vae_bf16.safetensors"]
dest = "comfyui"
kind = "text-encoder"
size_gb = 18.21
good_for = "the Qwen3-VL 8B encoder and the VAE that every Qwen-Image 2.1 pack needs, Turbo or not: choose it with 1 of 2 (alone it runs nothing); Qwen Research Licence: research or evaluation only, no commercial use"
licence = "Qwen Research Licence (research or evaluation only; https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE)"

[[suggest]]
name = "TRELLIS.2 (shape)"
repo = "Comfy-Org/TRELLIS.2"
files = ["diffusion_models/trellis_2_bf16.safetensors", "vae/trellis_2_shape_vae_bf16.safetensors", "clip_vision/dino_v3_vit_l.safetensors"]
dest = "comfyui"
kind = "image"
size_gb = 12.65
good_for = "picture to 3D: the trellis2-* packs, which are also 3D Generate's trellis2 engine; needs ComfyUI newer than the image's 0.22"
licence = "MIT (TRELLIS.2); DINOv3 Licence (the image encoder)"
next = "TRELLIS.2 (and SAM 3D Body) need ComfyUI 0.37.0, newer than the image's 0.22.0: after the first services/comfy/bin/comfyui start has made the toolbox, update ComfyUI inside it to commit 93810483a473 with the two commands in services/comfy/setup/comfyui.md (Install, Updating ComfyUI in the toolbox), then check the packs with services/comfy/bin/comfyui workflows check trellis2-shape sam3d-body"
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
- About 19 GB: the image (15.1 GB), the nodes and the adapter (0.15 GB), and the toolbox container's own layer, which grows with what's installed into it (3.95 GB here, with the in-place ComfyUI update and the nodes' Python packages); plus the models of the packs you use (Choosing models).
- A Hugging Face token only for gated models ([host.md §6](../../../docs/setup/host.md#6-accounts-and-licences)).

## Install

```bash
aihub install comfy
```

Runs `install.sh`: makes `.venv/` with Python 3.12 from `requirements-dev.txt` (the adapter only).

```bash
podman image exists docker.io/kyuz0/amd-strix-halo-comfyui:latest || { podman pull docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 && podman tag docker.io/kyuz0/amd-strix-halo-comfyui@sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 docker.io/kyuz0/amd-strix-halo-comfyui:latest; }
```

Pulls the ROCm image (15.1 GB) **by the digest in Tested with**, not whatever `:latest` is today, and tags it `:latest`: `bin/comfyui` creates the toolbox from `docker.io/kyuz0/amd-strix-halo-comfyui:latest`, and 3D Generate's workers run the same name. It does nothing when `:latest` is already there; compare its digest with the one above (`podman image inspect … --format '{{.Digest}}'`). 3D Generate's doc runs the same command, so the image is pulled once.

The toolbox is created by the first `bin/comfyui start` (or the first load from the hub), with `toolbox create strix-halo-comfyui --image <image> -- --device /dev/dri --device /dev/kfd --group-add video --group-add render --security-opt seccomp=unconfined`. On each start it pip-installs `gguf` and `comfyui_manager` into the container's venv if they're missing (never torch), then launches:

```
python main.py --listen 127.0.0.1 --port 8199 --extra-model-paths-config <mod>/extra_model_paths.yaml
  --output-directory <AIHub>/outputs/comfy --input-directory <mod>/input --user-directory <mod>/user
  --database-url sqlite:///<mod>/user/comfyui.db --disable-mmap --fp32-vae --enable-manager
```

with `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`. `--disable-mmap` avoids ROCm's slow mmap path above 64 GB, which hangs model loading (kyuz0's default for gfx1151); `--fp32-vae` keeps the FLUX.2 small-decoder VAE numerically safe; `--enable-manager` loads ComfyUI-Manager 4.x (a pip package, not a `custom_nodes` checkout). `--listen` must stay a loopback address: ComfyUI-Manager refuses node installs otherwise.

**Custom nodes.** They run code, so nothing in AIHub installs them without asking: `aihub setup` asks before the block's third step clones them. By hand, for each row of the custom-node table in Tested with:

```bash
git clone <repo> services/comfy/custom_nodes/<folder> && git -C services/comfy/custom_nodes/<folder> checkout <commit>
```

Their Python dependencies go into the container's venv (the second command under "Updating ComfyUI in the toolbox" below; here they were installed through ComfyUI-Manager, Manager → Custom Nodes Manager, which runs the same `requirements.txt`). The step is optional: a "no" skips only the nodes. Only some packs need them: the Qwen-Image 2.1 packs load their diffusion model with ComfyUI-GGUF's `UnetLoaderGGUF` (and the Turbo ones their VAE with KJNodes' `VAELoaderKJ`), the `scail2-*` video packs use VideoHelperSuite; the TRELLIS.2 and SAM 3D Body packs use core nodes only.

**Updating ComfyUI in the toolbox.** The image ships ComfyUI 0.22.0; TRELLIS.2 and SAM 3D Body need the commit in Tested with (0.37.0). `aihub setup` doesn't do this (it stays manual, plan 23.14), and the report reminds you when TRELLIS.2 is chosen. The toolbox exists only after the first `bin/comfyui start` (or the first load from the hub); stop ComfyUI first (`services/comfy/bin/comfyui quit`). From `services/comfy/`, ComfyUI itself, with the image's torch family held by a constraints file so pip never replaces it:

```bash
toolbox run -c strix-halo-comfyui bash -lc "cd /opt/ComfyUI && git fetch && git checkout 93810483a4739a1588236919a3128d3070244146 && /opt/venv/bin/pip list --format=freeze | grep -iE '^(torch|torchvision|torchaudio|triton|numpy)==' > '$PWD/data/toolbox-constraints.txt' && /opt/venv/bin/pip install -c '$PWD/data/toolbox-constraints.txt' -r requirements.txt"
```

Then each custom node's `requirements.txt` (all five have one), into the same venv:

```bash
toolbox run -c strix-halo-comfyui bash -lc "for r in '$PWD'/custom_nodes/*/requirements.txt; do /opt/venv/bin/pip install -c '$PWD/data/toolbox-constraints.txt' -r \"\$r\" || exit 1; done"
```

`/opt/venv` is the image's venv (`VIRTUAL_ENV`, first on its `PATH`), the one `bin/comfyui` launches ComfyUI with; the host's `$PWD` is the same path inside, since the toolbox shares your home. Then `bin/comfyui start` and `bin/comfyui workflows check trellis2-shape sam3d-body`. These commands weren't run for this doc (this machine's container was updated on 2026-09-24, with ComfyUI-Manager).

## Choosing models

ComfyUI runs any workflow pack, and a pack runs whatever models its workflow names; none are built in. To see what a pack needs, `bin/comfyui workflows check <pack>` (or `--all`): each `missing_model` line names the file and its folder, with a URL when the workflow recorded one. Files go in `data/models/comfyui/<folder>/` (`checkpoints`, `diffusion_models`, `text_encoders`, `vae`, `loras`, `clip_vision`, …). Ways in:
- the page: a pack's review screen has a **Download** button for each missing file whose workflow recorded a URL (`POST /v1/downloads`: into `<folder>/<name>.part`, renamed when done, then registered with the hub; `HF_TOKEN` is sent only to huggingface.co);
- `scripts/download_qwen_image_2.1.sh` and `scripts/download_qwen_image_2.1_turbo.sh` (the Qwen-Image 2.1 packs; resumable, sha256-checked; the Turbo one also fixes the FP8 file's metadata);
- by hand: put the file in its folder and run `aihub models scan --add`; downloads made in ComfyUI's own UI land there too. New packs: [docs/workflows.md](../../../docs/workflows.md).

`aihub docs` lists the models you have in a local inventory (`data/state/setup/models/`). The suggestions are optional and cover packs that ship in git. **Each choice must be a set that runs:** a suggestion is one Hugging Face repo, so a pack whose models span two repos takes two suggestions:
- **Qwen-Image 2.1 Turbo** = *1 of 2* (the Q8_0 diffusion model, 7.59 GB) **and** *2 of 2* (the text encoder and VAE, 18.21 GB): choose both or neither; either alone runs nothing. 25.8 GB together, for the `qwen21-turbo-*` packs (with ComfyUI-GGUF and KJNodes, the block's third step). *2 of 2* is also what the non-Turbo `qwen21-*` packs need besides their own diffusion model (not suggested). Both are under the **Qwen Research Licence**: "for research or evaluation purposes only", no commercial use without a separate licence from Qwen ([LICENSE](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE)).
- **TRELLIS.2** is one entry (three files of one repo) and runs alone, but its nodes need ComfyUI newer than the image's (What to look for).

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| Qwen-Image 2.1 Turbo Q8_0, 1 of 2 (`abenzerps/Qwen-Image-2.1-Turbo-Quantized`) | 7.59 GB | `qwen21-turbo-*`: instruction edits with references (`qwen21-turbo-edit-multi`, the image-edit default here), text to image, background removal; **with 2 of 2** | Qwen Research (research or evaluation only) | no |
| Qwen-Image 2.1 encoder and VAE, 2 of 2 (`Comfy-Org/Qwen-Image-2.1`, 2 files) | 18.21 GB | every Qwen-Image 2.1 pack; **with 1 of 2** for the Turbo ones | Qwen Research (research or evaluation only) | no (yes for those packs) |
| TRELLIS.2 shape set (`Comfy-Org/TRELLIS.2`, 3 files) | 12.65 GB | picture to 3D, `trellis2-*`, 3D Generate's `trellis2` | MIT; DINOv3 Licence | no |

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
aihub check comfy --start
```

Starts the adapter if it's stopped (not ComfyUI, which starts when the mod loads) and runs every check; a stopped mod's live checks are skipped, hence `--start`. Not run with `--start` here while GPU work is paused: with the mod stopped (2026-10-21), `aihub check comfy` gave `ok` for manifest, command, port and page and `comfy: no failures, but 6 checks skipped`.

```bash
services/comfy/bin/comfyui status
```

Expect the image, the mod, models and outputs paths, then `Toolbox: stopped`, `ComfyUI: not running`, `Web UI : not responding` when it isn't loaded (it reads podman's state only).

```bash
services/comfy/bin/comfyui workflows check qwen21-turbo-t2i trellis2-shape sam3d-body
```

Expect `ready` for each pack whose models are on disk (here, on 2026-10-21: all three). `check --all` lists every pack; a pack whose models aren't on disk shows `broken` with one `missing_model` line per file. `missing_node` means a node type isn't installed: the fix line names the custom-node package when the workflow recorded it (install it as above, then reload comfy). `missing_model` names the file and its folder under `data/models/comfyui/`, with the URL when the workflow recorded one. The check reads the node list cached at ComfyUI's last start (`data/object_info.json`), so it works while ComfyUI is down. The other problem codes are in [docs/workflows.md §7](../../../docs/workflows.md#7-problems-and-their-fixes).

```bash
podman image inspect docker.io/kyuz0/amd-strix-halo-comfyui:latest --format '{{.Digest}} {{.Created}}'
```

Expect `sha256:0066678ae9043f69a1c8c7699e70626ceffd35c1a8ca03227a05640ad0241ed2 2026-05-29 09:13:12…`.

```bash
podman unshare cat "$(podman container inspect strix-halo-comfyui --format '{{.GraphDriver.Data.UpperDir}}')/opt/ComfyUI/comfyui_version.py"
```

Reads ComfyUI's version from the container's own layer without starting it. Expect `__version__ = "0.37.0"`. (On a container that was never updated the file isn't in that layer; then the version is the image's, 0.22.0.)

## What to look for

- **The container's ComfyUI is newer than the image.** `/opt/ComfyUI` was updated in place (0.22.0 → 0.37.0). TRELLIS.2 and SAM 3D Body are core nodes only since then (`comfy_extras/nodes_trellis2.py`, `nodes_sam3d_body.py` aren't in the image). **Recreating the toolbox from the image loses them**, and with them the `trellis2-*` and `sam3d-body` packs and two of 3D Generate's engines. That includes `bin/comfyui update`, which pulls `:latest` and recreates the container, and `podman rm strix-halo-comfyui`. On a new machine, update ComfyUI inside the new toolbox to the commit above (Install, "Updating ComfyUI in the toolbox") and check the packs again.
- **A wedged container** (seen 2026-10-10 and 2026-10-21): podman says it's Up, but `podman exec` fails with "crun: the container … is not running", so ComfyUI can't be started or stopped inside it. `bin/comfyui start` and `quit` now recover by themselves: they stop ComfyUI's process from the host, then stop and start the container. If exec still fails, they stop with a message; check `podman ps -a`.
- **The image's digest is the pin.** `:latest` on Docker Hub moves, and gen3d's worker venvs are built against the torch inside the digest above (their `constraints.txt`). If the pull by digest ever fails because the owner removed that build, pull `:latest`, note its digest and torch version (`podman run --rm <image> /opt/venv/bin/python -c "import torch; print(torch.__version__)"`), then rebuild gen3d's venvs (`services/gen3d/scripts/install-runtime.sh` after deleting `runtime/*/.venv`) and run the packs' checks again. Keep a copy of a working image with `podman save -o <file>.tar <image>` if you need to rebuild offline.
- **`--disable-mmap` stays.** Without it, loading goes through ROCm's slow mmap path once more than 64 GB is mapped, and can hang.
- **Hybrid scaled-FP8 files** (for example abenzerps' Qwen-Image 2.1 Turbo FP8) render noise until their metadata is fixed with `scripts/fix_fp8_quant_metadata.py SRC DEST`.
- **GPU safety.** Use the stock image and the pinned nodes. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for) before running anything else.

## Known gaps

- Nothing in `aihub setup` installs the custom nodes' Python packages or updates ComfyUI in the toolbox: both are the manual commands in Install (the clones are the block's optional step, asked first).
- The image is pinned only by the setup step's digest: `bin/comfyui` and `bin/comfyui update` use `:latest`, and the in-place update to 0.37.0 is the manual commands in Install.
- The Z-Image and Wan 2.1 packs (`zimage-turbo`, `zimage-intorealism`, `qwen-edit-refine-zimage`, `wan21-t2v`, `wan21-i2v`) have `agent = false`: their models were deleted on 2026-10-20 to free disk space. The workflows are kept; `check` shows them `broken` until the models are downloaded again. The Flux 2 Klein, Krea 2 and Qwen-Image-Edit packs are also `broken` here (their models aren't on disk) but still have the agent on; a broken pack isn't offered to it.
