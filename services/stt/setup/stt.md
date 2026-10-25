<!-- gaifa-setup
id = "stt"
title = "Speech to Text (faster-whisper)"
models = ["stt/**"]
scan = []
summary = "Speech to text: transcribe audio and video files, live dictation and the Chat microphone (Whisper; runs on the CPU, much faster with the GPU)"
gpu = false
disk_gb = 0.75
needs = ["uv", "curl", "unzip", "ffmpeg"]
check = "gaifa check stt --start"
smoke = "gaifa start stt >/dev/null && curl -fsS -X POST -H 'content-type: application/json' -d '{\"preset\": \"fast\"}' \"$(gaifa url api/s/stt/v1/load)\" >/dev/null && curl -fsS \"$(gaifa url api/s/stt/v1/status)\" | tee /dev/stderr | grep -q '\"loaded\": *true'"   # plan 39: real work, run by gaifa setup --smoke and the field test

[[steps]]
run = "gaifa install stt"
what = "makes .venv/ (Python 3.14, about 250 MB), then for the variant: ROCm puts the ROCm build of CTranslate2 in (its release zip with curl and unzip, about 400 MB, from GitHub, unless a wheel is kept in runtime/wheels/; it needs host.md's ROCm packages), CUDA adds NVIDIA's cuBLAS and cuDNN 9 pip packages (about 1 GB), the CPU needs nothing more"

[[suggest]]
name = "Whisper small (the balanced preset)"
op = "POST /v1/load"
body = { preset = "balanced" }
size_gb = 0.49
good_for = "the default: dictation and files at about 30x real time on the GPU"
licence = "MIT"

[[suggest]]
name = "Whisper large-v3-turbo (the accurate preset)"
op = "POST /v1/load"
body = { preset = "accurate" }
size_gb = 1.62
good_for = "nearly large-v3's accuracy at about four times its speed; long or noisy recordings"
licence = "MIT"

[[variants]]                    # plan 39.5: the ROCm build of CTranslate2 (and host.md's ROCm packages)
accel = "rocm"
os = ["linux"]
tested = true

[[variants]]                    # PyPI's CTranslate2 is built with CUDA 12; cuBLAS and cuDNN come from pip
accel = "cuda"
os = ["linux", "wsl"]
needs = ["uv", "ffmpeg"]

[[variants]]                    # everywhere else (CTranslate2 has no Metal or xpu backend)
accel = "cpu"
os = ["linux", "wsl", "darwin"]
needs = ["uv", "ffmpeg"]
tested = ["linux"]
note = "Whisper small transcribes about as fast as real time on a modern CPU"
-->

# Speech to Text (faster-whisper): setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `stt` mod's one environment: `.venv/` in this folder, with faster-whisper on CTranslate2 and the ROCm build of CTranslate2 put over PyPI's CPU/CUDA one. The server (`server.py`) never touches the GPU; the model runs in a worker process (`python -m stt.asr.worker`) that it restarts after a GPU fault, moving to the CPU after three faults in ten minutes. Everything the mod does needs this environment: file transcription (`POST /v1/transcribe`), the live stream and the Chat microphone. **It runs without a GPU:** with no `/dev/kfd` the installer leaves PyPI's CPU build of CTranslate2 in, and `STT_DEVICE=auto` picks the CPU (int8), which is correct but much slower; the GPU needs the host ROCm packages below. Ported from the TranscriberPrototype ("Loud Radish", `~/Projects/TranscriberPrototype`).

## Tested with

Read from this machine on 2026-10-20 (Radeon 8060S, gfx1151, Fedora 44):

