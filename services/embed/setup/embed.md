<!-- aihub-setup
id = "embed"
title = "Embeddings: EmbeddingGemma 2"
models = ["embed/**"]
scan = []
-->

# Embeddings: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `embed` mod (port 5104) serves **EmbeddingGemma 2** (`google/embeddinggemma-2`, Apache 2.0). It maps text, code, images, audio and video into one 768-d space, with Matryoshka sizes 512, 256 and 128 and an 8k-token context. The mod's `.venv/` holds ROCm PyTorch and sentence-transformers. The server itself never imports torch: a spawned worker process loads the model, and unloading ends that worker, so all of its memory comes back. Search by meaning needs this environment: the library index and its agent tools (plan 28.2–28.3) and the Outputs page's "by meaning" toggle (28.4).

## Tested with

Read from this machine on 2026-10-20 (Fedora 44, kernel 7.2.11, Radeon 8060S / gfx1151):
- Python 3.12.13 (uv-managed), from `locks/embed.txt`:
  - torch `2.15.0a0+rocm10.2.0a20260926` with `amd-torch-device-gfx1151`, and torchvision `0.30.0a0+rocm10.2.0a20260926` with `amd-torchvision-device-gfx1151`. Both come from `https://nightly.repo.amd.com/rocm/whl-next/`, the same torch line as tts's Breeze (`services/tts/locks/breeze-tts.txt`); HIP 7.17.
  - transformers 5.20.2, sentence-transformers 6.1.0 (the model card asks for ≥ 6.1.0), numpy 2.5.4.
- ffmpeg 8.1.3 (host package).
- The model at revision `914f7f89142e33e77833254d9c9b90c3cef7303b` (2026-10-06): one `model.safetensors`, 1.49 GB in bf16.

## Prerequisites

- uv, and `ffmpeg` / `ffprobe` on `PATH` for audio and video inputs ([host.md](../../../docs/setup/host.md)).
- The hub running, for media inputs: images, audio and video are output ids, read through `GET /api/outputs/{id}/file`.
- No account or token: the repo isn't gated.

## Install

```bash
aihub install embed
```

