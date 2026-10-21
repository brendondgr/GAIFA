<!-- aihub-setup
id = "tts-breeze"
title = "Breeze TTS 2 and Whisper (Speech)"
models = ["tts/breeze-tts-2", "hf-cache/hub/models--openai--whisper-large-v3-turbo", "voices/**"]
scan = []
summary = "Speech: voice cloning, voice design and delivery directions with Breeze TTS 2 (non-commercial), plus Whisper word timings"
gpu = true
disk_gb = 7
needs = ["uv", "git", "ffmpeg"]
after = ["tts-kokoro"]
check = "uv pip freeze --python runtime/venvs/breeze-tts/bin/python | diff -q - <(sort locks/breeze-tts.txt) && git -C runtime/breeze-tts apply --reverse --check \"$PWD/engines/breeze/patches/0001-rocm-port-and-dtype.patch\" && grep -q '\"breeze\"' ~/.config/tts-engines/engines.json"

[[steps]]
run = "uvx --from huggingface_hub hf download BreezeBlue/Breeze-TTS-2 --local-dir ../../data/models/tts/breeze-tts-2"
what = "Breeze TTS 2's weights into data/models/tts/breeze-tts-2 (7.7 GB, the required suggestion below); needed before the installer, which runs offline"
ask = "Breeze TTS 2's weights and everything it makes are licensed for research and non-commercial use only (https://huggingface.co/BreezeBlue/Breeze-TTS-2). Accept that licence and install Breeze? (This answer is also the installer's --accept-breeze-license below.)"

[[steps]]
run = "HF_HOME=../../data/models/hf-cache uvx --from huggingface_hub hf download openai/whisper-large-v3-turbo --include '*.json' --include '*.safetensors' --include '*.txt'"
what = "Whisper large-v3-turbo into the project's Hugging Face cache (1.6 GB, required: the Breeze installer fetches it offline and stops without it)"

[[steps]]
run = "scripts/install-runtime.sh --accept-breeze-license"
what = "re-checks Kokoro (its smoke test loads Kokoro on the GPU again), then builds runtime/venvs/breeze-tts from locks/breeze-tts.txt (about 7 GB of wheels, 10 to 15 min), clones and patches Breeze's source, and runs a smoke test that loads Breeze on the GPU and compiles its fast stages (about 50 s); the engine is recorded only when the test passes"

[[suggest]]
name = "Breeze TTS 2"
repo = "BreezeBlue/Breeze-TTS-2"
files = []
dest = "tts/breeze-tts-2"
kind = "tts"
size_gb = 7.68
good_for = "the engine's weights: cloning, designing and directing voices"
licence = "BreezeBlue Research and Non-Commercial Licence"
required = true

[[suggest]]
name = "Whisper large-v3-turbo"
repo = "openai/whisper-large-v3-turbo"
files = ["added_tokens.json", "config.json", "generation_config.json", "merges.txt", "model.safetensors", "normalizer.json",
  "preprocessor_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json"]
dest = "hf-cache"
kind = "stt"
size_gb = 1.62
good_for = "transcripts of new voice clips and word timings (Breeze's timings, /v1/align)"
licence = "MIT"
required = true
-->

# Breeze TTS 2 and Whisper: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The Speech mod's second engine, in `runtime/venvs/breeze-tts`, with Breeze's source in `runtime/breeze-tts`. **Breeze TTS 2** clones a saved voice from a reference clip, designs a voice from a description, and follows delivery directions ("slow and warm") and tags like `(sigh)`. The same venv runs **Whisper large-v3-turbo** in one-shot processes: it writes the transcript of a new voice clip when you leave it empty, and aligns word timings (`POST /v1/align`, and Breeze's `timings`). The server venv and Kokoro are in [kokoro.md](kokoro.md). **Breeze's weights and outputs are licensed for research and non-commercial use only.**

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| `runtime/venvs/breeze-tts` | Python 3.12.13; exactly `locks/breeze-tts.txt` (checked with `uv pip freeze`, below) |
| torch | `torch==2.15.0a0+rocm10.2.0a20260926` with `amd-torch-device-gfx1151` (and `-gfx115x`), `torchaudio==2.11.0.3+rocm10.2.0a20260926`, `triton==3.8.0+gitc01b6774.rocm10.2.0a20260926` |
| ROCm (wheels) | `rocm==10.2.0a20260926`, `rocm-sdk-core`, `rocm-sdk-libraries`, `rocm-sdk-device-gfx1151` (same build), `rocm-bootstrap` 0.3.0 |
| Wheel index | `https://nightly.repo.amd.com/rocm/whl-next/`, with PyPI as the extra index (the same torch line as the `embed` mod) |
| Breeze packages | qwen-tts 0.1.1, transformers 4.57.3, accelerate 1.12.0, librosa 1.0.0, numpy 2.5.3, soundfile 0.14.0, huggingface-hub 0.36.2 |
| Breeze source | https://github.com/breezeblue-ai/breeze-tts.git at `008f769016b0a24711becd7a4925030bc93f608c` (2026-09-10, `engines/breeze/UPSTREAM_COMMIT`), plus `engines/breeze/patches/0001-rocm-port-and-dtype.patch` (applied exactly) |
| Engine record | `~/.config/tts-engines/engines.json`: backend `rocm`, device `cuda`, dtype `bf16`, fast stages `depth_decoder,backbone_decode`, licence accepted 2026-10-06 |
| Models | `BreezeBlue/breeze-tts-2` in `data/models/tts/breeze-tts-2` (7.7 GB; no revision recorded); `openai/whisper-large-v3-turbo` at `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` in `data/models/hf-cache/` (1.6 GB) |

