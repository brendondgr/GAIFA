# Images & Video (comfy)

AIHub's ComfyUI mod (plan Phase 11). The adapter, a FastAPI app on `127.0.0.1:5070`, starts ComfyUI (port 8199, in the `strix-halo-comfyui` ROCm toolbox) when it's loaded, and runs **workflow packs**: one folder per workflow in `workflows/`. The pack format and how to make one: [docs/workflows.md](../../docs/workflows.md). Setup on a new machine (the toolbox, ComfyUI's version, the custom nodes): [setup/comfyui.md](setup/comfyui.md).

- `comfy/`: the adapter package (`python -m comfy`)
- `bin/comfyui`: start, stop and inspect ComfyUI itself (`comfyui workflows …` for packs). When the toolbox container is wedged (podman reports it running but `podman exec` fails with "crun: the container … is not running"), `start` and `quit` stop ComfyUI's process from the host and restart the container before going on (`ensure_exec`), so loading ComfyUI from the hub recovers by itself.
- `extra_model_paths.yaml`: ComfyUI reads models from `$COMFY_MODELS` (AIHub's `data/models/comfyui`)
- `custom_nodes/`, `user/`, `input/`: ComfyUI's own folders (gitignored)
- `workflows/<id>/`: the packs. ComfyUI sees each as `user/default/workflows/<id>.json` (a symlink the adapter keeps)
- `tasks.toml`: the tasks packs can implement, and their shared input names

Tests: `.venv/bin/python -m pytest` in this folder.
