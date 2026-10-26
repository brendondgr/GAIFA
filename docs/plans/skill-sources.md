# Plan: skills from the chat's workspace, uploads and the open skill format

**Asked for:** 2026-10-26 · **Status:** In progress

## 1. Introduction

The agent reads three kinds of skills today, all inside GAIFA (plan 14.9, 22.1): a mod's (`[agent] skills`, served at `/api/skills`), the learner's harness (`data/agent/harness/`) and the user's own (`data/agent/skills/<name>/SKILL.md`). The prompt lists each one's name and description, `read_skill` loads the body, and the composer offers one slash command per skill (`services/agent/agent/knowledge.py`, `web/chat/chat-composer.js`). Skills written for other agents are never seen, even in a repository the chat is working in, and the frontmatter reader takes only one-line `key: value` pairs, so many outside skills would load with a broken description.

Nearly every coding agent now reads the same open format ([agentskills.io](https://agentskills.io/specification): a folder with `SKILL.md`, frontmatter `name` and `description`, optional `scripts/`, `references/`, `assets/`, loaded in stages); they differ only in where the folders are. The approach: **skills come from the workspace the chat is working in**, never from the user's home folders. For each folder of the chat's environment (and each folder the user allowed in that chat; plan 34), the workspace mod looks in every known agent's skill folder and lists what it finds; a chat with no environment (None) or no folders gets only GAIFA's own skills, as today. The same scan lists the folder's instruction files (`AGENTS.md`, `CLAUDE.md`, …) as something to read before working there. Skills can also be uploaded (a folder, a zip or one `SKILL.md`) or copied from a workspace folder into the user's own skills. Touches architecture §14.1 (the agent), §14.4, the workspace mod's README and the brief's §11.13 (the composer) and §11.12.

## 2. Gaps & unanswered questions

- **Which folders are scanned:** answered by the user (2026-10-26): only the chat's workspace folders, each one's own skill folders; no workspace, no scan; never `~/.claude`, `~/.agents` or other home folders.
- **Where in a folder:** *Assumption:* the folder's top level only (`<folder>/.claude/skills/*/SKILL.md` and the like), not every subfolder; a folder that is itself a skill folder's parent is not special. Nested repositories are separate workspace folders if the user wants them.
- **The locations table** (`services/workspace/skillscan.py`, one place to change): `.agents/skills`, `.claude/skills`, `.codex/skills`, `.gemini/skills`, `.cursor/skills`, `.github/skills`, `.opencode/skills`, `.cline/skills`, `.windsurf/skills`, `.devin/skills`, `.goose/skills`, `.roo/skills`. Instruction files: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, and `.cursor/rules/*.mdc` whose frontmatter has `alwaysApply: true`.
- **The same skill in several folders:** one entry per name; the entry lists every place it was found. *As built (2026-10-26):* a copy with other text or files is a `variant` of the first copy in the locations' order (the shared `.agents` first), read by an id qualified by its agent (`jobstuff:claude.apply`) but not listed for the model: this machine's JobStuff keeps each skill in `.agents` and `.claude` with one agent's paths in each, and listing both doubled the prompt.
- **Trust:** a workspace skill is the user's own repository's text, so it is followed as instructions, as Claude Code does; every tool call it leads to still goes through the hub's permissions and approvals. An uploaded or copied skill is screened for prompt injection (the hub's page screening, `utils/tools/screen.py`) and a flagged one is saved turned off, with the reason.
- **Instruction files in the prompt:** *Assumption:* listed, not loaded: "Before working in GAIFA, read its AGENTS.md (read_skill('gaifa:AGENTS.md'))". Small local windows can't carry a large `CLAUDE.md` in every chat. A `CLAUDE.md` that only imports `@AGENTS.md` counts as that file.
- **Scripts in skills:** *Assumption:* a workspace skill's scripts run with the workspace tools in that folder, at that folder's level (Run for the sandbox); an uploaded skill's scripts are kept but not run in this plan (the listing says so).
- **Vendor fields** (`allowed-tools`, `context: fork`, `disable-model-invocation`, `paths`, `argument-hint`, …): *Assumption:* kept as `meta`, shown on the skill's card, not acted on, except `disable-model-invocation: true`, which keeps the skill out of the prompt's list and leaves it as a slash command only, as its authors meant.

## Phase 1 — The open skill format everywhere (S)

- [x] **1.1 Frontmatter and validation: `utils/skillfmt.py`, `services/agent/agent/skillfmt.py`, `services/workspace/skillfmt.py`.**
  - **Parsing:** YAML frontmatter with `yaml.safe_load` (PyYAML: already in the hub's lock through `uvicorn[standard]`; add `pyyaml` to `services/agent/requirements.txt` and `services/workspace/requirements.txt`). Folded and literal scalars, lists and nested `metadata` work; a file without frontmatter or with bad YAML gets `problems`, not an exception.
  - **Shape:** `parse(text) -> {name, description, meta, body, problems}`; `check(name, folder_name, meta)` follows the spec (name 1–64 of `[a-z0-9-]`, no leading, trailing or double hyphen, matching its folder; description 1–1024 characters). A mismatch is a problem shown on the card, not a refusal (other agents' skills are often loose).
  - **Why three copies:** mods never import hub code (architecture §2); each copy is about 60 lines and a test checks they parse the same fixtures alike.
  - **Callers:** `utils/routes/skills.py`, `knowledge.py` and `harness.py` use it instead of their own `frontmatter`.
  *Done when:* `utils/tests/tools/test_skillfmt.py` covers a folded description, a list, nested metadata, no frontmatter, broken YAML and each name rule, and runs the same fixtures through the agent's and workspace's copies; the existing skill tests pass.
- [x] **1.2 A skill's other files: `read_skill('<id>/<path>')`.**
  - **Agent:** `Knowledge.read` takes `<id>/<relative path>` for a file inside the skill's folder (`references/forms.md`); a body's result ends with the list of its other files and sizes. Text files only, 256 KB at most, no `..`, no symlink out of the skill folder.
  - **Hub:** `GET /api/skills/{mod}/{name}/files/{path:path}` for mods' skills, with the same rules.
  *Done when:* `services/agent/tests/test_skills_files.py` reads a reference file and refuses `..`, a symlink out and a binary file; `utils/tests/tools/test_skills.py` covers the hub route.
- [x] **1.3 The repository's own skill copies agree: `.claude/skills/`, `.agents/skills/`.**
  - **Now:** both trees are tracked copies and `comfy-workflow`, `gaifa-mod` and `plan` have drifted. Make `.claude/skills` the source, bring `.agents/skills` level with it (keeping any newer text from either side), and add a test that the trees are identical.
  - **Docs:** `docs/structure.md` names both trees and which one to edit; `AGENTS.md` and `CLAUDE.md` say so in one line.
  *Done when:* `utils/tests/test_skill_copies.py` passes; `diff -r .claude/skills .agents/skills` is empty.

**Checks & deliverables — Phase 1**
- [x] A skill with a folded multi-line description lists with its whole description in Settings → Agent (`GET /v1/settings`, `test_skills_files.py`).
- [x] Delivered: the three `skillfmt.py`, the files route, the copies test.

## Phase 2 — Skills from the chat's workspace folders (M)

- [x] **2.1 The scan: `services/workspace/skillscan.py`, routes in `services/workspace/server.py`.**
  - **Routes:** `GET /v1/skills` (the folders of the call's environment and those allowed in its chat, resolved as `GET /v1/folders` does; `?environment=` for the page) → `{skills: [{id, name, description, folder: {id, name, path}, agent, path, hash, found_in: [paths], files, problems, meta}], instructions: [{id, folder, file, lines, imports?}]}`; `POST /v1/skills/read {folder, path}` → `{text, files}` for a `SKILL.md`, one of its files or an instruction file.
  - **Rules:** the folder's level is at least Read (every level is); the hard limits apply (`folders.py`: no symlink out, secret files never read, 2 MB); `.git`, `node_modules` and the like are never entered; at most 200 skills per folder; results cached per folder by the skill folders' mtimes.
  - **Ids:** `<folder id>:<skill name>` (the folder's id, unique among the folders), qualified by agent only on a clash (2 above); a skill is the same when its text and its files are.
  *Done when:* `services/workspace/tests/test_skills.py` covers a folder with `.claude/skills` and `.agents/skills` holding the same skill (one entry, two places), a clash, a symlink out (skipped), a secret file inside a skill (not read), None and an empty environment (nothing), an allowed-in-chat folder, and `AGENTS.md` plus a `CLAUDE.md` that imports it (one entry).
- [x] **2.2 The agent lists them per chat: `knowledge.py`, `loop.py`, `hubapi.py`.**
  - **Knowledge:** `skills(tid)` adds the chat's workspace skills (`hub.chat_skills(tid, environment)` → the workspace mod through the hub, with the same origin as `chat_folders`); `skill_list` groups them under their folder ("From GAIFA (workspace): …"), leaving out `disable-model-invocation` ones; `read` takes `<folder>:<name>` and `<folder>:<name>/<path>` and instruction files (`gaifa:AGENTS.md`).
  - **Prompt:** the instruction files are listed with the folder's skills (`knowledge.workspace_list`): "Before working in GAIFA, read its instructions with read_skill: gaifa:AGENTS.md".
  - **Off:** nothing when the workspace mod is off, turned off in the chat, or doesn't answer (the prompt goes on, as `folders_note` does).
  *Done when:* `services/agent/tests/test_workspace_skills.py` (fake hub): a chat in an environment with a skill lists and reads it; a chat in None lists none; a chat with workspace turned off lists none; the instruction note appears.
- [x] **2.3 The composer's slash commands per chat: `web/chat/chat-pane.js`, `chat-composer.js`.**
  - **Source:** *as built:* `ChatPane` asks the workspace mod directly (`GET /v1/skills` with the chat's environment, as it already asks for `/v1/folders`), not an agent route; nothing when the workspace is turned off in the chat. `GET /v1/settings` keeps only GAIFA's own skills.
  - **UI:** `chatSkills(own, workspace)` puts them after GAIFA's own; the slash list offers one as `/<folder>:<name>`, found by either part, its hint led by the folder's name; it sends `Use the <id> skill: …` as today.
  *Done when:* `utils/tests/web/chat.test.mjs` covers the matches and hints; on the installed hub a new chat in the Job Applications environment offers `/jobstuff:apply` for `/ap`, and in None doesn't. ✓ 2026-10-26.

**Wire — Phase 2:** the chat's slash menu and the agent's skill list follow its environment.

**Checks & deliverables — Phase 2**
- [x] On the installed hub, a chat whose environment holds `~/Agents/GAIFA` lists `gaifa:plan`, `gaifa:gaifa-mod` and the others once each (both trees), reads `gaifa:plan/planner.md`, and is told to read `gaifa:AGENTS.md`; the same chat moved to None lists none of them. *As checked (2026-10-26):* the scan of the GAIFA folder gives the six skills once each, `AGENTS.md` and `CLAUDE.md`, and `planner.md`; no environment here holds GAIFA, so the chat check ran on Job Applications (`~/Tools/JobStuff`): its 8 skills in the prompt (skills 139 → 395 tokens), none in None.
- [x] Delivered: `services/workspace/skillscan.py`, the agent's changes, the composer's, tests; docs: the workspace README (routes), architecture §14.1, the brief's §11.13, `docs/structure.md`.

## Phase 3 — Uploading and copying skills (M)

- [ ] **3.1 The agent's skills routes: `services/agent/agent/api_skills.py`.**
  - **Routes:** `POST /v1/skills` (multipart: one `SKILL.md`, a zip, or a folder's files with their relative paths) → validated into `data/agent/skills/<name>/`; `PATCH /v1/skills/{name}` `{enabled}`; `DELETE /v1/skills/{name}` (moved to `data/agent/skills/.trash/<name>-<date>/`, never removed at once); `POST /v1/skills/copy {id}` copies a workspace skill (its files through `POST /v1/skills/read`).
  - **Limits:** 2 MB and 100 files a skill, no symlinks, no path outside the folder, names per 1.1; 409 for a name in use unless `replace`.
  - **Screening:** the body and its text files go through the hub's page screening (plan 30.6, `utils/tools/screen.py`) through a new hub route, `POST /api/screen {text}` → `{findings, checked}` (`utils/routes/webpages.py`, beside the page routes; the text is not stored); flagged → saved with `enabled = false` and the findings in `data/agent/skills/<name>/.gaifa.json`. When the screening model doesn't answer, the skill is saved off with "not checked".
  *Done when:* `services/agent/tests/test_api_skills.py` covers each input form, a zip with `../` (refused), a flagged skill (off), copy from a fake workspace, delete into `.trash`; `utils/tests/tools/test_screen_route.py` covers the route with a fake model.
- [ ] **3.2 Settings → Agent → Skills: `web/chat/chat-settings.js` (`SkillsCard`).**
  - **List:** every skill GAIFA has, grouped by source (mine, learned, each mod), each with its description, problems and an on/off switch; "Upload…" (file picker for a `.md`, `.zip` or folder) and a drop zone; Delete asks first.
  - **From workspace:** the skills of the folders of the environment picked at the top of the card, each with "Copy to my skills".
  *Done when:* `utils/tests/web/chat-settings.test.mjs` covers the grouping; on the second hub (`?mock`) an upload, a copy and a delete show in the list.

**Wire — Phase 3:** Settings → Agent → Skills is live (upload, copy, switch off, delete).

**Checks & deliverables — Phase 3**
- [ ] On the installed hub: upload `~/.claude/skills/portfolio-readme` as a folder; it lists under "mine", appears in a new chat's `/` menu and is read when asked.
- [ ] Delivered: `api_skills.py`, the card, tests; docs: the agent's README, architecture §14.1, `docs/structure.md`.

| Deliverable | Description | Location |
| --- | --- | --- |
| Skill format | YAML frontmatter, the spec's checks | `utils/skillfmt.py`, `services/agent/agent/skillfmt.py`, `services/workspace/skillfmt.py` |
| Workspace scan | skills and instruction files of the chat's folders | `services/workspace/skillscan.py` |
| Agent | per-chat skills, reading files, upload and copy | `services/agent/agent/knowledge.py`, `api_skills.py` |
| UI | the slash menu per chat, Settings → Agent → Skills | `web/chat/chat-pane.js`, `chat-composer.js`, `chat-settings.js` |
| Tests | format, scan, per-chat listing, routes, UI | `utils/tests/tools/test_skillfmt.py`, `services/workspace/tests/test_skills.py`, `services/agent/tests/test_workspace_skills.py`, `test_api_skills.py`, `utils/tests/web/*.test.mjs` |
