# The host: Linux with an NVIDIA GPU

What a Linux machine with an NVIDIA card needs before you clone AIHub (plan 38.4). **Not yet run on such a machine:** the field test (plan 40.5) checks it, and this page is corrected from its report. The commands that are the same everywhere (uv, accounts, disk) are in [host.md](host.md) §3–§6.

## Check what AIHub sees

```bash
bin/aihub hardware
bin/aihub setup host
```

`aihub hardware` should list your card with its `sm_` architecture and CUDA version, and `cuda` among the accels. `aihub setup host` prints a fix for each problem; the ones that need `sudo` are printed, never run.

## 1. The NVIDIA driver

AIHub's PyTorch and llama.cpp builds bring their own CUDA runtime; the host needs only the **driver** (`nvidia-smi` must work):

| Distribution | Install |
|---|---|
| Ubuntu, Pop!_OS | `sudo ubuntu-drivers install`, then reboot |
| Fedora | enable [RPM Fusion](https://rpmfusion.org/Configuration), `sudo dnf install akmod-nvidia`, wait for the module to build, reboot |
| Arch | `sudo pacman -S nvidia` (or `nvidia-open`), reboot |
| openSUSE | `sudo zypper install nvidia-video-G06`, reboot |

Check: `nvidia-smi` prints the card and `CUDA Version: 12.x` or newer. The setup picks the newest PyTorch CUDA build the driver can run (cu130, cu128 or cu126); a driver older than CUDA 12.6 should be updated.

## 2. Containers with the GPU (vLLM, some 3D engines)

Mods that run their engine in a container reach the GPU through the **NVIDIA Container Toolkit**:

```bash
# Ubuntu: add NVIDIA's repository first (https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

With podman, mods pass `--device nvidia.com/gpu=all` (CDI); with docker, `--gpus all` (`services/_template/containers.py`). Check: `podman run --rm --device nvidia.com/gpu=all ubuntu nvidia-smi`.

## 3. Packages

```bash
sudo apt install podman git nodejs npm espeak-ng ffmpeg
```

(Fedora: `sudo dnf install podman git-core nodejs22 nodejs22-npm espeak-ng`, ffmpeg from RPM Fusion.) Vulkan is optional: llama.cpp's CUDA build doesn't need it.

## 4. Memory

A card's VRAM is its own budget (plan 36): AIHub's memory panel shows a bar per card, and loading a model that doesn't fit the card unloads idle GPU mods, not RAM-only ones. A mod declares its VRAM as `vram_gb`; llama.cpp can split a model between VRAM and RAM.

## What to look for

- `nvidia-smi` works but `cuda` is missing from `aihub hardware`: `nvidia-smi` printed no "CUDA Version" (a very old driver).
- `nouveau` instead of `nvidia` in `aihub hardware`'s driver: the open-source driver is loaded; install NVIDIA's and reboot.
- Several cards: `[services.<id>] gpu = <index>` in `config.toml` pins a mod to one (`aihub hardware` numbers them); by default a mod starts on the freest.
