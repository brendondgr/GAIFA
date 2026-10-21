<!-- aihub-setup
id = "vllm"
title = "vLLM"
models = []
scan = ["profiles/*.toml"]
summary = "vLLM: serve Hugging Face chat models (safetensors, AWQ) on the GPU, published to the relay"
gpu = true
disk_gb = 0.1
images = { "docker.io/kyuz0/vllm-therock-gfx1151" = 12.4 }
needs = ["uv", "podman"]
after = ["relay"]
check = "aihub check vllm --start"

[[steps]]
run = "aihub install vllm"
what = "makes the adapter's .venv/ and pulls the pinned kyuz0/vllm-therock-gfx1151 image (12.4 GB on disk, from Docker Hub)"

[[suggest]]
name = "Qwen3 0.6B (the smoke-test profile)"
op = "POST /v1/downloads"
body = { profile = "qwen3-0.6b" }
size_gb = 1.52
good_for = "proving vLLM runs on your GPU in about 2 minutes"
licence = "Apache-2.0"

[[suggest]]
name = "Qwen3.6 35B-A3B, AWQ 4-bit"
op = "POST /v1/downloads"
body = { profile = "qwen3.6-35b-a3b-awq" }
size_gb = 25.0
good_for = "a capable agent model with tool calls and thinking, about 3B active"
licence = "Apache-2.0"
-->

# vLLM: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `vllm` mod serves Hugging Face models (safetensors, AWQ) with vLLM and publishes the running one to the [relay](../../relay/setup/relay.md). Upstream vLLM doesn't support `gfx1151`, so vLLM runs in kyuz0's patched image, [`kyuz0/vllm-therock-gfx1151`](https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes), pinned by digest. Two environments:
- **The adapter**, `.venv/` in this folder (port 5101; FastAPI, httpx, tomlkit, huggingface_hub). It downloads models, asks AIHub for memory, and starts and stops one engine container at a time. It never touches the GPU itself.
- **The engine**, `vllm serve` in a podman container `aihub-vllm-<profile>` from the pinned image, on `127.0.0.1:7801` (host network, nothing published), with `/dev/kfd` and `/dev/dri`.

GGUF models go to [llama.cpp](../../lcpp/setup/llama-cpp.md) instead.

**Parked on the machine these docs were written on** (since 2026-10-20: its models were deleted to free disk). That's local: `config.toml` has `[services.vllm] autostart = false`, and `profiles/.parked.json` (gitignored) lists the profiles the adapter skips there. A fresh clone gets every profile. See "Parking a profile" below.

## Tested with

Read from this machine on 2026-10-21:

| Part | Version |
|---|---|
| Engine image | `docker.io/kyuz0/vllm-therock-gfx1151@sha256:8002236ea7526491cf9b0b6a543408fb0be2baacbba656effc132aba2e44dd1d`, image id `1c9dd1fedc13`, created 2026-10-04, 12.4 GB on disk |
| Inside it (image labels) | `rocm10.0.0-torch2.11.0-vllm0.31.0`; source revision `61fad8eb8449f5deda445043c1bd4eb92735eff1` of kyuz0/amd-strix-halo-vllm-toolboxes |
| The adapter | Python 3.12.13 (uv-managed), fastapi 0.143.2, uvicorn 0.54.0, httpx 0.28.1 |
| GTT | `mem_info_gtt_total` = 130,446,364,672 bytes (121.5 GiB) |

Recorded engine runs: the 0.6B smoke test (2026-10-15: healthy after 130 s cold, 134 tok/s single stream) and the AWQ profile's process overhead (6.4 GB, in `vllm_mod/settings.py`). Plan 18.7's live check is still open, so the AWQ's `memory_gb = 40` is the seed value, not a measurement. Nothing was started on the GPU for this doc.

## Prerequisites

- [host.md](../../../docs/setup/host.md): the kernel parameters (vLLM sizes itself from the GTT), the `video` and `render` groups, podman, the IOMMU **on**.
- The [relay](../../relay/setup/relay.md).
- Disk: the image (12.4 GB) plus each profile's model in `data/models/hf-cache/` (the AWQ repo is 25.0 GB; the 0.6B is 1.5 GB) plus compile caches.
- Gated repos need a Hugging Face token (host.md §6); the two seed profiles' repos aren't gated.

## Install

```bash
aihub install vllm
```

Runs `install.sh`: makes `.venv/` (Python 3.12) from `requirements-dev.txt`, then `podman pull`s the image named in `service.toml` (`VLLM_IMAGE`) if podman doesn't have it, from Docker Hub.

### Parking a profile

