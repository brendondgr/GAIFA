# The host: the machine before AIHub

What the machine needs before you clone AIHub. Every value here was read from the machine AIHub is built on (2026-10-20). Where it differs from the upstream guide, both are given.

## Tested with

| | This machine |
|---|---|
| Machine | ASUS ROG Flow Z13 (GZ302EA), BIOS 311 |
| Chip | AMD Ryzen AI MAX+ 395 with Radeon 8060S (Strix Halo, `gfx1151`), 128 GB unified memory |
| OS | Fedora Linux 44 (KDE Plasma), kernel `7.2.11-200.fc44` |
| GPU drivers | the kernel's `amdgpu`; `linux-firmware-20260916`, `mesa-vulkan-drivers-26.2.4` (llama.cpp uses Vulkan, through RADV) |
| ROCm | none on the host: ROCm and PyTorch come inside the containers and the engine venvs |
| Containers | podman 5.8.9, toolbox 0.3 |
| Tools | uv 0.12.23, git 2.56.0, Node 22.23.1 (`nodejs22`), npm 10.9.8, espeak-ng 1.52.0, ffmpeg 8.1.3 (RPM Fusion), Blender 5.2.2 (optional) |

Other Strix Halo machines (the Framework Desktop, the HP Z2 Mini G1a, the GMKtec EVO-X2, …) have the same chip and should work the same way. Other GPUs are out of scope: the container images, the PyTorch wheels and the engines' settings are all built for `gfx1151`.

## 1. Let the GPU use the memory

On Strix Halo the GPU and CPU share memory. By default the GPU can address only a small part of it; AIHub's models need most of it. Two places decide this.

**The BIOS's dedicated GPU memory** (the UMA frame buffer). This machine keeps it small, **4 GB** (`mem_info_vram_total` reads `4294967296`), and gives the GPU the rest through GTT (below). Leave it at its default or set it low; don't give the GPU a large fixed carve-out, which the CPU then can't use.

**Kernel parameters.** On this machine `/proc/cmdline` has:

```
amd_iommu=off amdgpu.gttsize=131072 ttm.pages_limit=33554432
```

| Parameter | This machine | Upstream guide | What it does |
|---|---|---|---|
| `amdgpu.gttsize` | `131072` (128 GiB) | `126976` (124 GiB) | how much memory the GPU can address through GTT, in MiB |
| `ttm.pages_limit` | `33554432` (128 GiB of 4 KiB pages) | `32505856` (124 GiB) | how many pages the GPU's memory manager may pin; match it to `gttsize` |
| `amd_iommu` | `off` | `off` | faster GPU memory access on unified memory (5–12% reported); it **disables the NPU** and removes DMA-attack protection |

The upstream guide is kyuz0's Strix Halo toolboxes ([strix-halo-toolboxes.com](https://strix-halo-toolboxes.com), [repo](https://github.com/kyuz0/amd-strix-halo-toolboxes)), whose images AIHub uses. Its 124 GiB leaves a little more for the CPU; 128 GiB is what this machine has run on since the start.

To set them on Fedora:

```bash
sudo grubby --update-kernel=ALL --args="amd_iommu=off amdgpu.gttsize=131072 ttm.pages_limit=33554432"
```

```bash
sudo reboot
```

(The upstream guide edits `GRUB_CMDLINE_LINUX` in `/etc/default/grub` and runs `sudo grub2-mkconfig -o /boot/grub2/grub.cfg` instead; either works.)

**Check it:**

```bash
cat /proc/cmdline
```

```bash
cat /sys/class/drm/card*/device/mem_info_gtt_total
```

The first shows the three parameters; the second prints about `130446360576` (121.5 GiB) here. That number matters: AIHub's memory manager and the vLLM mod read it to size what they load. If it prints around 60 GB, the parameters didn't apply.

## 2. GPU access for your user

The containers pass `/dev/kfd` and `/dev/dri` through, which needs your user in the `video` and `render` groups:

```bash
sudo usermod -aG video,render $USER
```

Log out and back in, then check that `id` lists both. (On this machine: `groups=…,39(video),…,105(render),…`.)

