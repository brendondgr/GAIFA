# The host: macOS on Apple Silicon

What a Mac needs before you clone AIHub (plan 38.4). **Not run on a Mac yet:** the hub and the mods without GPU work are checked in CI; the GPU variants (`mps`) are marked untested until someone runs the field test on a Mac.

## 1. Tools

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git node espeak-ng ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Podman or Docker Desktop only for mods that run containers; containers on macOS can't reach the GPU, so those mods run on the CPU or aren't available.

## 2. Running the hub

There's no systemd: `aihub install` writes a launchd agent to `data/state/hub/com.aihub.hub.plist` and prints the commands that copy it to `~/Library/LaunchAgents/` and load it (AIHub writes nothing outside its folder for you). Until then, `aihub start` runs the hub in the background, and mods run as detached processes that outlive it.

## 3. The GPU

The Apple GPU shares the system's memory (one memory pool). PyTorch reaches it as `mps`, llama.cpp through its Metal build. `aihub hardware` lists `mps` among the accels on Apple Silicon; an Intel Mac has none, and runs the CPU variants.

## What to look for

- A mod whose variants are all ROCm or CUDA (vLLM, most 3D engines) is "not available on this machine"; the setup says why.
- Speech to Text runs on the CPU (CTranslate2 has no Metal backend).
