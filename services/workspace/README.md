# Workspace

An AIHub mod (plan Phase 27): folders on this machine that the chat agent reads, edits in place and runs code in. Each folder has a **level**, and the chat's **mode** decides what asks first; the stricter of the two wins. Setup: [setup/workspace.md](setup/workspace.md). The mod guide is [docs/mods.md](../../docs/mods.md).

## Levels

| Level | What can happen in the folder |
|---|---|
| **Read** (`read`) | list, read, search, read-only git. Every new folder starts here. |
| **Edit** (`edit`) | also edit, write, move and delete files in place, and commit |
| **Run** (`run`) | also run commands in the sandbox (no network) |
| **Run + network** (`run_net`) | the sandbox with full internet |

The AIHub folder (and anything inside it) and `data/models/` never go above Read. A folder that *contains* AIHub keeps its level for its other files, but nothing inside AIHub is ever written.

## Hard limits

Nothing lifts these (`folders.py`):
- paths outside the folder, or through a symlink that leads out of it;
- secret files (`.env`, `*.pem`, `id_*`, `*credential*`, `secrets*`, as any part of the path), unless the user names the file in their message;
- `.git/` is written only by the git tools;
- reading files over 2 MB (unless named) or binary files.

Listings and searches skip `.git`, `node_modules`, `.venv`, caches and build folders.

## Routes

| Route | What it does |
|---|---|
| `GET /health` | 200 while the server is up |
| `GET /v1/status` | folders, edits and runs |
| `GET /v1/folders` | the folders with their levels (`max_level` and `capped` say why one is held at Read) |
| `POST /v1/folders` | `{path, level?, allow_bypass?, id?, name?}` adds one (Read unless you say otherwise) |
| `PATCH /v1/folders/{id}` | `{level?, allow_bypass?, name?}` |
| `DELETE /v1/folders/{id}` | removes it from the list; its files are left alone |

## Working on it

```bash
cd services/workspace && .venv/bin/python -m pytest -q
aihub check workspace
```