Runs `install.sh`:
1. Makes `.venv/` with Python 3.12 and installs the exact packages in `locks/embed.txt` from the ROCm nightly index (about 4 GB of wheels; 6 s from uv's cache, a few minutes cold).
2. Downloads the model into `data/models/embed/embeddinggemma-2/` if it isn't there (1.5 GB; `hf download … --local-dir`, with `HF_HOME` inside the project, never `~/.cache`).

On first start the mod registers the model with the hub (`POST /api/models`, kind `text-encoder`, tags `embedding` and `multimodal`, source with the revision). Registering again is harmless.

Another machine without this GPU:

```bash
services/embed/install.sh --cpu
```

The same packages unpinned, with PyTorch's CPU wheels. The model then runs in fp32 (see What to look for).

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `EMBED_MODEL_DIR` | `service.toml` `[run.env]` | yes (set) | the weights, `{models}/embed/embeddinggemma-2` |
| `EMBED_STATE_DIR` | `service.toml` | yes (set) | `data/state/embed/`: `memory.json` (the measured memory per encoder set) and the temporary copies ffmpeg reads |
| `EMBED_DEVICE` | `service.toml` / `config.toml [services.embed].env` | no | `auto` (default: the GPU when torch sees one), `cuda`, `cpu` |
| `EMBED_IDLE_UNLOAD_S` | the mod's Settings tab (`idle_unload_s`) | no | unload after this many idle seconds; default 300, 0 = never |
| `EMBED_MAX_INPUTS`, `EMBED_AUDIO_MAX_S`, `EMBED_BATCH_TEXT`, `EMBED_BATCH_MEDIA` | `config.toml` env | no | 256 inputs a call; audio cut at 320 s (25 tokens a second fills the 8k context); batches of 32 texts and 4 images |
| `EMBED_INDEX` | `service.toml` | no | `1` (default): the library follows the hub's outputs and indexes them into `data/databases/embed.db`; `0` turns it off |
| `EMBED_IDLE_SOURCE` | `service.toml` | no | how the library tells the GPU is free: `engine` (default; other processes' DRM engine time from `/proc/*/fdinfo`) or `busy_percent` (`gpu_busy_percent`; see What to look for) |
| `EMBED_IDLE_BUSY_PCT`, `EMBED_IDLE_SECONDS` | `service.toml` | no | indexing starts once the GPU has stayed under 10 % for 300 s, and stops between batches when it isn't |
| `EMBED_INDEX_BATCH_TEXT`, `EMBED_INDEX_GAP_S`, `EMBED_INDEX_AUDIO_MAX_S` | `config.toml` env | no | 8 chunks a batch; 1 s between batches before the next look at the GPU; audio indexed up to an hour |

## Check it works

```bash
aihub start embed && aihub check embed
```

Expect `embed: all checks passed`.

```bash
services/embed/.venv/bin/python -m pytest -q -m gpu
```

Run in `services/embed/`. Loads the real model in a worker: each of three drawn shapes is found by its text, each kind embeds, and unloading ends the worker. Expect `3 passed` (about 15 s). The unit tests (`pytest -q`, fake backend, no GPU) expect `20 passed`.

The live check (2026-10-20, through the hub, three real pictures from `services/gen3d/runtime/lab/input/` and the Hunyuan3D demo): "a samurai warrior with a sword", "a penguin holding a sign" and "a white ceramic vase" each rank their own picture first (cosine 0.73, 0.78 and 0.62 against 0.49–0.54 for the others), at 768, 512, 256 and 128 dimensions.

**Measured here** (bf16 on the GPU, the hub's count: PSS plus GTT):

| Loaded | Memory | Load |
|---|---|---|
| nothing (server only) | 0.06 GB | |
| text path (270M) | 3.0 GB | 9 s on the first call (worker start, torch import, ROCm init) |
| + vision encoder (images, video) | 3.9 GB | 2.6 s (reloads inside the worker) |
| + audio encoder | 5.4 GB | 3.0 s |
| after unload | 0.10 GB | |

| Input | Encode time |
|---|---|
| 64 short texts (~20 tokens each) | 107 ms in all |
| 1 text of ~2.4k tokens | 125 ms |
| 1 image | 0.18 s (3 images: 0.45 s) |
| 20 s video (20 frames at 1 fps) | 1.5 s |
| 30 s audio | 0.15 s |

Decoding through ffmpeg adds 0.1 s for audio and 0.2 s for video. On the CPU (fp32, `EMBED_DEVICE=cpu`) the rankings are the same but it's slow: 64 texts in 30 s, about 22 s an image.

**The library** (2026-10-20, against a dev hub with 32 outputs: two documents, 24 pictures, audio and video clips): all 32 indexed into 90 chunks in about 140 s once the GPU had been quiet, with one pause midway when something else used the GPU. Then the model unloaded. Much of that time is the 1 s look at the GPU after each batch. Indexing records the text path at 3.1 GB.

**Search** (plan 28.3): `POST /v1/search` and the agent's tools `embed_library_search` and `embed_library_collections`. On the same hub, "the picture of the red car" ranks the drawn car first at 0.75, with the other pictures at or below 0.59. A search of everything first indexes pending outputs from the last day, for up to 10 s; a search within a chat or collection first indexes all of its outputs, for up to 120 s. Either can take seconds right after a large upload.

## What to look for

- **Never fp16.** The model card says activations overflow fp16 (NaN, or quietly bad vectors). The backend picks bf16 when `torch.cuda.is_bf16_supported()` and fp32 otherwise.
- **Never `malloc_trim` in a ROCm process here.** On 2026-10-20 a `malloc_trim(0)` after loading, added to give back the heap the weights were read into, came just before the server and another mod's GPU worker crashed in the HSA/HIP runtimes and the kernel reported corrupt page tables (bf16 −inf patterns). The same boot also had disk checksum errors from hours earlier, so the cause isn't certain. The worker process makes it unneeded either way: unloading ends the worker.
- **A worker crash** (a segfault in `libhsa-runtime64`) answers `503 worker_died` with a fix; the server stays up, and the next call starts a new worker. Repeated crashes: `aihub logs embed` and `journalctl -k`.
- **The measured memory** grows after the first encode (kernels, allocator caches), so `memory.json` keeps the most seen per encoder set. `/v1/status` reports it as `memory_estimate_gb`. Delete `data/state/embed/memory.json` to measure again.
- **Matryoshka:** a slice of a unit vector isn't one, so the mod normalizes again after truncating (sentence-transformers' `truncate_dim` with `normalize_embeddings` normalizes *before* truncating). Queries and documents must use the same `dim`.
- **Prompts:** text with `task: "query"` gets `task: search result | query: `, documents get `title: {title or none} | text: `. Media take no prompt.
- **Video** is decoded at 1 fps and scaled to fit 768 px. A video longer than 32 s is sampled evenly down to 32 frames (the processor's own cap). An mp4 often keeps its index at the end, so ffmpeg reads a temporary copy in `data/state/embed/tmp/`, never a pipe.
- **`gpu_busy_percent` is noisy on gfx1151.** With nothing running it reads 13–17 % and jumps to 80–90 % about every 15 s, while the DRM engine counters of every process add up to 3.5 % (measured 2026-10-20). "Under 10 % for 5 minutes" never holds on it, so the default source is `engine`: the busiest engine's share of time across every process except the embed mod's own. `GET /v1/library` shows the reading (`gpu.busy_pct`) and how long it's been quiet.
- **Indexing never evicts another mod.** It asks the hub for memory without making room; a `409 needs_room` leaves the library in `no_room` until the next quiet period. A search still loads the model the usual way, and the [memory] triggers make room for it.
- **Weights through a symlink** are refused by the hub's registry (`doesn't exist in data/models`): keep them as a real folder.

## Known gaps

- CPU speed: matmul runs at 0.9 TFLOP/s in fp32 here, so the slowness is elsewhere in the model's CPU path. Not looked into further.
- The vision token budget is the default (280 tokens an image, 140 a video frame); the card allows 70–1120.
