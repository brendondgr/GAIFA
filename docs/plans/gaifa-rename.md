# Plan: the rename to GAIFA (Phase 50)

Asked for on 2026-10-25: AIHub becomes **GAIFA**, "Great, Another Interface For Agents", pronounced "guy-fuh". "AIHub" is a generic name; GAIFA is the product's own. The rename goes everywhere: the docs and READMEs, the UI, the command, every identifier that carries the old name, the skills, the project folder (`~/Agents/AIHub` → `~/Agents/GAIFA`) and the GitHub repository (`brendondgr/AIHub` → `brendondgr/GAIFA`). The README is rebuilt with a generated SVG banner, after the README skill's banner guide (`~/Projects/bdgrClaudeSkills/README-Skill/references/banner-guide.md`).

**What the survey found (2026-10-25):** 2,816 occurrences in 527 of 1,544 tracked files, and 20 tracked paths with the name in them. The forms: prose `AIHub` (≈970), the command `aihub` and `bin/aihub`, environment variables `AIHUB_*` (URL, ROOT, PORT, SERVICE_ID, ACCEL, DEVICE, the GPU ones, OUTPUTS, MODELS, INPUTS, DATABASES, IDLE_UNLOAD_S, CONTAINER_RUNTIME, HARDWARE_FIXTURE, OUT), HTTP headers `X-AIHub-*` (Make-Room, GPU-Lease, Origin, Answer-Within, Thread, Output, Error), systemd units `aihub.service` and `aihub-<id>.service`, the launchd label `com.aihub.hub`, hub files `data/logs/aihub.log`, `data/state/hub/aihub.json|.out`, setup blocks ` ```aihub-setup `, the MCP names `aihub_wait_approval` and `aihub/approval`, logger names `aihub.*`, browser keys `aihub.chat.*`, container and image names `aihub-vllm-*`, `aihub-ws-*`, `localhost/aihub-workspace-sandbox`, the ComfyUI node `AIHubTextEncodeQwenImage21` and package `nodes/aihub_nodes/`, lcpp's `src/lcpp/aihub.py`, the mods' `aihub-install.sh`, SearXNG's `settings.yml.aihub-<date>` backups, the package name in `pyproject.toml`, and the skills `aihub`, `aihub-mod`, `aihub-setup`, `aihub-field-test` (in `.claude/skills/` and `.agents/skills/`). No binary file carries the name; the screenshots in `docs/assets/` show it in the sidebar.

Outside git, on this machine: the 12 running units, `~/.config/systemd/user/aihub.service`, seven wrappers in `~/.local/bin` that point into the folder (`aihub`, `comfyui`, `cubeart`, `gen3d`, `localtts`, `relay`, and the `breeze-tts`/`kokoro-tts` scripts), lcpp's uv tool (`~/.local/share/uv/tools/lcpp`), `~/.local/share/applications/3dgenerate.desktop`, the sandbox image, every mod's `.venv` (absolute paths in scripts and editable installs), the workspace mod's `data/state/workspace/folders.json` (the AIHub folder, id `aihub`), and Claude Code's project memory (keyed by the folder's path). The ComfyUI toolbox mounts all of `/home/bdgr`, so the move doesn't touch it. No database holds the folder's path.

## Naming rules

| Where | Old | New |
| --- | --- | --- |
| Prose, UI text, titles | AIHub | GAIFA (all capitals; "a GAIFA mod", since it starts with a consonant sound) |
| Command, package, units, files, keys, loggers, containers | `aihub` | `gaifa` |
| Environment variables | `AIHUB_*` | `GAIFA_*` |
| HTTP headers | `X-AIHub-*` | `X-GAIFA-*` (compared lower-case as `x-gaifa-*`) |
| Class and node names | `AIHub…` | `GAIFA…` |
| Commit messages | `AIHub (N.k): …` | `GAIFA (N.k): …` |

The name's meaning and pronunciation are said once in the README's first lines, in architecture §1, and in Settings → About.

## Gaps

**Simple gaps (assumed):**
- **Compatibility on the wire: none.** Every reader and writer of the variables, headers and units is in this repository, so they change together in one commit. A mod built outside the repo against `AIHUB_URL` would need the new names; there are none.
- **Compatibility for things saved outside git:** the ComfyUI node keeps its old class name as a second, hidden mapping (workflows saved in ComfyUI's own `user/` folder may use it); the chat's browser settings read their `aihub.chat.*` value once when the `gaifa.chat.*` one is missing; `gaifa install` stops, disables and removes an `aihub.service` and an `~/.local/bin/aihub` link that point at this clone. SearXNG backups made under the old prefix aren't pruned any more (at most 10 small files; left as they are).
- **Git history stays as it is.** Old commit messages keep "AIHub".
- **Historical docs** (dated reports, finished plans, the eval notes) are renamed too, so a search for the old name finds only the compatibility lines and this plan.
- **The logo stays.** `web/favicon.svg` (the amber hub of five nodes) is the product's mark; the banner embeds it from that one file.
- **The work happens in a separate worktree** (`gaifa-rename`, in the session's scratchpad), so the installed hub, its 12 units and the uncommitted chat-page work in the main checkout are untouched until 50.5. The uncommitted work is snapshotted to a local branch `wip/main-2026-10-25` first, and carried over the rename in 50.5 by applying the same renaming to its diff.
- **Pushing:** after 50.6, to the renamed repository.

**Needs a human answer:** none. The user asked for the folder and the repository to be renamed too.

## Phase 50 — The rename to GAIFA (M–L)

- [ ] **50.1 This plan.** `docs/plans/gaifa-rename.md`, listed in `docs/structure.md`.
  *Done when:* the plan is committed.
- [x] **50.2 Every identifier, in one commit.**
  - **Mechanical pass** over all tracked text files except Markdown prose: `AIHub` → `GAIFA`, `AIHUB` → `GAIFA`, `aihub` → `gaifa`; Markdown gets only the parsed parts (the ` ```aihub-setup ` fences, commands, paths and variables inside code) so the prose can land in 50.3. `services/relay/` is included (its `X-AIHub-*` and `AIHUB_*` uses are ours).
  - **Renamed paths:** `bin/aihub` → `bin/gaifa`, `bin/aihub.service.in` → `bin/gaifa.service.in`, `services/*/aihub-install.sh` → `gaifa-install.sh`, `services/comfy/nodes/aihub_nodes/` → `gaifa_nodes/`, `services/lcpp/src/lcpp/aihub.py` → `gaifa.py`, the `test_aihub.py` files → `test_gaifa.py`, `services/gen3d/desktop/3dgenerate-aihub.desktop` → `3dgenerate-gaifa.desktop`.
  - **By hand:** the unit's description (`GAIFA - Great, Another Interface For Agents (http://127.0.0.1:7000)`); the ComfyUI node's old name kept as a hidden alias (`services/comfy/nodes/gaifa_nodes/__init__.py` `NODE_CLASS_MAPPINGS`); the browser keys' one-time fallback (`web/chat/chat-ui.js` `getPref`); the old unit and link cleanup in `gaifa install` (`utils/cli.py`); Settings → About says what the name means; `pyproject.toml` `name = "gaifa"` and `uv lock`.
  *Done when:* `uv run pytest` passes (with its Node tests), and the suite of every mod whose files changed passes in its own venv; `git grep -i aihub` outside Markdown finds only the two compatibility lines.
