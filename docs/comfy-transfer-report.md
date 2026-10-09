# ComfyUI workflow transfer test (plan 11.12)

**The question:** how easily does a workflow that wasn't used to build the comfy mod become a working pack? Thirteen workflows were held out while the converter, checker and input detector were built (plan 11.5–11.6). Then they were imported with the code frozen, scored, the problems fixed, and scored again.

## Method

1. **Freeze:** git tag `comfy-transfer-freeze` (commit `8583c6e`, after 11.11).
2. **Import** each workflow as a user would.
   - Your own and the official ones: from their files.
   - The Civitai ones: from their downloaded zips where they came as zips.
   - The CLI failed on the first try (finding I1 below), so the imports went through the page's API (`POST /v1/import`).
3. **Ground truth:** each editor file loaded in ComfyUI's own editor in the browser, with `app.graphToPrompt()` giving the API graph ComfyUI itself would queue. Nothing was run.
4. **Expectations, written before the detector ran on each workflow** (`services/comfy/tests/fixtures/holdout-expected/`):
   - **want:** what a person would expose
   - **maybe:** fine either way
   - **missed:** a person would want it, and no rule could find it
5. **Score** (`services/comfy/tests/transfer.py`):
   - **Converts:** our API graph against ComfyUI's, ignoring `filename_prefix` (the editor date-fills it).
   - **Missing pieces right:** the missing node types and model files `check` reports, against an independent count (live, connected node types not in ComfyUI's node list; file names not in any loader's list).
   - **Inputs right / wrong / missed / extra:** the detector's suggestion against the expectations.
   - **Task and outputs** against the expectations.
6. **Fix** in separate commits, then score again with the same script against both versions of the code. The "before" table is the frozen code run through today's scoring script, so the two tables compare like with like.

**Caveat:** the node types of Qwen-Image-2.1 were seen once while the plan was written, so tier 1 isn't entirely blind.

## The held-out set

| Tier | Workflows | Source |
|---|---|---|
| 1: same style, new model | `qwen21-t2i`, `qwen21-edit-multi`, `qwen21-remove-bg` | yours |
| 2: official templates with subgraphs | `klein9b-t2i`, `klein9b-edit-base`, `klein9b-edit-distilled` | ComfyUI templates |
| 3: community, custom nodes, video | `scail2-basic`, `scail2-gguf`, `zimg-v7-basic` | community / Civitai |
| 4: stress | `zimage-aio` (124 nodes, 5 subgraphs), `lonecat-krea2-pro` (474 nodes, LUT files, zip), `krea2-simple`, `krea2-dualmode` | Civitai |

## Before (the frozen code)

| Workflow | Tier | Converts | Missing pieces right | Inputs right / wrong / missed / extra | Task | Outputs |
|---|---|---|---|---|---|---|
| qwen21-t2i | 1 | exact | yes | 2 / 0 / 2 / 0 | ok | ok |
| qwen21-edit-multi | 1 | 1 difference | yes | 4 / 0 / 0 / 0 | ok | ok |
| qwen21-remove-bg | 1 | 1 difference | yes | 1 / 0 / 0 / 0 | wrong | ok |
| klein9b-t2i | 2 | exact | yes | 2 / 0 / 2 / 0 | ok | ok |
| klein9b-edit-base | 2 | 2 differences | yes | 3 / 0 / 0 / 0 | ok | ok |
| klein9b-edit-distilled | 2 | 2 differences | yes | 3 / 0 / 0 / 1 | ok | ok |
| scail2-basic | 3 | 4 differences | yes | 4 / 0 / 1 / 0 | ok | ok |
| scail2-gguf | 3 | 9 differences | yes | 4 / 2 / 1 / 0 | ok | wrong |
| zimg-v7-basic | 3 | 2 differences | yes | 1 / 0 / 3 / 2 | ok | ok |
| zimage-aio | 4 | 30 differences | no | 0 / 0 / 0 / 1 | wrong | — |
| lonecat-krea2-pro | 4 | **failed** | no | — | — | — |
| krea2-simple | 4 | 6 differences | yes | 2 / 0 / 0 / 3 | ok | ok |
| krea2-dualmode | 4 | exact | yes | 1 / 1 / 0 / 2 | wrong | ok |

## After the fixes

