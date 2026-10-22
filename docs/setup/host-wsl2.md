# The host: Windows 11 through WSL2

AIHub runs on Windows inside WSL2 (Ubuntu), which is Linux with systemd; native Windows isn't supported ([platforms.md](../platforms.md)). **Not yet run end to end:** the field test (plan 40.6) checks it with an Intel GPU.

## 1. WSL2 and Ubuntu

In PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
```

Then, in Ubuntu, turn systemd on (AIHub runs as a systemd user service):

```bash
printf '[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf
```

and restart WSL from PowerShell: `wsl --shutdown`, then open Ubuntu again.

## 2. The GPU

WSL2 uses the **Windows** GPU driver: install or update it on Windows (NVIDIA's Game Ready or Studio driver; Intel's Arc and Iris Xe driver), and **don't install a GPU driver inside Ubuntu**. WSL exposes the GPU as `/dev/dxg`.

- **NVIDIA:** `nvidia-smi` works in Ubuntu as soon as the Windows driver is installed. CUDA variants run as on Linux.
- **Intel:** install the compute runtime inside Ubuntu (`sudo apt install intel-opencl-icd libze1 libze-intel-gpu1`); then `xpu` variants run.
- **AMD:** ROCm on WSL supports only some Radeon cards; AIHub uses the CPU variants unless `rocminfo` lists your GPU.

Vulkan inside WSL goes through a translation layer (dzn) and isn't used.

## 3. Where the clone goes

Clone AIHub inside WSL's own filesystem (`~/`), **not** under `/mnt/c/`: Windows drives are many times slower from WSL. `aihub setup host` warns about it.

## 4. The browser

Open <http://127.0.0.1:7000> in your Windows browser: WSL forwards localhost. `aihub open` opens it there.

## Check it

```bash
bin/aihub hardware          # your GPU, "(WSL2)", and cuda or xpu among the accels
bin/aihub setup host        # wsl-systemd, wsl-clone and wsl-gpu ok
```
