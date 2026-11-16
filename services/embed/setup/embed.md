<!-- gaifa-setup
id = "embed"
title = "Embeddings"
models = ["embed/**"]
scan = []
summary = "Embeddings: search outputs, documents and chats by meaning (text, images, audio, video in one space)"
recommended = true   # offered first for chat (capability-enablement 1.4)
gpu = true
disk_gb = 6.6
needs = ["uv"]
check = "gaifa start embed && gaifa check embed"
smoke = "gaifa start embed >/dev/null && r=$(curl -fsS -X POST -H 'content-type: application/json' -d '{}' \"$(gaifa url api/s/embed/v1/selftest)\") && echo \"$r\" && echo \"$r\" | grep -q '\"passed\": *true'"   # plan 39, capability-enablement 7.2: real work, measured (one sentence)

[[steps]]
run = "gaifa install embed"
what = "makes .venv/ with PyTorch for this machine's variant (on gfx1151 locks/embed.txt: ROCm nightly torch, about 4 GB of wheels, 6.6 GB installed; elsewhere requirements.txt from the variant's index) and downloads EmbeddingGemma 2 (1.5 GB)"

[[suggest]]
name = "EmbeddingGemma 2"
repo = "google/embeddinggemma-2"
revision = "914f7f89142e33e77833254d9c9b90c3cef7303b"
files = []
dest = "embed/embeddinggemma-2"
kind = "text-encoder"
size_gb = 1.53
good_for = "the full encoder: 768-d vectors for text, code, images, audio and video in one space"
licence = "Apache-2.0"
default = true                  # capability-enablement 7.3: the default choice, not required: a smaller one may replace it

[[suggest]]                     # 7.3: about a third of the size; measured in docs/embed-models.md
name = "BGE base (English)"
repo = "BAAI/bge-base-en-v1.5"
revision = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
exclude = ["onnx/*", "*.bin"]
dest = "embed/bge-base-en-v1.5"
kind = "text-encoder"
size_gb = 0.44
good_for = "text only, English, 768-d: three times as fast on a GPU and on the CPU; pictures, audio and video aren't searched (their titles are)"
licence = "MIT"
next = "chosen alone, the mod uses it; beside EmbeddingGemma 2, switch with Settings → Agent → Memory → Change…"

[[suggest]]                     # 7.3: about a tenth of the size
name = "BGE small (English)"
repo = "BAAI/bge-small-en-v1.5"
revision = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
exclude = ["onnx/*", "*.bin"]
dest = "embed/bge-small-en-v1.5"
kind = "text-encoder"
size_gb = 0.13
good_for = "text only, English, 384-d: the smallest and fastest, for a machine without a GPU; pictures, audio and video aren't searched (their titles are)"
licence = "MIT"
next = "chosen alone, the mod uses it; beside EmbeddingGemma 2, switch with Settings → Agent → Memory → Change…"

[[find]]                        # capability-enablement 7.1: where such models are compared
label = "Embedding models compared (MTEB leaderboard)"
url = "https://huggingface.co/spaces/mteb/leaderboard"
note = "local models only; pick by size and score for your machine"

[[variants]]                    # plan 39.3: this machine's (gfx1151's exact lock)
accel = "rocm"
os = ["linux"]
tested = true

[[variants]]
accel = "cuda"
os = ["linux", "wsl"]

[[variants]]
accel = "xpu"
os = ["linux", "wsl"]

[[variants]]
accel = "mps"
os = ["darwin"]

[[variants]]
accel = "cpu"
os = ["linux", "wsl", "darwin"]
note = "slower; fp32"
-->

# Embeddings: setup

**The easy way:** paste the text of `gaifa setup --prompt embed` into your coding agent (Claude Code, Codex): it reads this doc, runs the same commands and checks, and can fix what goes wrong. Or run `gaifa setup embed` yourself.

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
gaifa install embed
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

## Choosing models

EmbeddingGemma 2 is the **default**, not required (capability-enablement 7.3): the model question also offers two smaller text-only encoders, measured on this machine and on the CPU in [docs/embed-models.md](../../../docs/embed-models.md). `install.sh` downloads EmbeddingGemma 2; `--no-weights` skips that. The others come from the model question (`gaifa setup embed`), into `data/models/embed/<id>/`.