- [x] **50.3 The docs and skills.** All Markdown: `README.md` (name only; 50.4 rebuilds it), `CLAUDE.md` (status, skills, commands, the commit-message rule), `AGENTS.md`, `docs/` (architecture §1 gains the meaning and pronunciation), every `services/*/README.md` and setup doc, `web/PATCHES.md`; the skill folders `.claude/skills/aihub*` and `.agents/skills/aihub*` renamed to `gaifa*` with their `name:` fields; "an AIHub" → "a GAIFA".
  *Done when:* `uv run pytest` passes, `bin/gaifa docs --check --strict` passes, and `git grep -i aihub` finds only the lines that describe the rename (this plan, the Stage Q row, its structure and patch rows, the name notes in CLAUDE.md, AGENTS.md and architecture §1) and the compatibility lines.
- [x] **50.4 The README and its banner.** `docs/assets/make_header.py` (standard library; after the banner guide) reads `web/favicon.svg` and writes `docs/assets/header.svg`: the logo on its own panel, "GAIFA", the tagline (what it is, then "Great, Another Interface For Agents · say guy-fuh"), a row of languages (Python, JavaScript, HTML, CSS, Shell) and one of the stack (FastAPI, SQLite, uv, ComfyUI, llama.cpp). `README.md` drops `# AIHub` for the banner, opens with what GAIFA is and the name, and keeps the existing sections and their prose (restructure mode: accurate sentences stay), with the clone URL and folder updated and the numbers rechecked (test count, mods).
  *Done when:* the banner renders on white and on GitHub's dark background (`rsvg-convert`), nothing overflows, every command and link in the README resolves, and the README is committed with the script and the SVG.
