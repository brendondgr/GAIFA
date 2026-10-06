# Images & Video (comfy)

AIHub's ComfyUI mod (plan Phase 11). The adapter, a FastAPI app on `127.0.0.1:5070`, starts ComfyUI (port 8199, in the `strix-halo-comfyui` ROCm toolbox) when it's loaded, and runs **workflow packs**: one folder per workflow in `workflows/`. The pack format and how to make one: [docs/workflows.md](../../docs/workflows.md).

- `comfy/`: the adapter package (`python -m comfy`)
- `bin/comfyui`: start, stop and inspect ComfyUI itself
- `workflows/<id>/`: the packs, shared with ComfyUI's workflow browser
- `tasks.toml`: the tasks packs can implement, and their shared input names

Tests: `.venv/bin/python -m pytest` in this folder.