| Workflow | Tier | Converts | Missing pieces right | Inputs right / wrong / missed / extra | Task | Outputs |
|---|---|---|---|---|---|---|
| qwen21-t2i | 1 | exact | yes | 4 / 0 / 0 / 0 | ok | ok |
| qwen21-edit-multi | 1 | exact | yes | 4 / 0 / 0 / 0 | ok | ok |
| qwen21-remove-bg | 1 | exact | yes | 1 / 0 / 0 / 0 | ok | ok |
| klein9b-t2i | 2 | exact | yes | 4 / 0 / 0 / 0 | ok | ok |
| klein9b-edit-base | 2 | exact | yes | 3 / 0 / 0 / 0 | ok | ok |
| klein9b-edit-distilled | 2 | exact | yes | 3 / 0 / 0 / 0 | ok | ok |
| scail2-basic | 3 | exact | yes | 5 / 0 / 0 / 0 | ok | ok |
| scail2-gguf | 3 | 1 difference (display only) | yes | 5 / 0 / 0 / 0 | ok | ok |
| zimg-v7-basic | 3 | exact | yes | 1 / 0 / 3 / 0 | ok | ok |
| zimage-aio | 4 | 4 differences (display only, plus an unconnected uninstalled node) | yes | 0 / 0 / 0 / 1 | wrong | — |
| lonecat-krea2-pro | 4 | converts (ComfyUI's own editor can't) | yes | 0 / 0 / 0 / 5 | ok | — |
| krea2-simple | 4 | exact | yes | 2 / 0 / 0 / 3 | ok | ok |
| krea2-dualmode | 4 | exact | yes | 1 / 0 / 1 / 0 | ok | ok |

**Totals over tiers 1–3** (the nine expected to work):

| | Exact conversions | Missing pieces right | Inputs right | Wrong | Missed | Extra | Task right | Outputs right |
|---|---|---|---|---|---|---|---|---|
| Before | 2 / 9 | 9 / 9 | 24 | 2 | 9 | 3 | 8 / 9 | 8 / 9 |
| After | 8 / 9 | 9 / 9 | 30 | 0 | 3 | 0 | 9 / 9 | 9 / 9 |

**The three remaining misses** are on `zimg-v7-basic`: its prompt, width and height come from custom nodes that aren't installed (Impact Pack's wildcard processor, easy-use's `easy int`). Their fields can't be known until the nodes are installed. The check names those packages, and a note says where the prompt comes from.

**The one remaining difference** (`scail2-gguf`) is a display-only value on rgthree's "Display Int" node.

**Tier 4** passes its bar: every workflow converts or names what it can't handle. The extras are on Lonecat, whose save nodes are uninstalled custom nodes (outputs not judged), and on `krea2-simple`, where on inspection the detector was right and my expectation was wrong: the size it found (node 232) is the latent that's wired in, and the other 20 empty latents are disconnected presets.

## What the held-out workflows found, and the fixes

**Converter** (commit `189faed`)

| Found on | Problem | Fix |
|---|---|---|
| Klein edit (official templates) | Subgraph inputs were matched by position. The subgraph node lists only the inputs it exposes, so the **image was wired into the CLIP loader** | Match by name; with no outside socket, the inner widget's value stands |
| Z-Image All-in-One | ComfyUI's editor renumbers subgraph nodes whose ids collide with others when it loads a file, so node ids differed from ComfyUI's | Renumber the same way (after `last_node_id`, in definition order) |
| Lonecat Krea 2 Pro | Node ids like `"2682:0"` crashed the converter | Ids are strings throughout |
| Z-Image All-in-One | A bypassed node with no input of the output's type passes the input at the same slot (ComfyUI's rule) | Same fallback |
| Z-Image All-in-One | Bypassed subgraphs were dropped instead of passed through | Pass through |
| SCAIL 2 | VideoHelperSuite's per-format settings (`crf`, `pix_fmt`) were dropped | Keep every scalar saved by name |
| Krea 2 Simple | rgthree's Power Lora Loader values were dropped, so **its LoRAs wouldn't apply** | Its layout is understood |
| several | rgthree's editor-only helpers (group bypassers, bookmarks) counted as missing nodes | Known as editor-only |
| Lonecat Krea 2 Pro | "Anything Everywhere" makes links only the editor knows | Named as the problem `editor_links`, with how to fix it |

**Input detection** (commit `53342b3`)

