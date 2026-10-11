# Plan: Qwen-Image 2.1 Turbo workflow packs (comfy)

Qwen released [Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) (2026-10): the same 7B model as Qwen-Image 2.1, distilled to **8 steps at CFG 1** with a fixed sampling schedule saved in the checkpoint (`sample_sigmas` in `model_index.json`). This plan adds three Turbo packs to the `comfy` mod that mirror the base packs (`qwen21-t2i`, `qwen21-edit-multi`, `qwen21-remove-bg`). They use the same loaders, the same lazy Q8_0/FP8 switch, the same text encoder and VAE, the same prefix KV cache, inputs and outputs, so the agent's task tools and the Run form treat them like the base packs.

It touches the comfy mod only (architecture §11, plan Phase 11; pack format in [workflows.md](../workflows.md)). No hub code changes.

## Gaps & answers

- **Which weights?** *Answered by the user (2026-10-09):* the official Turbo only, in quantized form, with no Turbo LoRAs. They come from `abenzerps/Qwen-Image-2.1-Turbo-Quantized`, the same author and converter as the base packs' `UC` files: `qwen-image-2.1-turbo-Q8_0.gguf` (7.59 GB) and `qwen-image-2.1-turbo-fp8.safetensors` (7.13 GB). These are the official Turbo weights, not an uncensored ("UC") build.
- **Text encoder and VAE.** *Assumption:* reuse `qwen3vl_8b_bf16.safetensors` and `qwen_image_2.1_vae_bf16.safetensors`. The Turbo repo's copies are byte-identical (same sizes; the base download script already notes the identical hashes).
- **Sampling.** A KSampler scheduler can't reproduce Turbo's schedule. *Approach:* `ManualSigmas` with the checkpoint's 8 sigmas plus a final 0 (`1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0`), passed through `RandomNoise`, `CFGGuider` (cfg 1), `KSamplerSelect` (euler) and `SamplerCustomAdvanced`. Every node is core or already installed (checked against `data/object_info.json`).
- **The `steps` input.** The schedule fixes the step count, so the Turbo packs don't expose `steps`. `cfg` stays exposed (default 1), as in the base packs.
- **Task defaults (★).** *Assumption:* left as they are. The defaults are the user's per-task choice (`PUT /v1/defaults`), and the agent can still pick the Turbo packs by name.
- **`~/Models`.** Not a git repo, and ComfyUI no longer runs from it (`MOVED.md`). The editor files and the builder are kept there with the base model's, as before. AIHub is the only place where commits happen.

## Steps

- [x] **T.1 Models: `services/comfy/scripts/download_qwen_image_2.1_turbo.sh`.**
  - **Script:** the same resumable pattern as `download_qwen_image_2.1.sh`, plus a sha256 check against the repo's `SHA256SUMS` before each rename. It writes to `data/models/comfyui/diffusion_models/`.
  - **Registry:** `aihub models scan --add` registers both files. Set their `source` to `abenzerps/Qwen-Image-2.1-Turbo-Quantized@main` (`huggingface`), then run `aihub models verify` on both.
  *Done when:* both files are on disk with matching sha256, and `aihub models show` lists them with their source, verified.
  - *As built:* the upstream FP8 export can't run as published (ComfyUI runs it unscaled: noise; see [comfy-transfer-report.md](../comfy-transfer-report.md), Running them). `scripts/fix_fp8_quant_metadata.py` adds ComfyUI's per-layer FP8 metadata (header only, tensor data byte-identical), and the download script applies it. The registry records the fixed file's sha256 and notes the upstream one.