| Model | Size | Good for | Gives up | Licence |
|---|---|---|---|---|
| [google/embeddinggemma-2](https://huggingface.co/google/embeddinggemma-2) at `914f7f89` (default) | 1.5 GB | text, code, images, audio and video in one 768-d space (Matryoshka 512/256/128), 8k context, many languages | the largest and slowest of the three | Apache-2.0 |
| [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) at `a5beb1e3` | 0.44 GB | English text, 768-d; about three times as fast | pictures, audio and video (their titles are still searched), other languages, 512-token inputs | MIT |
| [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) at `5c38ec7c` | 0.13 GB | English text, 384-d; the fastest, for a machine without a GPU | the same, and a little less accurate | MIT |

**Any other model.** A sentence-transformers text encoder runs with no code: put it in `data/models/embed/<id>/` with a `gaifa-model.toml` (`name`, `dim`, `dims`, `kinds = ["text"]`, `query_prompt`, `document_prompt` with `{title}` and `{text}`, `dtype`, `size_gb`; the format is in `embed/models.py`). The two above have theirs in `services/embed/models/`. A model that needs `trust_remote_code` isn't loaded.

**Which one is used.** `EMBED_MODEL` (default `embeddinggemma-2`), unless a switch saved another in `data/state/embed/model.json`; a model with no weights falls back to the first one that has them (so a setup with BGE small alone uses it). **Changing it** (`POST /v1/model {"model": "<id>"}`, or **Change…** on Settings → Agent → Memory and the Embeddings page) builds the new model's index beside the one in use (`data/databases/embed-<id>.db`; EmbeddingGemma 2's stays `embed.db`), in the background under the library's GPU and memory rules: every output, the chat summaries, the agent's memory texts and the collections. Search keeps using the old model until the new index is ready; then the mod restarts on the new one. Switching back finds the old index where it was and embeds only what changed meanwhile. `GET /v1/models` lists the models, the one in use and a switch in progress; `DELETE /v1/model/switch` stops one.

A text-only model answers a search for pictures, audio or video (`kind`) and an embed of one with `422 needs_full_model` and the fix.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `EMBED_MODEL_DIR` | `service.toml` `[run.env]` | yes (set) | the weights, `{models}/embed/embeddinggemma-2` |
| `EMBED_STATE_DIR` | `service.toml` | yes (set) | `data/state/embed/`: `memory.json` (the measured memory per encoder set) and the temporary copies ffmpeg reads |
| `EMBED_DEVICE` | `service.toml` / `config.toml [services.embed].env` | no | `auto` (default: the GPU when torch sees one), `cuda`, `cpu` |
| `EMBED_WORKER_PYTHON` | `config.toml [services.embed].env` | no | the model's worker runs in this Python instead: a CPU-only torch venv, so a CPU run never opens `/dev/kfd` (a ROCm torch build opens it on its first CPU op even with `EMBED_DEVICE=cpu`, and rejects `-1` in `HIP_VISIBLE_DEVICES`/`ROCR_VISIBLE_DEVICES` with a fatal error). Build one with `uv venv` and `uv pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match -r services/embed/requirements.txt` |
| `EMBED_IDLE_UNLOAD_S` | the mod's Settings tab (`idle_unload_s`) | no | unload after this many idle seconds; default 300, 0 = never |
| `EMBED_MAX_INPUTS`, `EMBED_AUDIO_MAX_S`, `EMBED_BATCH_TEXT`, `EMBED_BATCH_MEDIA` | `config.toml` env | no | 256 inputs a call; audio cut at 320 s (25 tokens a second fills the 8k context); batches of 32 texts and 4 images |
| `EMBED_INDEX` | `service.toml` | no | `1` (default): the library follows the hub's outputs and indexes them into `data/databases/embed.db`; `0` turns it off |
| `EMBED_INDEX_BATCH_TEXT`, `EMBED_INDEX_AUDIO_MAX_S` | `config.toml` env | no | 8 chunks a batch, each under its own `background` lease from GAIFA's GPU queue (plan 31.3: it replaced the `EMBED_IDLE_*` gate); audio indexed up to an hour |

## Check

```bash
gaifa check embed --start
```

Expect `embed: all checks passed`.

```bash
curl -s -X POST -H 'content-type: application/json' -d '{}' "$(gaifa url api/s/embed/v1/selftest)"
```

Expect `"passed":true` and a sentence such as `"sentence":"EmbeddingGemma 2 on your GPU: 354 texts a second, 3.4 GB"` (a smaller model names itself; on the CPU: `on the CPU`). That is the test the Set up dialog and Settings → Services run.

```bash
curl -s -X POST -H 'content-type: application/json' -d '{"query":"a picture of a dog"}' "$(gaifa url api/s/embed/v1/search)" | head -c 200
```

Expect `{"results":[…` (empty on a new install until outputs are indexed): search by meaning works.

## When it fails

