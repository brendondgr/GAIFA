# Images & Video (comfy)

GAIFA's ComfyUI mod (plan Phase 11). The adapter, a FastAPI app on `127.0.0.1:5070`, starts ComfyUI (port 8199, in the `strix-halo-comfyui` ROCm toolbox) when it's loaded, and runs **workflow packs**: one folder per workflow in `workflows/`. The pack format and how to make one: [docs/workflows.md](../../docs/workflows.md). Setup on a new machine (the toolbox, ComfyUI's version, the custom nodes): [setup/comfyui.md](setup/comfyui.md).

- `comfy/`: the adapter package (`python -m comfy`)
- `bin/comfyui`: start, stop and inspect ComfyUI itself (`comfyui workflows …` for packs). When the toolbox container is wedged (podman reports it running but `podman exec` fails with "crun: the container … is not running"), `start` and `quit` stop ComfyUI's process from the host and restart the container before going on (`ensure_exec`), so loading ComfyUI from the hub recovers by itself.
- `extra_model_paths.yaml`: ComfyUI reads models from `$COMFY_MODELS` (GAIFA's `data/models/comfyui`)
- `custom_nodes/`, `user/`, `input/`: ComfyUI's own folders (gitignored)
- `workflows/<id>/`: the packs. ComfyUI sees each as `user/default/workflows/<id>.json` (a symlink the adapter keeps)
- `tasks.toml`: the tasks packs can implement, and their shared input names
- **The GPU slot** (plan 31.3): each run takes GAIFA's GPU slot (`comfy/gpu_slot.py`, a copy of `services/_template/gpu_slot.py`) before it asks for memory and queues its prompt, and gives it back when the prompt finishes, fails or is cancelled. A run that has to wait is answered at once as `queued` with `stage: "waiting_gpu"`, `ahead` and `eta_s` (in `/v1/jobs/{id}` and `/v1/status`); Cancel stops the wait. A request carrying `X-GAIFA-GPU-Lease` (gen3d's TRELLIS.2 or SAM 3D Body) runs under that lease instead of queueing behind its caller.
- **Live previews** (plan 45.1): ComfyUI runs with `--preview-method auto`, so it sends a picture of each sampler step over its websocket. `comfy/previews.py` keeps the newest frame per run (`GET /v1/runs/{id}/preview?after=<seq>`, 204 when there's none newer) and the run's stage and steps, as `live` on `/v1/jobs/{id}` and the status jobs (plan 44.2): Chat, the Overview and the page draw them. Prompts queued from ComfyUI's own page show without frames: ComfyUI sends those only to that page. The agent's tools follow a run with `GET /v1/jobs/{id}?wait=60&live=true`, which answers at each new step or frame, not only at the end.

Tests: `.venv/bin/python -m pytest` in this folder.
