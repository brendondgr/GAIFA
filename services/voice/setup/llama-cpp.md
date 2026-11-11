<!-- gaifa-setup
id = "voice"
title = "Voice (LFM3-Omni-2B in llama.cpp)"
models = ["s2s/**"]
scan = []
summary = "Voice mode on a speech-to-speech model: it hears you and answers aloud itself, on this machine, in a fraction of a second (LFM3-Omni-2B in llama.cpp)"
gpu = false
disk_gb = 0.5
needs = ["uv", "curl", "tar"]
check = "gaifa check voice --start"
smoke = "gaifa start voice >/dev/null && curl -fsS -X POST -H 'content-type: application/json' -d '{\"text\": \"The voice mod works.\"}' -o /dev/null \"$(gaifa url api/s/voice/v1/speech)\" && curl -fsS \"$(gaifa url api/s/voice/v1/status)\" | tee /dev/stderr | grep -q '\"loaded\": *true'"

[[steps]]
run = "gaifa install voice"
what = "makes .venv/ (about 350 MB), fetches llama.cpp b12292 for the variant from GitHub (20–200 MB, checked against its sha256) into runtime/llama.cpp/, and the Silero VAD model (2 MB) into runtime/vad/"

[[suggest]]
name = "LFM3-Omni-2B Q4_K_M (smaller, faster)"
repo = "LiquidAI/LFM3-Omni-2B-GGUF"
revision = "d508b88f08a5b4286f2d2805a6a8d69a0ff44c72"
files = ["LFM3-Omni-2B-Q4_K_M.gguf", "mmproj-LFM3-Omni-2B-Q8_0.gguf", "LICENSE"]
dest = "s2s/LFM3-Omni-2B"
size_gb = 1.61
good_for = "the default: first audio about 90 ms after you stop talking on a Radeon 8060S"
licence = "LFM Open License v1.0"
required = true

[[suggest]]
name = "LFM3-Omni-2B Q8_0 (closer to the original)"
repo = "LiquidAI/LFM3-Omni-2B-GGUF"
revision = "d508b88f08a5b4286f2d2805a6a8d69a0ff44c72"
files = ["LFM3-Omni-2B-Q8_0.gguf", "mmproj-LFM3-Omni-2B-Q8_0.gguf", "LICENSE"]
dest = "s2s/LFM3-Omni-2B"
size_gb = 2.35
good_for = "comparing with Q4_K_M (docs/voice-eval.md); about 120 ms to first audio, 0.8 GB more memory"
licence = "LFM Open License v1.0"

[[variants]]                    # llama.cpp's Vulkan release build (Mesa RADV on AMD)
accel = "vulkan"
os = ["linux"]
tested = true

[[variants]]                    # llama.cpp's CUDA 12.8 release build
accel = "cuda"
os = ["linux", "wsl"]

[[variants]]                    # llama.cpp's CPU release build: the language model on the CPU
accel = "cpu"
os = ["linux", "wsl"]
note = "untested; the spike's -ngl 0 run answered in about 200 ms on 16 cores"
-->

# Voice (LFM3-Omni-2B in llama.cpp): setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `voice` mod's one environment: `.venv/` in this folder (FastAPI, websockets, onnxruntime for the Silero VAD) and a release build of llama.cpp in `runtime/llama.cpp/`. The mod starts `llama-server` as a child process with a speech-to-speech model and bridges the Chat page's voice mode to its realtime WebSocket (`/v1/realtime`). It is the "Speech model (local)" choice in Settings → Speech → Voice mode; without it, voice mode uses the chat's model with the stt and tts mods.

## Tested with

