# Workspace

An AIHub mod (plan Phase 27): folders on this machine that the chat agent reads, edits in place and runs code in. Each folder has a **level**, and the chat's **mode** decides what asks first; the stricter of the two wins. Folders are grouped in **environments** (plan 34): a chat works in one. Setup: [setup/workspace.md](setup/workspace.md). The mod guide is [docs/mods.md](../../docs/mods.md).

## Environments

An environment is a named set of folders, each with its own level there (a folder can be Read in one and Edit in another), after Claude's. They live in `data/state/workspace/environments.json`. **Default** always exists (rename it, never delete it); **None** (`none`, plan 42.5) is built in and never stored: no folders, listed first, never renamed, deleted or given folders (422 `none`); Phase 27's `folders.json` became Default on first load, ids and levels kept (the old file is left as it was). A folder's id is the same in every environment, and no two folders share one.

A chat picks its environment under its message box (⌂, plan 42.3; saved as the thread's `settings.environment`; a new chat starts with the last one picked in that browser, else None). The agent sends it in each call's origin (`environment`); a chat without one, or whose environment was deleted, uses Default. Every tool call sees only:
- the folders of the chat's environment, and
- the folders the user allowed **in that chat** (the hub passes them as `origin.folders`, from the chat's folder grants; only the hub sets it). These are always Read here, whatever the origin says, and are checked again as below.

**Asking for a folder.** When the agent reads (tree, read, search, git) a full path (`~/…`, `/home/…`) that is in no folder of the chat, the preflight answers `ask_folder: {path, level: "read", max_level, capped?, environment: {id, name}}` with `key = "folder:<path>"` instead of a refusal. The hub turns it into a card in every mode: **Allow for this chat** (a thread-scoped folder grant in the hub; Settings → Agent and the chip's menu can take it back), **Add to "<environment>"** (the page adds it to the environment at Read through `POST /v1/environments/{id}/folders`, then the call runs once) or **Deny**. Editing or running in such a folder is never asked for: it needs the folder in the environment at a higher level. A path inside a folder the chat already has is refused with which folder and path to use instead.

Folders that are never asked for (the Workspace page can still add them): anything outside the user's home or a mounted drive (`/mnt`, `/media/<you>`, `/run/media/<you>`); `/`, the home folder and anything above it; a hidden or secret-looking folder on the way (`~/.ssh`, `~/.config`, `secrets/`); a path that isn't a folder or doesn't exist. Symlinks are resolved first, so one can't lead out. The AIHub folder and `data/models/` stay at Read in every environment.

## Levels

| Level | What can happen in the folder |
|---|---|
| **Read** (`read`) | list, read, search, read-only git. Every new folder starts here. |
| **Edit** (`edit`) | also edit, write, move and delete files in place, and commit |
| **Run** (`run`) | also run commands in the sandbox (no network) |
| **Run + network** (`run_net`) | the sandbox with full internet |

The AIHub folder (and anything inside it) and `data/models/` never go above Read. A folder that *contains* AIHub keeps its level for its other files, but nothing inside AIHub is ever written: the edit tools refuse it, and the sandbox mounts AIHub and the models read-only inside such a folder.

## Hard limits

Nothing lifts these (`folders.py`):
- paths outside the folder, or through a symlink that leads out of it (checked again as each write lands: the folders on the way are opened one at a time without following a symlink, so a folder a sandbox run swaps for a symlink can't send a write out);
- secret files (`.env`, `*.pem`, `id_*`, `*credential*`, `secrets*`, as any part of the path), unless the user names the file in their message;
- `.git/` is written only by the git tools;
- reading files over 2 MB (unless named) or binary files;
- git never runs a program from the folder: hooks, fsmonitor, external diffs, textconv, signing and submodules are off, and every filter, diff and merge driver the repository's own config names is emptied (the user's global ones, such as git-lfs, are kept);
- read-only git takes commits and ranges of commits only (no `rev:path`, no blob by hash), matches `path` literally, and never shows secret files in status, diff or show unless the user named one as `path`.

Listings and searches skip `.git`, `node_modules`, `.venv`, caches and build folders.

## Routes

| Route | What it does |
|---|---|
| `GET /health` | 200 while the server is up |
| `GET /v1/status` | folders, environments, edits and runs |
| `GET /v1/environments` | every environment with its folders and their levels |
| `POST /v1/environments` | `{name, id?}` creates one (no folders yet); 409 for a name in use |
| `GET /v1/environments/{id}`, `PUT /v1/environments/{id}` `{name}`, `DELETE /v1/environments/{id}` | one environment; rename; delete (not Default or None: 422) |
| `POST /v1/environments/{id}/folders` | `{path, level?, allow_bypass?, id?, name?}` adds a folder there (Read unless you say otherwise; capped as below) |
| `PATCH /v1/environments/{id}/folders/{fid}`, `DELETE …/folders/{fid}` | its level, Bypass or name there; remove it from that environment (its files are left alone) |
| `GET /v1/folders` | the folders a chat can use: its environment's (`?environment=` or the origin's, else Default) and, for a chat's call, those allowed in it (`granted: true`); `max_level` and `capped` say why one is held at Read; also `environment: {id, name}` |
| `POST /v1/folders`, `PATCH /v1/folders/{id}`, `DELETE /v1/folders/{id}` | Phase 27's routes, now for Default (or `?environment=`) |
| `POST /v1/tree`, `/v1/read`, `/v1/search`, `/v1/git` | the reading tools (text, contents inside `<untrusted>`) |
| `POST /v1/edit`, `/v1/write`, `/v1/move`, `/v1/delete`, `/v1/git/commit` | the editing tools: each returns its diff and `undo` |
| `GET /v1/checkpoints?thread=` | turns with checkpoints (files, tools, size, the undo route), and the usage |
| `GET /v1/checkpoints/{thread}/{turn}` | one turn's changes |
| `POST /v1/checkpoints/{thread}/{turn}/undo` | every file back as it was before the turn; 409 `changed_since` with diffs when a file changed outside the agent |
| `GET /v1/recent?thread=` | recent edits, runs and undos |

## The page

`ui/page.js`, three tabs: **Environments** (the environments as a switcher with their folder counts; New environment by name; for the one picked: rename, delete (not Default), add a folder by its path at a level, each folder's level there, only up to what it may reach, with the reason when it's capped, "allow Bypass", remove; `#/s/workspace/folders` opens it too), **Activity** (checkpoint usage; each turn's changed files with Undo, which refuses with the diffs if a file changed since; recent runs with their exit codes, Stop for a running one; links to the chat) and **Sandbox** (the image: built or not, Build or Rebuild, the build log). The chat also shows **Undo this turn** under a turn that changed files.

## The sandbox

Commands and Python run in `localhost/aihub-workspace-sandbox:2` (rootless podman, `sandbox.py`): only Python 3.12, uv, Node LTS, git, ripgrep, build-essential and the data libraries. Your user inside, the folder at its own absolute path (read-write from Run), the rest of `$HOME` an empty tmpfs (the uv, pip and npm caches are overlays: read, never written back), a read-only root, no network unless the folder is at Run + network and the call asks for it (then full internet), 8 GB of memory and 1024 processes at most, 120 s by default (600 s at most). Every run is a record in `data/state/workspace/runs/` (`<id>.json` with the last 32 KB of output, `.out` and `.err` with the first 1 MB).

| Route | What it does |
|---|---|
| `GET /v1/sandbox` | the image: built or not, id, size, a build in progress and its log |
| `POST /v1/sandbox/build` | build it (minutes) |
| `GET /v1/runs?thread=`, `GET /v1/runs/{id}` | run records |
| `POST /v1/runs/{id}/cancel` | stop a run |
| `POST /v1/run` | `workspace_run`: `{folder, command, where: sandbox \| host, network?, cwd?, timeout_s?}` → `{run, state, exit_code, seconds, where, network, stdout, stderr, note?}` (output inside `<untrusted>`; `stdout` is `(no output)` when the command printed nothing); Run for the sandbox and the host, Run + network for `network` and git remotes |
| `POST /v1/python` | `workspace_python`: `{code, inputs?, folder?, network?, timeout_s?}`; inputs (outputs) are fetched from the hub into `inputs/` (`$AIHUB_INPUTS`); without a folder every file the code writes becomes an output in `outputs/workspace/<date>/<HHMMSS>-<name>` with a sidecar (the run and the code); with a folder, files in `$AIHUB_OUT` do. Only regular files become outputs: a symlink the code leaves is skipped |
| `POST /v1/limits` | the hub's preflight before each call (plan 27.4): `{action, folder, level, allow_bypass, key, once, preview, refuse?, ask_folder?}` (`ask_folder`: plan 34, above). A command's `key`, what "allow in this chat" covers, is the folder (and `cwd`) plus the exact command line, with " (with internet)" or " (on this machine)": `proj pytest -q`. A compound command (`;`, `&&`, `\|\|`, `\|`, `&`, backticks, `$(`, newlines, redirections) has no key and is `once` |

A call that goes away (the hub cancelled it) stops its run. Host runs (`where = "host"`) run `bash -c` in the folder on your machine, with your files and network, and are only reached after you allowed that one call: no grant covers them.

## Checkpoints

Before any change, the file's bytes (or "didn't exist") go to `data/state/workspace/checkpoints/<thread>/<turn>/` (`entries.json`, `NNN.bin` before, `NNN.after` as the agent left it). The thread and turn come from the call's `X-AIHub-Origin`; a call from outside a chat is its own turn (`_direct`). Undo restores a whole turn, newest change first, and restores nothing if any file changed since or now leads outside its folder (a folder on the way became a symlink: 409 with "it now leads outside its folder" and no diff). Kept 14 days or 2 GB, oldest turns first. Commits aren't checkpointed (git keeps them). A chat's first change in a folder reports a dirty working tree (`dirty_before`), so the agent knows which changes were the user's.

## Working on it

```bash
cd services/workspace && .venv/bin/python -m pytest -q
aihub check workspace
```