| Found on | Problem | Fix |
|---|---|---|
| Z-Image V7, Krea2 Dual Mode | A prompt was mapped to a linked field, or to a text processor's pattern (`RegexReplace.regex_pattern`) | Never map a linked field; follow text processors upstream; note prompts that come from uninstalled nodes |
| Qwen-Image-2.1, Klein, SCAIL 2 gguf | Size wasn't found through primitive ints or a resolution picker, and an image resize was taken for the size | Trace the sampler's latent input: primitives, resolution pickers, img2img resizes, the sampler using a guider; no size when a switch chooses |
| Klein edit distilled | An image loader that feeds only a bypassed branch became an input | Skipped |
| Krea2 Dual Mode | An image that's only described by a captioner made it an edit workflow | That image is optional, and the task stays text-to-image |
| Qwen-Image-2.1 remove background | Labelled image-edit | `remove-background` from the prompt's words |
| SCAIL 2 gguf, Z-Image All-in-One | VideoHelperSuite previews and image comparers counted as outputs | Not outputs |
| SCAIL 2 | The driving video wasn't an input | New shared input `video` (a file, like `image`) |
| Qwen-Image-2.1 | A pack mapping `aspect` to a real field had it swallowed by the derived-aspect logic | A mapped `aspect`/`megapixels` is passed as it is |

**Importing** (commit `f120d4d`)

| Problem | Fix |
|---|---|
| I1: `comfyui workflows` changed folder, so relative paths failed | It stays in your folder |
| I2: `comfyui workflows new` only read JSON, though the guide said it takes PNGs and zips | It uses the page's importer |
| I3: a zip with four workflow variants (Z-Image Turbo V7) imported one of them, silently | One draft each (`zimg-v7-1` … `-4`) |

## Running them

| Workflow | Runs? | Notes |
|---|---|---|
| qwen21-t2i | **yes**: 236 s, peak 40.6 GB | A 3:2 photo through its resolution picker (1248×832) |
| qwen21-edit-multi | **yes**: 608 s, peak 43.0 GB | Two AIHub outputs as `image` and `image_2` (`output:<id>`): the fox from one placed in front of the cabin from the other |
| qwen21-remove-bg | **yes**: 367 s, peak 43.1 GB | The fox cut out, with real transparency |
| qwen21-turbo-t2i (2026-10-09) | **yes**: 59 s cold, 42 s warm, peak 40.3 GB | The same 3:2 size (1248×832); a storefront with two signs of text, both spelled right. The FP8 side of the switch too (42 s), once its file was fixed (below) |
| qwen21-turbo-edit-multi (2026-10-09) | **yes**: 204 s, peak 54.6 GB | An AIHub output as `image` and a result path as `image_2`: the cat from one placed at the shop door of the other, signs and light unchanged. The higher peak is the prefix KV cache using spare memory (`auto`) |
| qwen21-turbo-remove-bg (2026-10-09) | **yes**: 118 s, peak 38.8 GB | The cat cut out (68% fully transparent, soft fur edges) |
| klein9b-* (3) | no: 3 model files missing each | The official templates record their download URLs, so the review screen offers Download buttons. Downloading needs your go-ahead |
| scail2-basic | no: 2 model files missing | `wan2.1_14B_SCAIL_2_fp8_scaled.safetensors`, and the LightX2V LoRA under a `Wan2.1/` subfolder (you have it without the subfolder: one `[set]` line) |
| scail2-gguf | no: custom node `KikoPurgeVRAM` | Its models are all here; install that node (ComfyUI-Manager) and it should run |
| zimg-v7-basic | no: Impact Pack, easy-use, Image Saver nodes | Named by the check |
| tier 4 | not run | Judged on conversion. Two of them also carry prompts that name a real person in sexual content, which I won't run |

**Turbo FP8 file (2026-10-09).** `abenzerps/Qwen-Image-2.1-Turbo-Quantized`'s `turbo-fp8` mixes two formats: the legacy `scaled_fp8` marker with the new `.weight_scale` names and no per-layer metadata. ComfyUI 0.37's `convert_old_quants` only maps the legacy `.scale_weight` names, so it ran the FP8 values unscaled and the image was noise. FP8 × scale matches the Q8_0 GGUF to 2.7% on sampled layers, so the weights are fine. `services/comfy/scripts/fix_fp8_quant_metadata.py` adds the metadata ComfyUI's own exports carry (header only), and `download_qwen_image_2.1_turbo.sh` applies it.

## Speed-ups: Qwen-Image 2.1 edit and remove background (2026-10-09)

