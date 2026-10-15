# vLLM

An AIHub mod (plan Phase 18) that serves Hugging Face models with [vLLM](https://github.com/vllm-project/vllm) on this machine, a Ryzen AI Max+ 395 (Strix Halo, gfx1151). Upstream vLLM doesn't support gfx1151, so vLLM runs in kyuz0's patched image, [`kyuz0/vllm-therock-gfx1151`](https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes), pinned by digest in `service.toml` (`VLLM_IMAGE`). llama.cpp (the `lcpp` mod) stays the engine for GGUF files.

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

## Tests

```bash
.venv/bin/python -m pytest
```
