# vLLM

An AIHub mod (plan Phase 18) that serves Hugging Face models with [vLLM](https://github.com/vllm-project/vllm) on this machine, a Ryzen AI Max+ 395 (Strix Halo, gfx1151). Upstream vLLM doesn't support gfx1151, so vLLM runs in kyuz0's patched image, [`kyuz0/vllm-therock-gfx1151`](https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes), pinned by digest in `service.toml` (`VLLM_IMAGE`). llama.cpp (the `lcpp` mod) stays the engine for GGUF files.

**Parking a profile** on one machine (its model deleted, so loading it would download it again): list its id in `profiles/.parked.json` (gitignored), and the adapter skips it. Setup: [setup/vllm.md](setup/vllm.md).

- **The adapter** (`vllm_mod/`, port 5101) is what AIHub runs. It starts one vLLM container at a time and stops it again.
- **The engine** is `vllm serve` in a container named `aihub-vllm-<profile>`, listening on `127.0.0.1:7801` (`VLLM_ENGINE_PORT`, host network, nothing published).

## Profiles

A profile is one model setup: `profiles/<id>.toml`. Unknown keys are errors.

| Key | Meaning |
| --- | --- |
| `name` | shown on the page |
| `model`, `revision` | the Hugging Face repo and the branch, tag or commit |
| `served_name`, `alias` | the id clients send, and the relay's alias |
| `memory_gb` | vLLM's whole budget (weights, KV cache, CUDA graphs); becomes `--gpu-memory-utilization` = `memory_gb` / the GPU's GTT size (121.5 GiB here) |
| `max_model_len`, `max_num_seqs` | context window and requests at once |
| `attention_backend` | `TRITON_ATTN` (default), `ROCM_ATTN`, `ROCM_AITER_UNIFIED_ATTN`, or empty for vLLM's choice |
| `enforce_eager`, `trust_remote_code` | vLLM's flags |
| `tool_parser`, `reasoning_parser` | native tool calls (`--enable-auto-tool-choice`) and thinking in `reasoning` |
| `env`, `extra_args` | anything else for the engine |

The seed profiles take their flags from kyuz0's `models.py` in the pinned image.

## Smoke test (2026-10-15)

`Qwen/Qwen3-0.6B` at 0.1 of the GPU (12.06 GiB: KV cache 10.81, weights 1.12, graphs 0.13), `--max-model-len 8192`: healthy after 130 s cold (torch.compile 16 s), 134 tok/s single stream, 13.8 GB of GTT in use.

## Triton autotuning on gfx1151 (`engine_site/`)

In the pinned image, GPU event timing is broken: events time a 256 MB cache flush at 0.005–0.009 ms, the wall clock at 2.4 ms or more. Triton's autotuner sizes its benchmark from that estimate (`rep / estimate_ms`), so it ran about 381,000 repetitions per candidate config, each with that flush. Hybrid models such as Qwen3.6 tune about 100 configs for their linear-attention kernels during vLLM's profiling run, and the first start hadn't finished after 20 minutes.

- **`engine_site/sitecustomize.py`** is on `PYTHONPATH` in the container (mounted read-only). When Triton is imported, it checks events against the wall clock. If events are off by more than 5×, `triton.testing.do_bench` times with the wall clock (synchronize + `perf_counter`) and caps the repetitions (20 warmup, 50 timed). `VLLM_MOD_TRITON_BENCH=wall|off` forces either way. It chain-loads the image's own `sitecustomize`.
- **`TRITON_CACHE_AUTOTUNING=1`** keeps the tuning results in the Triton cache (`data/state/vllm/cache/triton`), so a model tunes once. Without it, this Triton build tunes again at every start.

## Tests

```bash
.venv/bin/python -m pytest
```