The Turbo edit took 200 s for 8 steps, and the sampler was only 80 s of it. Per-node timings (ComfyUI's websocket `executing` events, one run each, the same inputs and seed, a unique prompt per run so no node is cached) found three costs that don't change the image:

- **The text encoder read the references twice.** `TextEncodeQwenImage21` runs the prompt and every reference image through Qwen3-VL for the positive, then again for the negative. At cfg 1 the sampler never uses the negative. `AIHubTextEncodeQwenImage21` (`services/comfy/nodes/`, [workflows.md §9](workflows.md#9-aihubs-own-nodes)) encodes once.
- **The vision patch-embed is a Conv3d that ROCm runs very slowly.** Its kernel equals its stride, so it is one matmul. It took 17.5 s of a 33 s encode of one 1024² image, and as a matmul the encode takes 14.5 s, with the output equal to 1e-5. The patch applies to every Qwen-VL text encoder, so the base packs get it too.
- **The VAE ran in fp32.** ComfyUI starts with `--fp32-vae` for FLUX.2's small decoder. The Turbo edit and remove-bg packs load the Qwen VAE (a bf16 file) in bf16 through `VAELoaderKJ`. Decode went from 12 s to 2 s.

Edit (two references at 1024², a 1248×832 result):

| Stage | Text encode | Sampling | Decode | Total |
|---|---|---|---|---|
| Base `qwen21-edit-multi` (40 steps) | 94 s | 417 s | 13 s | **531 s** |
| Base, with the matmul fix (automatic) | 42 s | 373 s | 12 s | **429 s** |
| Turbo as it was | 91–117 s | 81–90 s | 12 s | **191–220 s** |
| + matmul patch-embed | 42 s | 87 s | 12 s | **147 s** |
| + encode once | 24 s | 84 s | 12 s | **120 s** |
| + bf16 VAE (the pack now) | 20 s | 85 s | 2 s | **110 s** |
| + `fast` preset (768: a 928×640 result) | 11 s | 28 s | 1 s | **40 s** |

Remove background (a 1024² photo, kept at its size):

| Stage | Text encode | Sampling | Decode | Total |
|---|---|---|---|---|
| Base `qwen21-remove-bg` (40 steps; the 2026-10-07 run, today's stalled) | — | — | — | **367 s** |
| Base, with the matmul fix (automatic) | 21 s | 236 s | 13 s | **270 s** |
| Turbo as it was | ~50 s | 42 s | 18 s | **118 s** |
| + matmul patch-embed | 21 s | 49 s | 13 s | **83 s** |
| + encode once | 12 s | 59 s | 13 s | **85 s** |
| + bf16 VAE (the pack now) | 10 s | 48 s | 2 s | **62 s** |
| + `fast` preset (768) | 5 s | 23 s | 1 s | **29 s** |

- **Sampling varies about ±10 s between identical runs.** That's why "encode once" saves 9 s in the text encoder but shows nothing in the remove-bg total.
- **The image doesn't change** from the first three fixes. Against the previous stage at the same seed: encode once differs by 0.38/255 on average (GPU run-to-run noise), and the bf16 VAE by 1.0/255 (1.7% of pixels by more than 8/255).
- **The `fast` preset changes the result.** It reads the inputs and makes the result at 768² (~0.6 MP), so it's smaller and keeps less fine detail. Sampling falls to a third because attention grows faster than the token count. It's a preset on the Run form, and the default stays 1024. The agent's task tools take only shared inputs, so they don't offer it yet.
- **One base remove-bg run stalled** inside a GPU kernel (GPU 100% busy at 45 W, past 20 min, and `/interrupt` couldn't stop it). It ended only when ComfyUI restarted. It didn't recur in the later runs.

## Edits needed by hand

| Workflow | Lines of `workflow.toml` changed |
|---|---|
| qwen21-t2i, qwen21-edit-multi, qwen21-remove-bg | 1 each: the name (the files have no title note, so the name came from the id) |
| klein9b-* | 0 (saved as suggested; waiting on model downloads) |
| others | not saved: drafts until their custom nodes or models are installed |

## What's still a limit

- **Inputs on custom nodes that aren't installed.** Their fields aren't in ComfyUI's node list until they're installed. Install the package (the check names it), then review again.
- **A size chosen by a switch between several latents.** It isn't mapped; the note says which node chooses.
- **"Anything Everywhere".** Its links exist only in ComfyUI's editor. Run the workflow once and import it from history, or wire the inputs directly.
- **Display-only widgets on uninstalled nodes** (rgthree's comparer and number displays) aren't sent. They don't change a run.
- **Re-saving in ComfyUI keeps the renumbered ids,** which now match the ones packs use. A pack made before the renumbering fix would report `input_unmapped` after a re-save; `title =` mappings avoid that entirely.

## Regression tests

`services/comfy/tests/test_holdout.py`:
- **Your three Qwen-Image-2.1 workflows and the three official Klein templates** are fixtures with ComfyUI's own API graphs. They must convert exactly and detect with no wrong inputs.
- **The seven third-party workflows** are read from where they are on this machine and skipped when absent. They aren't committed, and their packs are kept out of git by `services/comfy/workflows/.gitignore`.
