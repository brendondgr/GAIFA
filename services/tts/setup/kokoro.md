<!-- aihub-setup
id = "tts-kokoro"
title = "Kokoro-82M (Speech)"
models = ["hf-cache/hub/models--hexgrad--Kokoro-82M"]
scan = []
summary = "Speech: text to speech with Kokoro's fast built-in English voices (the server and its first engine)"
gpu = true
disk_gb = 6.6
needs = ["uv", "espeak-ng", "ffmpeg"]
after = []
check = "uv pip freeze --python runtime/venvs/kokoro/bin/python | diff -q - <(sort locks/kokoro.txt) && test -f ../../data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/snapshots/f3ff3571791e39611d31c381e3a41a3af07b4987/kokoro-v1_0.pth"

[[steps]]
run = "aihub install tts"
what = "makes .venv/ in this folder with Python 3.12 from requirements.txt: the server only (about 90 MB, a minute)"

[[steps]]
run = "HF_HOME=../../data/models/hf-cache uvx --from huggingface_hub hf download hexgrad/Kokoro-82M --revision f3ff3571791e39611d31c381e3a41a3af07b4987 --include config.json --include kokoro-v1_0.pth --include 'voices/a*.pt' --include 'voices/b*.pt' && mkdir -p ../../data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/refs && printf f3ff3571791e39611d31c381e3a41a3af07b4987 > ../../data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/refs/main"
what = "Kokoro's weights and its 28 English voices into the project's Hugging Face cache (0.34 GB, the required suggestion below), with the cache's main pointed at that commit; needed before the next step, which runs offline"

[[steps]]
run = "scripts/install-runtime.sh"
what = "builds runtime/venvs/kokoro from locks/kokoro.txt (about 6.5 GB of ROCm wheels, about 10 min), writes ~/.local/bin/kokoro-tts and ~/.config/tts-engines/engines.json, and ends with a smoke test that loads Kokoro on the GPU; it stops before Breeze"

[[suggest]]
name = "Kokoro 82M with the English voices"
repo = "hexgrad/Kokoro-82M"
revision = "f3ff3571791e39611d31c381e3a41a3af07b4987"
files = ["config.json", "kokoro-v1_0.pth",
  "voices/af_alloy.pt", "voices/af_aoede.pt", "voices/af_bella.pt", "voices/af_heart.pt", "voices/af_jessica.pt",
  "voices/af_kore.pt", "voices/af_nicole.pt", "voices/af_nova.pt", "voices/af_river.pt", "voices/af_sarah.pt",
  "voices/af_sky.pt", "voices/am_adam.pt", "voices/am_echo.pt", "voices/am_eric.pt", "voices/am_fenrir.pt",
  "voices/am_liam.pt", "voices/am_michael.pt", "voices/am_onyx.pt", "voices/am_puck.pt", "voices/am_santa.pt",
  "voices/bf_alice.pt", "voices/bf_emma.pt", "voices/bf_isabella.pt", "voices/bf_lily.pt", "voices/bm_daniel.pt",
  "voices/bm_fable.pt", "voices/bm_george.pt", "voices/bm_lewis.pt"]
dest = "hf-cache"
kind = "tts"
size_gb = 0.34
good_for = "the engine's weights and its 28 American and British English voices"
licence = "Apache-2.0"
required = true
-->

# Kokoro-82M: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The Speech mod (`tts`, port 5040) has a server and two engines. The server, `python -m localtts`, runs in `.venv/` in this folder and never imports torch. Each engine runs in its own worker process, in its own venv under `runtime/venvs/`, and unloading ends that process. This doc covers the server venv and **Kokoro-82M** (`runtime/venvs/kokoro`): fast built-in voices (American and British English), the default engine for a request with no voice and no instruction. Kokoro can't clone or design voices; that's Breeze ([breeze.md](breeze.md)). Kokoro is Apache-2.0.

## Tested with

Read from this machine on 2026-10-21 (Fedora 44, Radeon 8060S / gfx1151):

| Part | Version |
|---|---|
| Server `.venv` | Python 3.12.13 (uv-managed), fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, numpy 2.5.3, soundfile 0.14.0 |
| `runtime/venvs/kokoro` | Python 3.12.13; exactly `locks/kokoro.txt` (checked with `uv pip freeze`, below) |
| torch | `torch==2.12.0a0+rocm7.13.0a20260411`, `torchaudio==2.11.0a0+rocm7.13.0a20260411`, `triton==3.7.0+git18f89f64.rocm7.13.0a20260411` |
| ROCm (wheels) | `rocm==7.13.0a20260411`, `rocm-sdk-core`, `rocm-sdk-libraries-gfx1151` (same build) |
| Wheel index | `https://rocm.nightlies.amd.com/v2/gfx1151/`, with PyPI as the extra index |
| Kokoro | kokoro 0.9.4, misaki 0.9.4, spacy 3.8.16, `en_core_web_sm` 3.8.0 (a wheel from the spacy-models GitHub release), transformers 5.17.0, huggingface-hub 1.33.0 |
| Model | `hexgrad/Kokoro-82M` at `f3ff3571791e39611d31c381e3a41a3af07b4987`, in `data/models/hf-cache/` (0.34 GB: the model and the 28 English voices) |
| Host | espeak-ng 1.52.0, ffmpeg 8.1.3 |