| Part | Version |
|---|---|
| Python | 3.14.6 (uv-managed) |
| faster-whisper | 1.2.1 |
| CTranslate2 | 4.8.1, ROCm build `ctranslate2-4.8.1-cp314-cp314-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` (sha256 `e5420e7f282502afc6fc768368eb44629afd3cf0f151efadbe907ef13f1f36e0`) |
| onnxruntime | 1.31.0 (Silero VAD; the model ships inside faster-whisper) |
| numpy, soxr | 2.5.4, 1.1.0 |
| ROCm (host packages) | rocm-hip 7.1.1, rocblas 7.1.1, hipblas 7.1.0, hiprand 7.1.0, rocrand 7.1.0 |
| ffmpeg | 8.1.3 (host; decodes every input, and video's audio track) |

## Prerequisites

- For the GPU, the host ROCm runtime packages above, which CTranslate2's ROCm build links against ([host.md §3](../../../docs/setup/host.md#3-packages); `hiprand` and `rocrand` are the two a base ROCm install leaves out):

  ```bash
  sudo dnf install rocm-hip rocblas hipblas hiprand rocrand
  ```

  `rpm -q rocm-hip rocblas hipblas hiprand rocrand` lists them (here: the versions in Tested with). Without them it runs on the CPU.
- `ffmpeg` ([host.md §3](../../../docs/setup/host.md#3-packages)), at run time: it decodes every input but WAV. Without it only WAV files can be read.
- `curl` and `unzip`, for the installer's wheel download (GPU machines only).
- `uv` on `PATH`.
- No accounts: the models are public on Hugging Face.

## Install

```bash
gaifa install stt
```

Runs `install.sh`: makes `.venv/` with uv-managed Python 3.14 from `requirements-dev.txt` (about 250 MB, a minute), then, on a machine with `/dev/kfd`, reinstalls CTranslate2 from the ROCm wheel kept in `runtime/wheels/` (gitignored). When no wheel is kept there it downloads `rocm-python-wheels-Linux.zip` (about 400 MB) from the [CTranslate2 v4.8.1 release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.1) and keeps the `cp314-cp314` wheel.

## Choosing models

The mod runs **faster-whisper's CTranslate2 conversions of Whisper**, from a fixed list (`stt/catalog.py`): `tiny` to `large-v3`, picked by preset or by name. None is needed to install it: a model is fetched on first use into `data/models/stt/<name>/` and registered in the models registry. The suggestions are two presets; Whisper's weights are MIT-licensed. To fetch one ahead of time (it loads it, too):

```bash
curl -X POST http://127.0.0.1:7000/api/s/stt/v1/load -H 'content-type: application/json' -d '{"preset": "balanced"}'
```

A model already in `~/.cache/huggingface/hub/` is copied from there instead of downloaded (reading outside the project is fine; nothing is written there).

| Preset | Model | Size | Runs at |
|---|---|---|---|
| `fast` | `base` | 142 MB | float16 on the GPU |
| `balanced` (the default) | `small` | 464 MB | float16 on the GPU |
| `accurate` | `large-v3-turbo` | 1.6 GB | float16 on the GPU |
| `best` | `large-v3` | 3.1 GB | float16 on the GPU |
| by name | `tiny`, `medium` | 75 MB, 1.5 GB | float16 on the GPU |

On the CPU every model runs at int8.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `STT_DEVICE` | `[run.env]` | optional | `auto` (the GPU when CTranslate2 sees one), `cpu` or `cuda` |
| `STT_IDLE_UNLOAD_S` | from `[memory] idle_unload_s` | optional | unload the model after this many idle seconds; `0` never (default 300). An open live stream or a running job keeps it loaded, however long the silence |
| `STT_BACKEND` | env | optional | `faster-whisper`, or `mock` (a scripted model, for tests) |
| `STT_ALLOW_UNSAFE_COMPUTE` | env | optional | `1` lets int8 `small` and up load on an AMD GPU (it faults gfx1151) |
| `STT_NO_GPU_REPAIR` | env | optional | `1` stops the worker from reinstalling the kept ROCm wheel |

## Check it works

```bash
gaifa check stt --start
```

Starts the mod if it's stopped (a stopped mod's live checks are skipped), then checks it. Expect `all checks passed`. Then the tests (the GPU test loads `small` and unloads it):

```bash
cd services/stt && .venv/bin/python -m pytest -q
```

```bash
cd services/stt && STT_GPU_TESTS=1 .venv/bin/python -m pytest -q -s tests/test_gpu.py
```

Expect `small on the GPU: 25.3 s of audio in 0.9 s, real-time factor 0.036` or close to it (2026-10-20).

```bash
cd services/stt && .venv/bin/python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
```

Expect `1`; `0` means the PyPI build is installed (rerun `gaifa install stt`).

## What to look for

- **int8 `small` and up on gfx1151 aborts the process** with "Memory access fault by GPU node-1" rather than raising. The mod never picks it (float16 on the GPU, int8 only on the CPU) and refuses it before the load if asked (`stt/asr/acceleration.py`).
- **`uv` puts PyPI's CTranslate2 back** whenever it syncs the package; `ctranslate2.get_cuda_device_count()` then says `0` and everything runs on the CPU, slowly but correctly. Each worker start reinstalls the kept wheel when the installed one didn't come from it.
- **A GPU fault costs a restart, not the server.** `GET /v1/status` → `engine.notices` lists each restart; after three in ten minutes `engine.fell_back` is true and `device` is `cpu`.
- **Garbage text in many languages at 10–30× the normal time** means the GPU's arithmetic is wrong, not the model: on 2026-10-20 it appeared together with a kernel oops and btrfs checksum errors, and a clean run of the same file minutes earlier. Check `journalctl -k -b` before blaming the mod.
- **One model at a time, and a model in use stays.** An open live stream or a running file job holds its model: asking for another one answers `409 busy` (`/v1/load`) or closes the stream with 4409 `busy`, and a queued job waits in stage `waiting` until the stream ends. `POST /v1/unload` still unloads; a stream that is still open loads the model again on its next word.
- **GAIFA's GPU slot** (`[gpu]`, `stt/gpu.py`, plan 31.3). A file job on the GPU waits in stage `waiting_gpu` (state `queued`, with `ahead` and `eta_s`) while another mod's work holds the GPU. Live dictation never waits: when another mod holds the slot at its start, it runs on the CPU (`small` at most, int8; `ready.reason` says why); otherwise it holds an `interactive` lease and, once another mod's work waits, loads the CPU model, moves to it between two frames (`{"type": "device", "device": "cpu", "reason"}`) and gives the slot back. `GET /v1/status` → `streams` lists each open stream's device and reason.
- **Uploads wait in `runtime/tmp/`** (up to 4 GB each) until their job ends, cancelled or not. At most 8 wait at once (then `429 queue_full`); a full disk answers `507 no_space`; files older than an hour are swept when the mod starts.
- Whisper invents text over silence ("thank you", "bye"). The ported hallucination filter (`stt/asr/hallucination.py`) and Whisper's own VAD filter drop it; a silent file gives an empty transcript.

## Known gaps

- `gaifa install stt` doesn't check the ROCm packages; a missing `libhiprand.so.1` shows up as the CPU being used.
- The wheel is pinned to CTranslate2 4.8.1 and Python 3.14; a newer faster-whisper that needs another CTranslate2 needs a new wheel.
