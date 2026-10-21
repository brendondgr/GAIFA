# Workspace

An AIHub mod (plan Phase 27): folders on this machine that the chat agent reads, edits in place and runs code in. Each folder has a **level**, and the chat's **mode** decides what asks first; the stricter of the two wins. Setup: [setup/workspace.md](setup/workspace.md). The mod guide is [docs/mods.md](../../docs/mods.md).

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
| `GET /v1/status` | folders, edits and runs |
| `GET /v1/folders` | the folders with their levels (`max_level` and `capped` say why one is held at Read) |
| `POST /v1/folders` | `{path, level?, allow_bypass?, id?, name?}` adds one (Read unless you say otherwise) |
| `PATCH /v1/folders/{id}` | `{level?, allow_bypass?, name?}` |
| `DELETE /v1/folders/{id}` | removes it from the list; its files are left alone |
| `POST /v1/tree`, `/v1/read`, `/v1/search`, `/v1/git` | the reading tools (text, contents inside `<untrusted>`) |
| `POST /v1/edit`, `/v1/write`, `/v1/move`, `/v1/delete`, `/v1/git/commit` | the editing tools: each returns its diff and `undo` |
| `GET /v1/checkpoints?thread=` | turns with checkpoints (files, tools, size, the undo route), and the usage |
| `GET /v1/checkpoints/{thread}/{turn}` | one turn's changes |
| `POST /v1/checkpoints/{thread}/{turn}/undo` | every file back as it was before the turn; 409 `changed_since` with diffs when a file changed outside the agent |
| `GET /v1/recent?thread=` | recent edits, runs and undos |

## The page

`ui/page.js`, three tabs: **Folders** (add a folder by its path, at Read; its level, only up to what it may reach, with the reason when it's capped; "allow Bypass"; remove), **Activity** (checkpoint usage; each turn's changed files with Undo, which refuses with the diffs if a file changed since; recent runs with their exit codes, Stop for a running one; links to the chat) and **Sandbox** (the image: built or not, Build or Rebuild, the build log). The chat also shows **Undo this turn** under a turn that changed files.

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
| `POST /v1/limits` | the hub's preflight before each call (plan 27.4): `{action, folder, level, allow_bypass, key, once, preview, refuse?}`. A command's `key`, what "allow in this chat" covers, is the folder (and `cwd`) plus the exact command line, with " (with internet)" or " (on this machine)": `proj pytest -q`. A compound command (`;`, `&&`, `\|\|`, `\|`, `&`, backticks, `$(`, newlines, redirections) has no key and is `once` |

A call that goes away (the hub cancelled it) stops its run. Host runs (`where = "host"`) run `bash -c` in the folder on your machine, with your files and network, and are only reached after you allowed that one call: no grant covers them.

## Checkpoints

Before any change, the file's bytes (or "didn't exist") go to `data/state/workspace/checkpoints/<thread>/<turn>/` (`entries.json`, `NNN.bin` before, `NNN.after` as the agent left it). The thread and turn come from the call's `X-AIHub-Origin`; a call from outside a chat is its own turn (`_direct`). Undo restores a whole turn, newest change first, and restores nothing if any file changed since or now leads outside its folder (a folder on the way became a symlink: 409 with "it now leads outside its folder" and no diff). Kept 14 days or 2 GB, oldest turns first. Commits aren't checkpointed (git keeps them). A chat's first change in a folder reports a dirty working tree (`dirty_before`), so the agent knows which changes were the user's.

## Working on it

```bash
cd services/workspace && .venv/bin/python -m pytest -q
aihub check workspace
```