## Prerequisites

- [kokoro.md](kokoro.md): the server venv (`aihub install tts`), and the same host packages. `ffmpeg` converts every voice upload to 24 kHz mono WAV.
- git (the installer clones Breeze's source).
- **The licence.** Read https://huggingface.co/BreezeBlue/Breeze-TTS-2; installing means passing `--accept-breeze-license`.

## Install

```bash
uvx --from huggingface_hub hf download BreezeBlue/Breeze-TTS-2 --local-dir data/models/tts/breeze-tts-2
```

From the project folder: Breeze's weights, the whole repo (about 7.7 GB).

```bash
HF_HOME=data/models/hf-cache uvx --from huggingface_hub hf download openai/whisper-large-v3-turbo --include "*.json" --include "*.safetensors" --include "*.txt"
```

Whisper into the project's Hugging Face cache (1.6 GB), the same patterns the Breeze installer asks for. Do both first: the runtime installer runs offline (What to look for).

```bash
services/tts/scripts/install-runtime.sh --accept-breeze-license
```

Builds Kokoro first ([kokoro.md](kokoro.md)), then `runtime/venvs/breeze-tts` with uv (Python 3.12) and exactly `locks/breeze-tts.txt` from AMD's whl-next index (several GB of wheels). Then `engines/breeze/install.sh` keeps that torch, clones Breeze into `runtime/breeze-tts`, checks out `UPSTREAM_COMMIT` and applies `patches/*.patch`, reinstalls Breeze's packages under a torch constraint, skips the weights when `config.json` and the safetensors are there, fetches Whisper (from the cache when it's there), copies `breeze_tts.py` and `align.py` into the venv, writes `~/.local/bin/breeze-tts`, and runs a smoke test (`breeze-tts --check`), **which loads Breeze on the GPU and compiles its fast stages on the first run**. Only after the test passes does it record the engine in `~/.config/tts-engines/engines.json`. It wasn't re-run for this doc.

### Voices

Saved voices are folders in `data/models/voices/<name>/` (`reference.wav` and `voice.json`). The three on this machine are **personal recordings**: they aren't in git and aren't shared. Make your own from 10 to 25 s of clean speech (3 to 60 s is accepted): Speech page → Voices → **Add voice** (upload or record), or:

```bash
curl -F name=myvoice -F audio=@me.wav -F "transcript=Exactly what I say in the clip." http://127.0.0.1:7000/api/s/tts/v1/voices
```

Leave out the transcript and Whisper writes one (check it: clone quality depends on it). **Design voice** invents one from a description and keeps its sample as the reference. The mod doesn't register a new voice in the models registry; `aihub models scan --add` adds it as kind `voice`. More in the mod's README, "Add a voice".

## Choosing models

Breeze is a fixed engine: it runs one set of weights, `BreezeBlue/Breeze-TTS-2`, from `data/models/tts/breeze-tts-2` (`BREEZE_MODEL`), and nothing in it downloads while it runs. What you choose are voices (above), not models.

**Whisper is required too.** Synthesis itself doesn't use it, but `engines/breeze/install.sh` always fetches `openai/whisper-large-v3-turbo` (offline under `install-runtime.sh`, so it must be in the cache first) and stops without it, and then Breeze is never recorded as installed. After that, Whisper writes transcripts of new voice clips, Breeze's word timings and `POST /v1/align`. `LOCALTTS_WHISPER_MODEL` can name another Whisper checkpoint in Transformers format for transcripts and `/v1/align` (put it in the cache yourself; not tested here), but the installer still asks for large-v3-turbo.

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| Breeze TTS 2 (`BreezeBlue/Breeze-TTS-2`) | 7.68 GB | the engine's weights | research and non-commercial only | yes |
| Whisper large-v3-turbo (`openai/whisper-large-v3-turbo`) | 1.62 GB | transcripts and word timings | MIT | yes (the installer needs it) |

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `LOCALTTS_BREEZE_PYTHON` | `service.toml` | yes (set) | `runtime/venvs/breeze-tts/bin/python` (also runs Whisper) |
| `BREEZE_REPO`, `BREEZE_MODEL` | `service.toml` | yes (set) | `runtime/breeze-tts`, `data/models/tts/breeze-tts-2` |
| `HF_HOME`, `HF_HUB_OFFLINE` | `service.toml` | yes (set) | `data/models/hf-cache` and `1`: Whisper is read from the cache, never downloaded |
| `LOCALTTS_VOICES_DIR` | `service.toml` | yes (set) | `data/models/voices` |
| `LOCALTTS_BREEZE_FAST` | `config.toml [services.tts].env` | optional | the fast stages; default from `engines.json` (`depth_decoder,backbone_decode`); empty = eager |
| `BREEZE_DTYPE`, `BREEZE_DEVICE` | `config.toml` env | optional | default from `engines.json` (`bf16`, `cuda`, which means ROCm here) |
| `LOCALTTS_WHISPER_MODEL` | `config.toml` env | optional | default `openai/whisper-large-v3-turbo` |

## Check it works

```bash
curl -s http://127.0.0.1:7000/api/s/tts/v1/status
```

A GET, so nothing loads. Expect `"breeze": {"state": "unloaded", …}` while idle and `Engines installed` 2. `aihub check tts` is in [kokoro.md](kokoro.md#check-it-works).

```bash
uv pip freeze --python services/tts/runtime/venvs/breeze-tts/bin/python | diff - <(sort services/tts/locks/breeze-tts.txt)
```

Expect only `Using Python 3.12.13 environment at: services/tts/runtime/venvs/breeze-tts` and no diff lines.

```bash
git -C services/tts/runtime/breeze-tts rev-parse HEAD
```

Expect `008f769016b0a24711becd7a4925030bc93f608c`.

```bash
git -C services/tts/runtime/breeze-tts apply --reverse --check "$PWD/services/tts/engines/breeze/patches/0001-rocm-port-and-dtype.patch"
```

From the project folder. No output and exit 0 means the patch is applied as shipped.

## What to look for

- **The runtime installer runs offline.** `install-runtime.sh` exports `HF_HUB_OFFLINE=1` unless you set it, and `engines/breeze/install.sh` downloads with `snapshot_download`. With nothing on disk, the weights step and the Whisper step fail with `LocalEntryNotFoundError` (offline mode), and the install stops. Download both first (Install). Setting `HF_HUB_OFFLINE=0` for that one run also lets it download (not tried here). The installer names the repo `BreezeBlue/Breeze-TTS-2`; the registry records `BreezeBlue/breeze-tts-2`. The Hugging Face API resolves both to `BreezeBlue/Breeze-TTS-2` (checked 2026-10-21).
- **The fast stages are HIP graphs.** `depth_decoder` and `backbone_decode` capture `torch.cuda.CUDAGraph`s (upstream's `models/cudagraph/`), which run as HIP graphs on ROCm. They're upstream's stock code and the installer's choice for gfx1151 (warm speed about RTF 1.5). `LOCALTTS_BREEZE_FAST=` (empty) runs eager instead: RTF about 2.7, no warmup. Don't add more graph stages (`text_encoder`, `backbone_prefill`, `codec`) or custom kernels.
- **The first start after an install compiles** (about 50 s; later cold starts about 30 s). Breeze's torch.compile cache is `~/.cache/localtts/inductor`.
- **Worker settings:** `MIOPEN_FIND_MODE=2`, `MIOPEN_LOG_LEVEL=3`, `ROCPROFILER_REGISTER_ENABLED=0` (see [kokoro.md](kokoro.md#what-to-look-for)). Breeze holds about 3.1 GB of RAM and 9.9 GB of GTT while loaded (`[memory] estimate_gb = 13` with Kokoro).
- **The patch's `tools/`** (`gemm_bench.py`, `rocm_bench.py`, …) are benchmarks AIHub never runs; leave them alone.
- **GPU safety.** Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). On 2026-10-19 and 20, experimental TTS work with custom Triton kernels and HIP graphs, with the IOMMU off, corrupted about 100 files. A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- `aihub install tts` doesn't download Breeze's weights or Whisper; the block's steps do, ahead of the installer, which can't download them while it forces offline mode.
- Breeze's weights have no revision recorded in the registry.
- Breeze's torch.compile cache (`~/.cache/localtts/inductor`, 56 MB here) and MIOpen's databases (`~/.config/miopen/`, `~/.cache/miopen/`) are outside the project and not on the allowlist.
- The voices are personal and can't be reproduced; a new machine starts with none.