- [x] **T.2 Builder: `~/Models/ComfyUI-next/workflows/qwen-image-2.1/build_turbo_workflows.py`.**
  - It reuses `Graph`, `T` and `note` from `build_workflows.py` next to it, with Turbo loaders (`Diffusion · Turbo Q8_0 GGUF (default)` / `Diffusion · Turbo FP8 (alternative)` behind the same yellow switch). The sampler group becomes `ManualSigmas → RandomNoise / CFGGuider / KSamplerSelect → SamplerCustomAdvanced`. The prefix KV cache (`QwenImage21Cache`) goes in all three graphs, as the official templates have it. Save prefixes are `Qwen21Turbo/{t2i,edit,remove_bg}`.
  - **Output:** editor files in `~/Models/ComfyUI-next/workflows/user-original/Qwen-Image-2.1-Turbo/` and API graphs in `qwen-image-2.1/api/` (`01_qwen21-turbo_text-to-image`, `02_qwen21-turbo_image-edit_multi-reference`, `03_qwen21-turbo_remove-background`).
  *Done when:* the script writes six files, and each API graph is accepted by ComfyUI's `/prompt` validation (T.4).
  - *As built:* `ImageCompare` is part of the API graph, as ComfyUI's editor writes it (`compare_view`), so the builder's graphs equal AIHub's conversion.

- [x] **T.3 Packs: `services/comfy/workflows/qwen21-turbo-{t2i,edit-multi,remove-bg}/`.**
  - `comfyui workflows new <id> --from <editor file>`, then `suggest --write`. Hand-edit `workflow.toml` to match the base packs: the same names and tasks (`text-to-image`, `image-edit`, `remove-background`), `prompt`, `seed` (→ `RandomNoise.noise_seed`, default -1), `cfg` (→ `CFGGuider.cfg`), `aspect`/`megapixels` (t2i), `image`/`image_2` (edit), `image` (remove-bg), and `outputs.image`. Add a `description` that tells the agent what Turbo is for.
  - **Agent guide:** `services/comfy/skills/choosing-a-workflow/SKILL.md` lists the Turbo packs: Turbo for quick text-in-image and edits, the base packs when quality matters more than time.
  *Done when:* `comfyui workflows check --all` reports the three packs `ready`, and `GET /api/s/comfy/v1/tools` offers them under `generate_image`, `edit_image` and `remove_background`.

- [x] **T.4 Live runs (loads models; the user asked for a working pipeline).**
  - `POST /api/s/comfy/v1/run` once per pack with the Q8_0 default, then `GET /v1/jobs/<id>?wait=900`. For the edit, use two AIHub outputs as `image`/`image_2`. For remove-bg, use any photo output, and check that the PNG has an alpha channel.
  - Run t2i once on the FP8 side: queue its API graph straight to ComfyUI with `~/Models/ComfyUI-next/workflows/qwen-image-2.1/run_api.py api/01_qwen21-turbo_text-to-image.api.json 3.switch=true` (the pack itself keeps Q8_0).
  - Ground truth: load each editor file in ComfyUI's own frontend and export the API graph. It must equal `tests/fixtures/holdout/qwen21-turbo-*.api.json` (as plan 11.12 did for the base files).
  *Done when:* each run finishes with an image in `outputs/comfy/<date>/`. Record times and peaks next to the base packs' in [comfy-transfer-report.md](../comfy-transfer-report.md) (§ "Runs").
  - *As built:* t2i 59 s cold / 42 s warm (base 236 s), edit 204 s (base 608 s), remove-bg 118 s (base 367 s); FP8 t2i 42 s after the fix. ComfyUI's editor (0.37.0, in the browser) exports exactly the three fixture graphs.

- [x] **T.5 Tests and docs.**
  - `services/comfy/tests/`: the existing suites stay green. Add a pack test (`test_packs.py`) asserting the three Turbo manifests load, map the task's required inputs, and carry no `steps` input.
  - Docs: `docs/structure.md` (the new script, this plan, the three packs) and `services/comfy/README.md` if it lists packs.
  *Done when:* `uv run pytest` (hub) and `services/comfy/.venv/bin/python -m pytest` (mod) pass.
  - *As built:* the Turbo workflows joined the held-out set in `test_holdout.py` (fixtures in `tests/fixtures/holdout/`, `ManualSigmas` added to the fixture node list); `test_packs.py::test_qwen21_turbo_packs`; `test_fix_fp8.py` for the fixer.

