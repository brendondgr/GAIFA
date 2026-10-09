# ComfyUI workflow packs

The `comfy` mod (Images & Video) runs ComfyUI workflows as **packs**: one folder per workflow in `services/comfy/workflows/<id>/`. Packs work like mods: adding a folder adds the workflow, editing its files changes it, and deleting the folder removes it. No restart is needed. Each pack can run from its page, from the API, and through the agent's task tools.

This page is the how-to. The design is in [architecture §11](architecture.md#11-later-pieces) and plan Phase 11.

## 1. What a pack is

```
services/comfy/workflows/<id>/
  workflow.json        the ComfyUI editor file (what ComfyUI saves; it opens in ComfyUI)
  workflow.api.json    optional: the exact API graph, used as given instead of converting workflow.json
  workflow.toml        optional: the manifest. Without it the pack is a draft.
  preview.webp         optional: the card picture (otherwise the newest result)
  assets/              optional: files the graph loads (LUTs, masks, reference images), copied into ComfyUI's input folder before a run
```

`<id>` is 2–48 characters: lowercase letters, digits and `-`, starting with a letter.

- **ComfyUI sees every pack** as `<id>.json` in its workflow browser. That entry is a symlink to the pack's `workflow.json`. Save it in ComfyUI and the adapter moves your saved version into the pack.
- **A workflow saved in ComfyUI under a new name** becomes a **draft**. It shows on the Workflows tab with a "Review" button.
- **Packs are tracked in git**, so tweaks have history.

## 2. Adding a workflow

| From | How |
|---|---|
| A file: an editor JSON or API JSON, a PNG/WebP/MP4/WebM ComfyUI made, or a Civitai zip | Images & Video → **Import** → drop the file. Or `comfyui workflows new <id> --from <file>`. |
| ComfyUI's editor | Save the workflow under a new name. It appears as a draft. |
| Something you ran in ComfyUI | Import → **From ComfyUI's history**. This takes the exact graph that ran, so it works even when the editor file won't convert. |
| Another pack | `comfyui workflows copy <id> <new-id>` |

Every import becomes a **draft**. It is checked against your installed nodes and models, and AIHub suggests its inputs. Review it on the page, or run `comfyui workflows suggest <id>`. Saving the review (or `--write`) writes `workflow.toml`, and the draft becomes a pack.

**From a zip:** each workflow JSON in it becomes its own draft (`<id>-1`, `<id>-2`, … when there are several, as Civitai packs often ship variants). The zip's other files (LUTs, example images) are kept in each pack's `assets/`. An editor file is preferred over an API graph; the API graph is kept as `workflow.api.json` only when the editor file is missing or doesn't convert.

**What isn't found by itself** (add it by hand in `workflow.toml`, or with "Expose another field" on the review screen):
- inputs on custom nodes that aren't installed: their fields can't be known until they are (the check names the package; a note says where the prompt comes from)
- a size chosen by a switch between several latents
- other settings a workflow author marks by hand (a mask box, a LoRA strength): any node field can be an input

## 3. `workflow.toml`

```toml
name = "Z-Image Turbo"
task = "text-to-image"               # from tasks.toml (§4); "custom" when none fits
description = "Fast photoreal text to image"   # the agent reads this
tags = ["photo", "fast"]
# memory_gb = 18                     # set only to override: each run measures its peak

[inputs.prompt]                      # a shared name (§4) when one fits
node = "67"                          # the node id, as `comfyui workflows show <id>` lists them
field = "text"                       # the node input it sets

[inputs.seed]
node = "70"
field = "seed"
default = -1                         # -1 = a random seed per run
also = ["26.seed"]                   # more "<node>.<field>" targets that get the same value

[inputs.lora_strength]               # any name works; shared names make packs interchangeable
title = "Watercolor LoRA"            # a node's title instead of its id (survives renumbering)
field = "strength_model"
label = "Watercolor strength"
min = 0
max = 1.5

[outputs.image]
node = "9"                           # a save node; kind is guessed (image, video, audio, mesh)

[presets.portrait]                   # named sets of input values, shown as buttons on the Run form
width = 832
height = 1216

[set]                                # fixed values, applied before every check and run
"66.unet_name" = "z_image_turbo_fp8_e4m3fn.safetensors"
```

- **Types, defaults, ranges and choices come from ComfyUI's node list** and the graph's current values. An input only needs to state what differs.
- **Input fields:** `node` or `title`, `field`, `label`, `description`, `type` (`string`, `integer`, `number`, `boolean`, `file`, `files`), `default`, `min`, `max`, `step`, `choices`, `multiline`, `required`, `hidden` (mapped, but not shown or offered to the agent) and `also`.
- **Node ids inside subgraphs** are `outer:inner`, for example `"12:5"`.
- **Unknown keys are errors**, so a typo is reported rather than ignored.
- **Saving the form on the review screen rewrites `workflow.toml` without comments.** To keep comments, use "Edit as TOML" or edit the file directly.

## 4. Tasks and shared input names

A pack's `task` says what it does. The agent gets **one tool per task** that has a ready pack, and any pack of that task can do the job. A call without a `workflow` uses the task's default (the ★ on the Workflows tab), or the only pack if there's one. Tasks live in `services/comfy/tasks.toml`; a new task is a new table there.

| Task | Tool | Needs inputs | Makes |
|---|---|---|---|
| `text-to-image` | `generate_image` | `prompt` | image |
| `image-edit` | `edit_image` | `image`, `prompt` | image |
| `image-to-video` | `animate_image` | `image`, `prompt` | video |
| `text-to-video` | `generate_video` | `prompt` | video |
| `upscale` | `upscale_image` | `image` | image |
| `remove-background` | `remove_background` | `image` | image |
| `custom` | only through `run_workflow` | — | — |

**Shared names:**
- `prompt` (`prompt_2` for a second stage), `negative`
- `image` (`image_2`, … for more), `mask`, `video` (a clip to restyle, or one whose motion drives the result)
- `width`, `height`, `seed`, `steps`, `cfg`, `strength` (denoise), `frames`, `fps`
- `aspect` and `megapixels` when the workflow picks its size with a resolution node (they're passed as they are)

**Derived inputs.** You don't map these; the adapter turns them into fields the pack does map:
- `aspect` + `megapixels` set `width` and `height`, in multiples of 16
- `seconds` sets `frames`, kept at 4k+1 when the graph's own frame count is (Wan)

**File inputs** (`image`, `mask`, `video`) take any of these:
- `output:<id>`: an AIHub output
- `upload:<name>`: from `POST /v1/uploads`, or the Upload button
- a result's path, such as `comfy/2026-10-06/….png` (the "Use as input" button)
- a file already in ComfyUI's input folder

## 5. Changing a workflow

| To change | Do |
|---|---|
| The graph (nodes, wiring, defaults) | Open it in ComfyUI (it's `<id>.json` in the workflow browser) and save. The pack updates within a second. |
| Which inputs it shows, their names and ranges | Edit `workflow.toml`, or open **Edit** on its card |
| A model file, a sampler, any fixed value, without opening ComfyUI | Add it to `[set]` |
| Quick variants | Add `[presets.<name>]`, or `comfyui workflows copy` and edit the copy |
| The card picture | Put `preview.webp` (or `.png`/`.jpg`) in the folder |
| Remove it | Delete the folder, or **Remove** on the review screen (the folder moves to `workflows/.trash/`) |

After editing, check it on the card (ready, or the problems), or run `comfyui workflows check <id>`.

## 6. The command line

```
comfyui workflows list                    every pack and draft, with its state
comfyui workflows show <id>               inputs, nodes (ids, types, titles, values) and problems
comfyui workflows check <id>… | --all     problems, with how to fix each
comfyui workflows suggest <id> [--write]  the drafted workflow.toml (--write saves it if there's none)
comfyui workflows new <id> --from <file|draft-id> [--accept]   (a JSON, PNG/WebP/MP4 or zip; relative paths work)
comfyui workflows copy <id> <new-id>
```

These commands work while ComfyUI is down: they use ComfyUI's node list as cached at its last start (`services/comfy/data/object_info.json`). `comfyui start|stop|status|logs` control ComfyUI itself.

## 7. Problems and their fixes

| Problem | Meaning | Fix |
|---|---|---|
| `missing_node` | A node type isn't installed. The package is named when the workflow recorded it. | Install that custom-node package with ComfyUI-Manager (in ComfyUI), then reload comfy. AIHub never installs custom nodes, because they run code. |
| `missing_model` | A loader names a file ComfyUI can't see | Download it into `data/models/comfyui/<folder>/`. The review screen has a Download button when the workflow recorded a URL. Or use `[set]` to point at a file you have. |
| `missing_input_file` | A LoadImage names a file that isn't in ComfyUI's input folder | Map it as an input (`image`), or put the file in `assets/` |
| `invalid_choice` | A setting's value isn't one of its options any more | Pick one in ComfyUI, or set it with `[set]` |
| `input_unmapped` | An input points at a node or field that doesn't exist (often after a re-save renumbered nodes) | Fix `node`/`title`/`field`; `comfyui workflows show <id>` lists the nodes |
| `task_input_missing` | The task needs an input name the pack doesn't map | Map it (for example `image`), or choose another task |
| `convert_failed` | The editor file couldn't be turned into an API graph | Run it once in ComfyUI and import it from history, or put the exact graph in `workflow.api.json` |
| `editor_links` | An "Anything Everywhere" node broadcasts values to other nodes' inputs; those links exist only in ComfyUI's editor | Run it once in ComfyUI and import it from history (the exact graph has the links), or connect those inputs directly and save |
| `no_output` | Nothing saves results | Add a Save Image / Save Video node in ComfyUI |
| `left_out` (note) | An editor-only node that isn't installed and isn't connected (a bookmark, a group helper) | Nothing; it doesn't affect the run |

**What converts.** The converter matches ComfyUI's own frontend exactly on the 12 development workflows and on 11 of 13 held-out ones (plan 11.12, [comfy-transfer-report.md](comfy-transfer-report.md)). It handles:
- widget values, including seed control values and upload buttons
- dynamic inputs (`format.codec`)
- links, Reroute, Primitive nodes, KJNodes Set/Get, and notes
- muted and bypassed nodes
- subgraphs, including promoted widgets, renumbered the way ComfyUI does when ids collide
- inputs added to a node since the file was saved (they take their defaults)
- rgthree's Power Lora Loader values, and rgthree's editor-only helpers (group bypassers, bookmarks)

For anything it can't follow, it names the node.

## 8. Running

- **The page:** Run tab → pick a workflow → fill the form (presets fill it too) → Run. Progress is live, and results land in `outputs/comfy/<date>/` with a sidecar (prompt, seed, settings, workflow), and on the Outputs page.
- **The API:**
  ```
  POST /api/s/comfy/v1/run {"workflow": "zimage-turbo", "inputs": {"prompt": "…", "aspect": "3:2"}, "preset": "portrait"}
  GET  /api/s/comfy/v1/jobs/<job id>?wait=300      # waits up to 300 s, then returns its outputs
  ```
- **The agent:** `GET /api/s/comfy/v1/tools` lists the task tools; `POST /v1/tools/<name>/call {"arguments": {…}}` runs one as a job.

**Memory.** A run asks AIHub for memory first. The amount is:
1. `memory_gb` if the pack sets it
2. otherwise the last 10 runs' peak + 5%
3. otherwise the model files × 1.2

If other mods have to be unloaded, the page asks first. ComfyUI starts on the first run (about 15 s), and stops after 10 minutes idle.

## 9. AIHub's own nodes

`services/comfy/nodes/aihub_nodes/` is a ComfyUI node package that AIHub owns and tracks in git. It loads through `extra_model_paths.yaml` next to `custom_nodes/`, which holds the third-party packages and is gitignored. It holds fixes and nodes the packs need, measured in [comfy-transfer-report.md](comfy-transfer-report.md):

- **The Qwen-VL vision patch-embed runs as a matmul.** The Qwen2.5-VL, Qwen3-VL and Qwen3.5 vision towers embed patches with a Conv3d whose kernel equals its stride, which is one matrix multiply. ROCm runs that Conv3d about 100× slower, so it was half of every Qwen-Image 2.1 text encode with images. The patch applies when ComfyUI loads the package, and the result is the same to rounding.
- **`AIHubTextEncodeQwenImage21`** is `TextEncodeQwenImage21` that reads the prompt and reference images once. The core node encodes them a second time for the negative, which the sampler never uses at cfg 1. Turn on `encode_negative` when a pack's cfg is above 1.

Changes here take effect when ComfyUI restarts (`comfyui restart`, or unload and load comfy).