| What you see | What to check | The fix |
|---|---|---|
| the test answers `no_weights` | `ls data/models/embed/` | `gaifa setup embed` (the model question), or `services/embed/install.sh` |
| it ran `on the CPU` though you have a GPU | `gaifa hardware` | the GPU's host setup (docs/setup/), then `gaifa setup embed --accel embed=<rocm\|cuda\|xpu\|mps>`; or keep the CPU with a smaller model |
| the CPU is slow (a few texts a second) | the torch in `services/embed/.venv` is a GPU build | `gaifa setup embed --accel embed=cpu` (a CPU-only torch), and pick BGE small (docs/embed-models.md) |
| a picture search answers `needs_full_model` | `curl -s "$(gaifa url api/s/embed/v1/models)"` (`model`) | a text-only model is in use: Settings → Agent → Memory → Change… to EmbeddingGemma 2 |
| search finds nothing new | `curl -s "$(gaifa url api/s/embed/v1/library)"` (`state`, `counts.pending`) | it indexes when the GPU is idle; `waiting_gpu` or `no_room` say why it waits |
| a model switch stopped (`failed`) | the switch's `error` in `GET /api/s/embed/v1/models` | fix what it names (room, weights), then Change… again; the old model stays in use meanwhile |
| `gaifa status` shows embed `not set up`; a chat says it isn't set up | `ls services/embed/.venv` | `gaifa setup embed` (or the Set up dialog: Settings → Services → Set up) |
| `gaifa status` shows embed `failed` | `gaifa logs embed` (the last lines say why) | fix what the log names, then `gaifa start embed`; still failing: `gaifa setup --prompt embed` for your coding agent |
| embed is off (Settings → Services shows its switch off) | Settings → Services | turn its switch on, or ask GAIFA's agent to turn it on; `gaifa start embed` starts it once |

## What to look for

- **The nightly wheel index drops old builds.** `locks/embed.txt` pins torch and ROCm build `10.2.0a20260926` from `https://nightly.repo.amd.com/rocm/whl-next/`, which on 2026-10-21 kept only about the last two months of builds. When a pinned wheel is gone, `gaifa install embed` stops at uv's resolve ("No solution found"); what to do is in [Breeze's doc](../../tts/setup/breeze.md#what-to-look-for) (uv's cache first, else move every package of the build to one the index still has, together).
- **Never fp16.** The model card says activations overflow fp16 (NaN, or quietly bad vectors). The backend picks bf16 when `torch.cuda.is_bf16_supported()` and fp32 otherwise.
- **Never `malloc_trim` in a ROCm process here.** On 2026-10-20 a `malloc_trim(0)` after loading, added to give back the heap the weights were read into, came just before the server and another mod's GPU worker crashed in the HSA/HIP runtimes and the kernel reported corrupt page tables (bf16 −inf patterns). The same boot also had disk checksum errors from hours earlier, so the cause isn't certain. The worker process makes it unneeded either way: unloading ends the worker.
- **A worker crash** (a segfault in `libhsa-runtime64`) answers `503 worker_died` with a fix; the server stays up, and the next call starts a new worker. Repeated crashes: `gaifa logs embed` and `journalctl -k`.
- **The measured memory** grows after the first encode (kernels, allocator caches), so `memory.json` keeps the most seen per encoder set. `/v1/status` reports it as `memory_estimate_gb`. Delete `data/state/embed/memory.json` to measure again.
- **Matryoshka:** a slice of a unit vector isn't one, so the mod normalizes again after truncating (sentence-transformers' `truncate_dim` with `normalize_embeddings` normalizes *before* truncating). Queries and documents must use the same `dim`.
- **Prompts:** text with `task: "query"` gets `task: search result | query: `, documents get `title: {title or none} | text: `. Media take no prompt.
- **Video** is decoded at 1 fps and scaled to fit 768 px. A video longer than 32 s is sampled evenly down to 32 frames (the processor's own cap). An mp4 often keeps its index at the end, so ffmpeg reads a temporary copy in `data/state/embed/tmp/`, never a pipe.
- **What "idle" meant (plan 28.2, replaced by the GPU queue in plan 31.3).** `gpu_busy_percent` reads 13–17 % with only the desktop running (Xwayland, plasmashell, browsers) and jumps to 80–90 % about every 15 s, so the `gaifa` measure asks what GAIFA's mods are doing instead, and keeps the whole GPU only as a 30 s median (spikes don't count) against 30 %. Per-process busy time isn't available for ROCm: a test mod running torch matmuls kept the GPU at 98 % while its DRM fdinfo engine counters stayed at 0 (compute goes through `/dev/kfd`'s user-mode queues), and `/sys/class/kfd/kfd/proc/<pid>/` here has only queues, VRAM and `evicted_ms`. `GET /v1/library` shows the reading, the mods it saw working and the device's median.
- **Indexing never evicts another mod.** It asks the hub for memory without making room; a `409 needs_room` leaves the library in `no_room` until the next quiet period. A search still loads the model the usual way, and the [memory] triggers make room for it.
- **Weights through a symlink** are refused by the hub's registry (`doesn't exist in data/models`): keep them as a real folder.

## Known gaps

- **GPU checks waiting for the machine to be checked** (paused 2026-10-20 after crashes in GPU work): the GPU tests (`pytest -m gpu`) on the final code, the idle gate's resume after another mod's GPU load (seen once), indexing pictures, audio and video at GPU speed, and 28.5's chat search in bf16 (run in fp32 on the CPU).
- With the model on the CPU, a search waits for the indexer's batch in flight: 23–46 s with pictures in the backlog.

- CPU speed: matmul runs at 0.9 TFLOP/s in fp32 here, so the slowness is elsewhere in the model's CPU path. Not looked into further.
- The vision token budget is the default (280 tokens an image, 140 a video frame); the card allows 70–1120.