- [x] **T.6 Speed-ups for edit and remove-bg: `services/comfy/nodes/aihub_nodes/` (asked for 2026-10-09).**
  - **Measure:** per-node timings over ComfyUI's websocket, for base → Turbo → each fix, with the same inputs and seed.
  - **Fixes (the image doesn't change):** the Qwen-VL vision patch-embed as a matmul instead of ROCm's slow Conv3d (global, applied when ComfyUI loads the package); `AIHubTextEncodeQwenImage21`, which encodes once (the negative is unused at cfg 1; `encode_negative` turns it back on); `VAELoaderKJ` at bf16 in the two packs (ComfyUI keeps `--fp32-vae` for FLUX.2). `extra_model_paths.yaml` lists `nodes/` after `custom_nodes/`.
  - **Trade-off, opt-in:** a `resolution` input and `[presets.fast]` (768) on both packs.
  *Done when:* the packs check `ready`, ComfyUI's editor exports exactly the new fixture graphs, and the tables are in [comfy-transfer-report.md](../comfy-transfer-report.md) ("Speed-ups").
  - *As built:* edit 191–220 s → 110 s (fast 40 s), remove-bg 118 s → 62 s (fast 29 s), text to image 49 s → 39 s (encode once + bf16 VAE; asked for afterwards); the base packs got the matmul fix too (edit 531 → 429 s, remove-bg 367 → 270 s).

- [x] **T.7 Turbo only for the agent; megapixels on every Turbo pack (asked for 2026-10-11).**
  - **Agent:** a manifest key `agent = false` keeps a pack off the agent's task tools, `list_workflows` and `run_workflow`; the page and API still run it. The three base packs set it, so the agent always gets Turbo; their weights stay on disk.
  - **Megapixels:** text to image already maps `megapixels` (ResolutionSelector). For edit and remove-bg, `megapixels` is a derived input that sets the encoder's square working size: 1024·√MP in multiples of 32 (1.0 MP = 1024×1024, as the ResolutionSelector counts). The `fast`/`draft` presets become `megapixels = 0.56` / `0.32`, the same 768 / 576 working sizes as measured.
  - **Agent guide:** `choosing-a-workflow` drops the base packs and says when to lower `megapixels` (prototyping) or leave it out (final).
  *Done when:* the base packs check `ready` on the page with `agent: false`, `GET /v1/tools` offers only Turbo for Qwen with `megapixels` on all three tools, and a live remove-bg at 0.25 MP returns a 512×512 RGBA image.
  - *As built:* `comfy/packs.py`, `tools.py`, `api_run.py`, `library.py` (`agent` in the workflow list), `schema.py` and `resolve.py`; tests in `test_tools.py`, `test_run.py`, `test_packs.py`. Live: remove-bg on the vase at 0.25 MP, 512×512 RGBA in 32.7 s (cold).

Commits: one per step once its tests pass, `AIHub (comfy, Qwen 2.1 Turbo T.k): <sentence>`.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Download script | Resumable, sha256-checked pull of Turbo Q8_0 + FP8 | `services/comfy/scripts/download_qwen_image_2.1_turbo.sh` |
| Registry entries | `qwen-image-2.1-turbo-q8-0`, `qwen-image-2.1-turbo-fp8` | `data/models/registry.json` |
| Builder | Editor + API graphs for the three Turbo workflows | `~/Models/ComfyUI-next/workflows/qwen-image-2.1/build_turbo_workflows.py` |
| Packs | Text to image, edit with references, remove background | `services/comfy/workflows/qwen21-turbo-*/` |
| AIHub nodes | Patch-embed matmul fix, `AIHubTextEncodeQwenImage21` | `services/comfy/nodes/aihub_nodes/` |
| Agent guide | Turbo for Qwen; when to lower `megapixels` | `services/comfy/skills/choosing-a-workflow/SKILL.md` |
| Tests | Turbo manifests load and map their task's inputs | `services/comfy/tests/test_packs.py` |