A profile is `profiles/<id>.toml` (the keys are in [README.md → Profiles](../README.md#profiles)). The seeds are `qwen3-0.6b` (`Qwen/Qwen3-0.6B`, the smoke test, `memory_gb = 12`) and `qwen3.6-35b-a3b-awq` (`cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit`, `memory_gb = 40`). To keep a profile out of the list on your machine (loading it would download its model), name it in `profiles/.parked.json`, a JSON list of ids that git ignores:

```bash
echo '["qwen3.6-35b-a3b-awq"]' > services/vllm/profiles/.parked.json
```

Remove an id (or the file) to bring a profile back. Then set `autostart = true` under `[services.vllm]` in `config.toml` (or leave it off and start by hand), `aihub start vllm`, and load the profile from the vLLM page. **The first load downloads its model** into `data/models/hf-cache/` (`HF_HOME`) before it asks for memory, registers it as `<repo> (vLLM)`, then starts the engine. The engine itself runs with `HF_HUB_OFFLINE=1`.

**The first start compiles.** The smoke test took 130 s cold (torch.compile 16 s); a hybrid model like Qwen3.6 also autotunes Triton kernels during its first start. The adapter waits up to 1200 s. The compile and tuning caches persist in `data/state/vllm/cache/` (`triton`, `inductor`, `vllm`, `xdg`), so later starts are faster.

## Choosing models

vLLM runs **Hugging Face repos** in a format the pinned image supports (safetensors in BF16, AWQ; not GGUF). Each model is a **profile**: `profiles/<id>.toml`, written by hand or with the page's profile form (`PUT /v1/profiles/<id>`), naming the repo, its alias on the relay and its memory budget. `POST /v1/downloads {"profile": "<id>"}` (the page's Download button) fetches its repo into `data/models/hf-cache/` without loading it; a load downloads first if needed. Gated repos need a Hugging Face token.

The two seed profiles are the suggestions, both optional. Sizes from Hugging Face, 2026-10-21:

| Profile | Repo | Size | Good for | Licence |
|---|---|---|---|---|
| `qwen3-0.6b` | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | 1.5 GB | the smoke test: proves the engine runs (`memory_gb = 12`) | Apache-2.0 |
| `qwen3.6-35b-a3b-awq` | [cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit](https://huggingface.co/cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit) | 25.0 GB | an agent model with tool calls and thinking, about 3B active (`memory_gb = 40`, not yet measured) | Apache-2.0 |

## Configuration

`service.toml` `[run.env]`:

| Key | Required | Meaning |
|---|---|---|
| `VLLM_IMAGE` | yes (set) | the pinned image, by digest (`:latest` moves) |
| `VLLM_ENGINE_PORT` | yes (set) | `7801` |
| `VLLM_STATE_DIR` | yes (set) | `data/state/vllm`: `downloads.json`, `last.json`, the caches |
| `HF_HOME` | yes (set) | `{hf_home}` = `data/models/hf-cache` |
| `VLLM_PROFILES_DIR`, `VLLM_RELAY_URL`, `VLLM_PODMAN` | optional | `profiles/`, `http://127.0.0.1:4000`, `podman` |
| `VLLM_START_TIMEOUT_S`, `VLLM_OVERHEAD_GB` | optional | 1200 s; 6 GB asked for beyond the profile's budget (measured 4.2 GB for the 0.6B, 6.4 GB for the 35B-A3B) |

**Memory.** A profile's `memory_gb` is vLLM's whole budget (weights, KV cache, CUDA graphs). The adapter passes `--gpu-memory-utilization` = `memory_gb` × 10⁹ / `mem_info_gtt_total`: 40 GB → 0.3066 here. It refuses more than 0.95. Each load first acquires `memory_gb` + the overhead from AIHub. `[memory] idle_unload_s = 0`: unload by hand.

**`engine_site/`** (mounted read-only, on the engine's `PYTHONPATH`): `sitecustomize.py` works around broken GPU event timing in the pinned image, which made Triton's autotuner run hundreds of thousands of repetitions per config. When events disagree with the wall clock by more than 5×, `triton.testing.do_bench` uses the wall clock and caps repetitions. `VLLM_MOD_TRITON_BENCH=wall|off` (in a profile's `env`) forces it. With `TRITON_CACHE_AUTOTUNING=1`, a model tunes once. Details: [README.md](../README.md#triton-autotuning-on-gfx1151-engine_site).

## Check it works

```bash
podman image exists docker.io/kyuz0/vllm-therock-gfx1151@sha256:8002236ea7526491cf9b0b6a543408fb0be2baacbba656effc132aba2e44dd1d && echo present
```

Expect `present`.

```bash
aihub check vllm
```

Parked, expect `vllm: no failures, but 5 checks skipped` (it's stopped). With a profile back and the mod started, `aihub check vllm` runs the live checks too.

```bash
cd services/vllm && .venv/bin/python -m pytest -q
```

A fake engine process instead of the container, no GPU: expect `29 passed` (2026-10-21).

## What to look for

- **Use the stock, pinned image.** Don't replace it with `:latest` or a custom build, don't add custom kernels, and keep the IOMMU on ([host.md, the IOMMU warning](../../../docs/setup/host.md#1-let-the-gpu-use-the-memory)). On 2026-10-19/20 experimental GPU compute on this machine wrote into memory the kernel used for file cache and corrupted files. `engine_site/` only changes how Triton times its benchmarks; it adds no kernels.
- **The first start looks hung.** Compiling and autotuning take minutes; the page shows the stage. A first start that is still autotuning after 20 minutes is what happened before `engine_site/`; check that it's mounted (`aihub logs vllm`, the engine command on the page's Engine tab).
- **A load fails before asking for memory.** The download failed (disk, network, a gated repo without a token).
- **`--gpu-memory-utilization` too small.** If `mem_info_gtt_total` is about half your memory, the kernel parameters didn't apply, and every profile's fraction doubles.
- AWQ needs `enforce_eager = true` on gfx1151 (the AWQ profile's comment, from kyuz0's `models.py`).

## Known gaps

- Parked: no engine start was checked for this doc. Bringing a profile back means a fresh download (25.0 GB for the AWQ one) and a cold compile.
- When a profile's model is downloaded again, it's registered at `hf-cache/hub/models--<org>--<name>`; add that exact folder to this doc's `models` (not `hf-cache/**`, which would claim Kokoro's and Whisper's).
- `install.sh` says the pull is "about 3.3 GB"; the image is 12.4 GB on disk.
