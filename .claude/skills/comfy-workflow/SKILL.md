---
name: comfy-workflow
description: Use when asked to add, import, adjust, fix or remove a ComfyUI workflow in AIHub ("add this workflow", "make a pack for X", "why won't this workflow run", "expose the LoRA strength", "use the fp8 model instead"), or to make a workflow available to the agent. Covers workflow packs in services/comfy/workflows/, workflow.toml, tasks, the comfyui workflows CLI and the check problems.
---

# Working with ComfyUI workflow packs

A workflow is a **pack**: `services/comfy/workflows/<id>/` with `workflow.json` (the ComfyUI editor file), an optional `workflow.api.json`, and `workflow.toml` (task, inputs, outputs, presets, `[set]`). **Read [docs/workflows.md](../../../docs/workflows.md) first.** It's the whole format on one page.

## The loop
1. **Bring it in:** `comfyui workflows new <id> --from <file or draft-id>`. This accepts an editor JSON, an API JSON, a PNG/WebP/MP4 ComfyUI made, or a zip. Or import it on the page.
2. **Look:** `comfyui workflows show <id>` lists the nodes (ids, types, titles, values) and the problems.
3. **Draft the manifest:** `comfyui workflows suggest <id>`, review it, then `--write`.
4. **Adjust `workflow.toml` by hand:**
   - use shared input names (`prompt`, `image`, `seed`, `width`, …) so the pack can stand in for others of its task
   - add inputs the detector missed (LoRA strengths, mask boxes)
   - add `[presets.*]`
   - use `[set]` to change fixed values without opening ComfyUI
5. **Check:** `comfyui workflows check <id>` until it says `ready`. Fixes are in docs/workflows.md §7.
6. **Run it once:** `POST /api/s/comfy/v1/run {"workflow": "<id>", "inputs": {…}}`, then `GET /api/s/comfy/v1/jobs/<job>?wait=600`. Do this only when the user wants a real run; it loads models.

## Rules
- **Never install custom nodes yourself.** Name the package and let the user install it with ComfyUI-Manager: custom nodes run third-party code.
- **Ask before downloading model files.** They're large, and downloading needs the user's go-ahead. Say the file, its source and its size.
- **A pack's models are the user's choice.** Record where each file comes from in the workflow (`properties.models` URLs) so the page's Download button and `comfyui workflows check` can name it; don't add a pack's models to comfy's setup doc as requirements (`services/comfy/setup/comfyui.md` suggests a few, optionally).
- **Leave `memory_gb` out unless the user wants to pin it.** Runs measure it.
- **Edit the graph in ComfyUI, not by hand in `workflow.json`.** The pack is `<id>.json` in ComfyUI's browser, and saves there come back into the pack. Use `[set]` for single values.
- **A task needs certain input names** (`tasks.toml`): `image-edit` needs `image` and `prompt`, and so on. The agent only sees packs that are `ready`.
- **Tests:** `services/comfy/.venv/bin/python -m pytest` in `services/comfy`. Never let a test run the real `bin/comfyui`.