- [x] **50.5 This machine moves to the new name.** Needs no new code; each step is checked before the next.
  - Snapshot and carry the uncommitted work: merge `gaifa-rename` into `main` with the uncommitted diff renamed and re-applied on top; check it against `wip/main-2026-10-25`.
  - Stop the hub and the 11 mod units (`aihub stop all`, `aihub stop`), `mv ~/Agents/AIHub ~/Agents/GAIFA`.
  - Relocate the venvs: replace the old absolute path in the text files of every `.venv` (scripts, `.pth`, `direct_url.json`), then `uv sync` the hub.
  - `bin/gaifa install` (writes `gaifa.service`, links `~/.local/bin/gaifa`, removes the old unit and link); re-point the other wrappers in `~/.local/bin` and the desktop file; reinstall lcpp's uv tool from `services/lcpp`; tag the sandbox image `localhost/gaifa-workspace-sandbox`; rename `data/logs/aihub.log` and the hub's state files; change the workspace folder record (`data/state/workspace/folders.json`, id `gaifa`, the new path).
  - Start the hub and the mods that were running, `gaifa doctor` and `gaifa doctor --inventory` clean (the two known outside paths aside), the UI loads at <http://127.0.0.1:7000> with GAIFA in the sidebar and title, a chat answers.
  - Claude Code: copy the project memory to the new folder's key, and note the rename in it.
  - Retake `docs/assets/overview.png` (it shows the name in the sidebar); the chat screenshots too where the same chats still exist. Commit.
  *As done (2026-10-25):* the hub and its 11 running mods came back as `gaifa.service` and `gaifa-<id>.service` from `~/Agents/GAIFA`; 536 files in 21 venvs relocated (the drama3-lab venv left alone: it reads with I/O errors since the 2026-10-20 disk damage); `gaifa install` removed the old unit and link; the wrappers, the desktop file (from its template), lcpp's uv tool and the sandbox image's tag moved over; `gaifa doctor` 48 ok, 1 warning (OpenCode's folder, as before); the inventory lists the same two outside paths as before; a chat on skynet answered "This app is called GAIFA" through the hub's status tool. The chat screenshots never show the name, so only the Overview was retaken (through Chromium's DevTools protocol: its `--screenshot` never settles on the live page). Old Claude Code worktrees in `.claude/worktrees/` were re-pointed with `git worktree repair`.
  *Done when:* everything above checks out, and no running process or wrapper points at `~/Agents/AIHub`.
- [ ] **50.6 The GitHub repository.** `gh repo rename GAIFA`, `git remote set-url origin git@github.com:brendondgr/GAIFA.git`, the description set to what GAIFA is, push `main`.
  *Done when:* `git push` reaches `brendondgr/GAIFA`, and the old URL redirects.

**Checks & deliverables — Phase 50**
- [ ] `git grep -i aihub` finds only the lines that describe the rename (this plan, the Stage Q row, its structure and patch rows, the name notes in CLAUDE.md, AGENTS.md and architecture §1) and the compatibility lines.
- [ ] The installed hub runs from `~/Agents/GAIFA` as `gaifa.service`, its mods as `gaifa-<id>.service`, and `gaifa doctor` passes.
- [ ] Delivered: the renamed tree, `bin/gaifa`, `docs/assets/make_header.py` and `header.svg`, the new README.

| Deliverable | Description | Location |
| --- | --- | --- |
| The renamed code | every identifier, file and unit | the whole tree |
| Compatibility lines | the ComfyUI node alias, the browser keys' fallback, the old unit's cleanup | `services/comfy/nodes/gaifa_nodes/__init__.py`, `web/chat/chat-ui.js`, `utils/cli.py` |
| Banner | generated from the logo | `docs/assets/make_header.py`, `docs/assets/header.svg` |
| README | the GAIFA front page | `README.md` |
| Tests | the hub's suite and each changed mod's suite, renamed | `utils/tests/`, `services/*/tests/` |
