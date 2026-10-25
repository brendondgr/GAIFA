# The host: Linux with an Intel GPU

What a Linux machine with an Intel Arc card or an integrated Intel GPU needs before you clone GAIFA (plan 38.4). **Not yet run on such a machine:** the field test (plan 40.5, 40.6) checks it. The shared parts are in [host.md](host.md) §3–§6.

## Check what GAIFA sees

```bash
bin/gaifa hardware
bin/gaifa setup host
```

`xpu` among the accels means PyTorch can use the GPU; `vulkan` alone means only Vulkan software (llama.cpp's Vulkan build) can.

## 1. The compute runtime

The kernel driver (`i915` or `xe`) is in every current kernel. PyTorch's `xpu` build and llama.cpp's SYCL build also need Intel's **compute runtime** (Level Zero):

| Distribution | Install |
|---|---|
| Ubuntu 24.04+ | `sudo apt install intel-opencl-icd libze1 libze-intel-gpu1` |
| Fedora | `sudo dnf install intel-compute-runtime oneapi-level-zero` |
| Arch | `sudo pacman -S intel-compute-runtime level-zero-loader` |

Check: `gaifa hardware` lists `level_zero` under the GPU's runtimes and `xpu` among the accels.

## 2. GPU access for your user

```bash
sudo usermod -aG render $USER     # then log out and in
```

## 3. Memory

An Arc card has its own VRAM (a memory pool of its own, plan 36); an integrated GPU shares the system's memory. `gaifa hardware` says which.

## What to look for

- `libze_intel_gpu` missing: `xpu` isn't offered, and the setup picks the CPU or Vulkan variants.
- Mods with no `xpu` variant (vLLM, most of 3D Generate) run on the CPU or aren't available; the setup says which.