## 3. Packages

```bash
sudo dnf install podman toolbox git-core nodejs22 nodejs22-npm espeak-ng
```

- **ffmpeg** (Speech, 3D previews, video outputs): Fedora's own `ffmpeg-free` lacks some codecs. This machine uses RPM Fusion's full `ffmpeg`. Enable [RPM Fusion](https://rpmfusion.org/Configuration), then `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`.
- **uv** (every Python environment; it downloads Python itself):

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  It installs to `~/.local/bin/uv`. Don't install Python packages with pip or dnf for AIHub; every environment is made by uv or lives in a container.
- **Blender** (optional): 3D Generate renders previews with it if `~/.local/bin/blender` exists. This machine uses Blender 5.2.2 LTS from blender.org, unpacked and linked there.
- **Node 22 and npm** are only for building the LLM Relay's web UI once, during `aihub install relay`.

**Check it:**

```bash
podman --version && toolbox --version && uv --version && node --version && espeak-ng --version && ffmpeg -version | head -1
```

## 4. Keep your services running

AIHub runs as a systemd **user** service, which stops when you log out unless lingering is on:

```bash
loginctl enable-linger $USER
```

`loginctl show-user $USER -p Linger` prints `Linger=yes`.

## 5. Disk

| What | Size on this machine |
|---|---|
| Model weights (`data/models/`, every model in the registry) | **354 GB** (the registry's files; the folder holds about 374 GB with caches) |
| ComfyUI image `kyuz0/amd-strix-halo-comfyui` (Images & Video, 3D Generate) | 15.1 GB |
| vLLM image `kyuz0/vllm-therock-gfx1151` | 12.4 GB |
| Speech runtimes (`services/tts/runtime/`) | 14 GB |
| 3D runtimes (`services/gen3d/runtime/`) | 13 GB |
| llama.cpp (`services/lcpp/runtime/`) | 262 MB |
| The hub's and mods' own venvs | under 100 MB each |

You don't need every model. Each model's doc in [models/](models/) gives its size and the environment that runs it. Put the clone on a disk with room: model weights live inside the project folder (`data/models/`), and podman keeps images in `~/.local/share/containers/`.

**The clone must be under your home folder.** The ComfyUI toolbox shares `$HOME` with the host, and ComfyUI reads models and custom nodes from the project folder through that share.

## 6. Accounts and licences

- **Hugging Face.** Most models download from Hugging Face. Some repos are **gated** (you accept terms on the model's page first), for example `facebook/sam-3d-objects`. Make a token at <https://huggingface.co/settings/tokens> and log in once:

  ```bash
  uvx --from huggingface_hub hf auth login
  ```

  The token is stored in `~/.cache/huggingface/token`, where the mods' downloaders find it (or set `HF_TOKEN`).
- **Licences you accept by installing:** each model doc names its licence when it has restrictions. The one the installers ask about is **Breeze TTS 2** (non-commercial): the Speech runtime installer needs `--accept-breeze-license`.
- **OpenCode** (optional) needs an OpenCode Zen key or a provider key; see the OpenCode environment doc.

## What to look for

- **`mem_info_gtt_total` is about half your memory.** The kernel parameters didn't apply: check `/proc/cmdline` after the reboot, and that `sudo grubby --info=DEFAULT` lists them.
- **`podman run` fails with permission denied on `/dev/kfd`.** You're not in `render` (or haven't logged in again since adding it).
- **SELinux denials on mounts.** The mods run their containers with `--security-opt label=disable` and the toolbox shares `$HOME`; a clone outside `$HOME` (another disk mounted elsewhere) won't be visible inside the ComfyUI toolbox.
- **The NPU is gone.** That's `amd_iommu=off`. AIHub doesn't use the NPU.
- **Upstream tweaks this machine doesn't use:** the upstream guide also suggests `sudo systemctl set-default multi-user.target` (no desktop, more free memory) and `sudo tuned-adm profile accelerator-performance`. This machine keeps the desktop and the `balanced` profile; AIHub keeps a 12 GB reserve for the desktop (`memory.reserve_gb`).

Next: [the hub](hub.md).
