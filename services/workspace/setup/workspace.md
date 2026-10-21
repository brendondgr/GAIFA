<!-- aihub-setup
id = "workspace"
title = "Workspace (folders, edits in place, the sandbox)"
models = []
scan = []
-->

# Workspace: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

Two environments:

1. **The mod's venv** (FastAPI, uvicorn, httpx). It keeps the folders you add as workspaces, each at a level (Read · Edit · Run · Run + network), in `data/state/workspace/folders.json`. Git and ripgrep on the host serve the reading tools.
2. **The sandbox image** `localhost/aihub-workspace-sandbox:2` (rootless podman), where commands and Python run: only Python 3.12, uv, Node LTS, git, ripgrep, build-essential and the data libraries (numpy, pandas, matplotlib, openpyxl, python-pptx, python-docx, pypdfium2), from `sandbox/Containerfile` and `sandbox/requirements.lock`.

## Tested with

Read from this machine on 2026-10-20:

- **The venv:** Python 3.14.6 (uv-managed), fastapi 0.156.3, uvicorn 0.54.0, httpx 0.28.1; on the host git 2.56.0, ripgrep 15.2.0, podman 5.8.9 (rootless, pasta networking, cgroups v2 with memory and pids delegated) on Fedora 44.
- **The image** (version 2, built 2026-10-20, id `d8a8c5248a4f`, digest `sha256:f52b6ddbfb5eae3fb479e2bc4a0fbb8e27af0630083655daf4e1b2be805fc369`, 1.06 GB; version 1 set `UV_PYTHON`, which made `uv pip install` aim at the read-only system Python instead of the project's `.venv`): Python 3.12.15, uv 0.13.4, Node v24.22.0 with npm 11.19.1, git 2.39.5, ripgrep 13.0.0, gcc 12.2.0 (Debian 12), numpy 2.5.4, pandas 3.0.6, matplotlib 3.11.2, openpyxl 3.1.5, python-pptx 1.0.2, python-docx 1.2.0, pypdfium2 5.14.0 (the rest in `requirements.lock`).
- **Base images,** pinned by digest in the Containerfile: `python:3.12-slim-bookworm@sha256:34386ef0…07258`, `node:24-bookworm-slim@sha256:a5f4366e…daee5`, `ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421…0262b`.

## Prerequisites

- [The hub](../../../docs/setup/hub.md).
- `git` and `rg` (ripgrep) on the host ([host.md](../../../docs/setup/host.md)); without `rg` the search tool falls back to Python.
- **Rootless podman** with cgroups v2 (memory and pids controllers delegated to your user, as Fedora does) and `pasta` for Run + network. Building the image needs the internet once.

## Install

```bash
aihub install workspace
```

Makes `.venv/` in this folder from `requirements-dev.txt`. Then build the sandbox image, from the Workspace page (Sandbox → Build) or by hand:

```bash
podman build -t localhost/aihub-workspace-sandbox:2 -f services/workspace/sandbox/Containerfile services/workspace/sandbox
```

To change the data libraries: edit `sandbox/requirements.in`, recompile `requirements.lock` (the command is at its top), bump `VERSION` in `sandbox.py`, rebuild.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `WORKSPACE_STATE` | `service.toml [run].env` | no | where folders, checkpoints and run records live (default `data/state/workspace`) |

## Check it works

```bash
aihub start workspace && aihub check workspace
cd services/workspace && .venv/bin/python -m pytest -q
```

Expect `all checks passed`, and the tests green; `tests/test_sandbox.py` (marked `podman`) runs the real sandbox and is skipped until the image is built.

## What to look for

- A folder you add shows **Read** until you raise it on the Workspace page. The AIHub folder and `data/models/` can't go above Read.
- **How a run is shaped:** `podman run --rm --userns=keep-id --security-opt label=disable --read-only --memory=8g --pids-limit=1024 --network=none|pasta`, a tmpfs at `/tmp` and at `$HOME`, `~/.cache/uv`, `~/.cache/pip` and `~/.npm` as overlays (`:O`, read but never written back), the folder at its own path (`rw` from Run, else `ro`), with the AIHub folder and `data/models/` mounted `ro` on top when the folder contains them; a folder whose path has a `:` or `,` can't be mounted (`bad_mount_path`). `label=disable` because relabelling your folder for SELinux would change its files' labels.
- **"Read-only file system"** in a run: the folder is below Run. **Exit 127, "not found":** the program isn't in the image; the run's note suggests installing it into the folder (Run + network) or running on your machine (`where = "host"`, which always asks).
- A project `.venv` made **on the host** points at the host's Python and won't run in the sandbox; make one inside the sandbox (`uv venv` / `uv sync` at Run + network) and it keeps working, because the folder is at the same path.

## Known gaps

- The image is built by hand or from the page; nothing rebuilds it when `requirements.lock` changes.