## Prerequisites

- [host.md](../../../docs/setup/host.md): uv, git, `espeak-ng` (Kokoro bundles one through espeakng-loader; the system package is the fallback for unknown words), `ffmpeg` (voice uploads and format conversion), the `video` and `render` groups. ROCm comes in the wheels, not from the host.
- The hub ([hub.md](../../../docs/setup/hub.md)). No account: the model is public.

## Install

```bash
aihub install tts
```

Runs `aihub-install.sh`: makes `.venv/` with Python 3.12 from `requirements.txt` (the server only).

```bash
HF_HOME=data/models/hf-cache uvx --from huggingface_hub hf download hexgrad/Kokoro-82M --revision f3ff3571791e39611d31c381e3a41a3af07b4987 --include config.json --include kokoro-v1_0.pth --include "voices/a*.pt" --include "voices/b*.pt"
```

```bash
mkdir -p data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/refs && printf f3ff3571791e39611d31c381e3a41a3af07b4987 > data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/refs/main
```

From the project folder: the model and the English voices into the project's Hugging Face cache (about 340 MB; the same files as the block's required suggestion). Do this first: the runtime installer runs offline (What to look for). The second command matters: a download by commit doesn't write the cache's `refs/main`, and Kokoro loads by `main`, so offline it wouldn't find the files.

```bash
services/tts/scripts/install-runtime.sh
```

Builds `runtime/venvs/kokoro` with uv (Python 3.12) and installs exactly `locks/kokoro.txt` from the index above (a few GB of wheels). Then it runs `engines/install.sh --gpu rocm --rocm-index … --prefix runtime/venvs/kokoro`, which keeps that torch, copies `kokoro_tts.py` into the venv, writes the `~/.local/bin/kokoro-tts` launcher, records the engine in `~/.config/tts-engines/engines.json`, and ends with a smoke test (`kokoro-tts --check`), **which loads Kokoro on the GPU**. Without `--accept-breeze-license` it stops there with a note about Breeze; with it, it goes on to [breeze.md](breeze.md). Re-running is safe. It wasn't re-run for this doc.

The two files outside the project (`~/.local/bin/kokoro-tts`, `~/.config/tts-engines/engines.json`) are on AIHub's allowlist. video-maker reads them too.

## Choosing models

