<!-- aihub-setup
id = "workspace"
title = "Workspace (folders, edits in place, the sandbox)"
models = []
scan = []
-->

# Workspace: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `workspace` mod's own venv (FastAPI, uvicorn, httpx). It keeps the folders you add as workspaces, each at a level (Read · Edit · Run · Run + network), in `data/state/workspace/folders.json`. Git and ripgrep on the host serve the reading tools.

## Tested with

Read from this machine on 2026-10-20: Python 3.14.6 (uv-managed), fastapi 0.156.3, uvicorn 0.54.0, httpx 0.28.1; git 2.56.0, ripgrep 15.2.0, podman 5.8.9 (rootless) on Fedora 44.

## Prerequisites

- [The hub](../../../docs/setup/hub.md).
- `git` and `rg` (ripgrep) on the host ([host.md](../../../docs/setup/host.md)); without `rg` the search tool falls back to Python.

## Install

```bash
aihub install workspace
```

Makes `.venv/` in this folder from `requirements-dev.txt`.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `WORKSPACE_STATE` | `service.toml [run].env` | no | where folders, checkpoints and run records live (default `data/state/workspace`) |

## Check it works

```bash
aihub start workspace && aihub check workspace
cd services/workspace && .venv/bin/python -m pytest -q
```

Expect `all checks passed`, and the tests green.

## What to look for

- A folder you add shows **Read** until you raise it on the Workspace page. The AIHub folder and `data/models/` can't go above Read.

## Known gaps

- None yet.