- llama.cpp **b12292**, `llama-b12292-bin-ubuntu-vulkan-x64.tar.gz` (sha256 `01a6e2a7caa8d6ab6cb2dd906bd7c5c435440849c259440b1c3d3724850fa8e7`), Mesa RADV on a Radeon 8060S (gfx1151). The model needs b11960 (v0.8.0) or newer.
- `LiquidAI/LFM3-Omni-2B-GGUF` at `d508b88f08a5b4286f2d2805a6a8d69a0ff44c72`.
- Silero VAD v6.2 (`silero_vad.onnx`, sha256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`, MIT).
- Python 3.14 (uv-managed), onnxruntime 1.2x on the CPU.

Measured numbers are in [docs/voice-spike.md](../../../docs/voice-spike.md).

## Prerequisites

`uv`, `curl` and `tar` ([host.md](../../../docs/setup/host.md)). For the Vulkan variant, a Vulkan driver (Mesa on AMD and Intel). The model's licence is the [LFM Open License v1.0](https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF/blob/main/LICENSE): read it before using the model for more than yourself.

## Install

```bash
gaifa install voice
```

Runs `install.sh`: the venv from `requirements-dev.txt`; llama.cpp's release tarball for the variant (`--accel`, else `GAIFA_ACCEL`, else Vulkan where a Vulkan driver is found) from `github.com/ggml-org/llama.cpp`, checked against the sha256 in the script, unpacked to `runtime/llama.cpp/bin/llama-b12292-<accel>/` with `bin/current` pointing at it (the tarball stays in `runtime/llama.cpp/vendor/`); and the Silero VAD model from `github.com/snakers4/silero-vad` into `runtime/vad/`. Under a minute. Nothing is written outside this folder.

On a machine with no release build (macOS, other CPUs), build llama.cpp b12292 yourself and set `VOICE_LLAMA_BIN` to its `llama-server` (`config.toml`, `[services.voice.env]`).

## Choosing models

The mod runs one model, LFM3-Omni-2B, from `data/models/s2s/LFM3-Omni-2B/`: a language-model file per size (`LFM3-Omni-2B-Q4_K_M.gguf` or `-Q8_0.gguf`) and the projector `mmproj-LFM3-Omni-2B-Q8_0.gguf` (vision, audio in and the speech codec), which both sizes share. `gaifa setup voice` offers both sizes; Q4_K_M is the one the mod needs. To add them by hand, download the files from `huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF` into that folder. The size is chosen in Settings → Speech → Voice mode or on the mod's page.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `VOICE_QUANT` | `service.toml` `[run.env]`, or `config.toml` `[services.voice.env]` | no | the size loaded when none is asked for: `q4_k_m` (default) or `q8_0` |
| `VOICE_GPU_LAYERS` | the same | no | `99` (default) puts the language model on the GPU; `0` keeps it on the CPU |
| `VOICE_LLAMA_BIN` | the same | no | another `llama-server` (b11960 or newer) |
| `VOICE_IDLE_UNLOAD_S` | `config.toml` `[services.voice] idle_unload_s` | no | unload after this long with no conversation (300) |
| `[voice_mode]` | `config.toml` | no | which engine voice mode uses, the size and the voice (Settings → Speech) |

## Check it works

```bash
gaifa start voice && gaifa check voice
```

Expect `all checks passed`. Then, with the model downloaded, a sentence in its own voice:

```bash
curl -X POST -H 'content-type: application/json' -d '{"text": "The voice mod works."}' -o voice.wav "$(gaifa url api/s/voice/v1/speech)"
```

And a conversation from the command line (a WAV per spoken turn, or typed turns):

```bash
cd services/voice && .venv/bin/python -m evals.client --url ws://127.0.0.1:5110/v1/realtime --text "What is the capital of France?"
```

## What to look for

- **`model_missing` (409):** a file isn't in `data/models/s2s/LFM3-Omni-2B/`; the error names it. Run `gaifa setup voice` or download it.
- **`engine_missing` (409):** no `llama-server` at `VOICE_LLAMA_BIN`; run `gaifa install voice`.
- **`engine_failed` at load:** the error carries llama.cpp's last log lines; the whole log is `runtime/logs/llama-server.log`. An "unknown model architecture" means the build is older than b11960.
- **The turn never ends, or ends on every noise:** `GET /v1/status` says which detector runs (`vad`: `silero` or `energy`). `energy` means `runtime/vad/silero_vad.onnx` is missing: run `gaifa install voice` again.
- **It hears itself (speakers):** the page cancels echo, but loud speakers close to the microphone can still interrupt replies. Use headphones.
- **gfx1151:** set `AMD_VULKAN_ICD=RADV` (the Vulkan variant does); AMDVLK was not tried.

## Known gaps

- CUDA, the CPU-only build and macOS are untested.
- Images and video in (the model takes them) aren't used.