Kokoro is a fixed engine: it runs one set of weights, `hexgrad/Kokoro-82M`, from the project's Hugging Face cache (`data/models/hf-cache/`), and its worker never downloads (`HF_HUB_OFFLINE=1`). There is nothing to choose but the voices. They're the `.pt` files in the repo's `voices/`; the command above takes the English ones, which are the two languages the engine is set up for (`--lang a` American, `b` British). The repo has voices for other languages too; they aren't wired in or tested here. Kokoro can't make new voices: cloned and designed voices are Breeze's ([breeze.md](breeze.md#voices)).

| Suggestion | Size | Good for | Licence | Required |
|---|---|---|---|---|
| Kokoro 82M with the English voices (`hexgrad/Kokoro-82M` at `f3ff357…`) | 0.34 GB | the engine's weights and its 28 voices | Apache-2.0 | yes |

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `LOCALTTS_KOKORO_PYTHON` | `service.toml` | yes (set) | `runtime/venvs/kokoro/bin/python` |
| `HF_HOME` | `service.toml` | yes (set) | `data/models/hf-cache`, where Kokoro's model is |
| `HF_HUB_OFFLINE` | `service.toml` | yes (set) | `1`: the workers never download |
| `LOCALTTS_DEFAULT_ENGINE` | `config.toml [services.tts].env` | optional | engine for a request with no voice and no instruction (default `kokoro`) |
| `LOCALTTS_IDLE_UNLOAD_S` | from `[memory] idle_unload_s` | optional | unload an engine after this many idle seconds (180) |
| `LOCALTTS_DATA`, `LOCALTTS_OUTPUTS_DIR`, `LOCALTTS_VOICES_DIR` | `service.toml` | yes (set) | `services/tts/data`, `outputs/tts`, `data/models/voices` |
| `LOCALTTS_LLM_URL` | `service.toml` | optional | the relay, for AI-Enhance |

The full list is in `localtts.env.example` (standalone use); under AIHub, `service.toml` and `config.toml` set them.

## Check it works

```bash
aihub check tts
```

Expect `ok` on every line but one on 2026-10-21: `FAIL widget clips series must be a non-empty list of {name, values}`, because no clips were made in the last 7 days (the widget answers an empty `series`).

```bash
curl -s http://127.0.0.1:7000/api/s/tts/v1/status
```

A GET, so nothing loads. Expect `"loaded": false`, both engines `"state": "unloaded"`, and the stat `{"label": "Engines installed", "value": 2}`.

```bash
uv pip freeze --python services/tts/runtime/venvs/kokoro/bin/python | diff - <(sort services/tts/locks/kokoro.txt)
```

Expect only `Using Python 3.12.13 environment at: services/tts/runtime/venvs/kokoro` and no diff lines: the venv is exactly the lock.

```bash
cat ~/.config/tts-engines/engines.json
```

Expect a `kokoro` entry with `"backend": "rocm"`, `"torch": "2.12.0a0+rocm7.13.0a20260411"` and this clone's `runtime/venvs/kokoro` as `home`.

## What to look for

- **The runtime installer runs offline.** `install-runtime.sh` exports `HF_HUB_OFFLINE=1` unless you set it. On a machine without the model, Kokoro's smoke test can't download it and fails with `LocalEntryNotFoundError` (offline mode), and `set -e` stops the script before Breeze. Download the model first (Install). Setting `HF_HUB_OFFLINE=0` for that one run also lets it download (not tried here). The engine is recorded in `engines.json` before the smoke test, so a failed test still leaves an entry.
- **Kokoro's venv uses an older ROCm** (7.13, April) than Breeze's (10.2, September). They're separate venvs on purpose; don't merge them.
- **Worker settings** (`workers/kokoro_worker.py`, `localtts/engines.py`): `MIOPEN_FIND_MODE=2` (MIOpen's fast find), `MIOPEN_LOG_LEVEL=3` (errors only), and `ROCPROFILER_REGISTER_ENABLED=0`. Without that last one the ROCm nightly torch loads rocprofiler-sdk, and an idle worker pins a CPU core and keeps the GPU at 100 %.
- **A loaded engine shows the GPU 100 % busy even when idle** (the compute processor polls its queue; about 45 W instead of 17 W). It stops when the engine unloads, hence the short idle unload.
- **The nightly wheel index drops old builds.** `locks/kokoro.txt` pins exact nightly builds (torch, torchaudio, triton, the `rocm*` packages, all of build `7.13.0a20260411`) from `https://rocm.nightlies.amd.com/v2/gfx1151/`, and nightly indexes don't keep every build: on 2026-10-21 `https://nightly.repo.amd.com/rocm/whl-next/` listed only the last two months of torch builds (2026-08-23 to 2026-10-20), and `https://rocm.nightlies.amd.com/v2/gfx1151/` Linux builds from 2026-01-01 to 2026-05-13; both still had the pinned ones. When a pinned wheel is gone, the install stops at uv's resolve ("No solution found", naming the package). Then:
  1. On a machine that built this venv before, uv's cache (`~/.cache/uv`) still holds the wheels and the installer goes on as is; don't `uv cache clean` or `uv cache prune` it (`aihub backup` doesn't copy it).
  2. Otherwise pick one build the index still has, `curl -sL https://rocm.nightlies.amd.com/v2/gfx1151/torch/ | grep -o 'torch-[^"<#]*cp312-cp312-linux_x86_64.whl' | tail -3`, change **every** package of the old build in the lock to that same build (their versions all end in the same `rocm…a<date>`; triton's also carries a git hash, so copy the names from the index, `curl -sL https://rocm.nightlies.amd.com/v2/gfx1151/<package>/`), re-run `scripts/install-runtime.sh`, and let its smoke test or check prove it. Record the new versions in Tested with. A different build is untested here: watch for new errors before trusting its output.
- **GPU safety.** Use the pinned wheels in the lock. Don't add custom kernels or HIP graphs. Keep the IOMMU on ([host.md §1](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). A GPU ring timeout or a failed GPU reset in `journalctl -k` is a reason to stop and check for Btrfs checksum errors (host.md, What to look for).

## Known gaps

- `aihub install tts` builds only the server venv; the model download and `install-runtime.sh` are separate steps (in the block, for `aihub setup`).
- `aihub check tts` isn't the block's check: on a fresh install its clips widget fails (`series must be a non-empty list`) until a clip is made.
- MIOpen keeps its databases in `~/.config/miopen/` and `~/.cache/miopen/` (both exist here), outside the project and not on the allowlist.
- On another GPU, `engines/setup.sh --plan` picks a torch build instead of the locks; that path isn't documented here.
