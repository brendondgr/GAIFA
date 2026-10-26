# Plan: mods that are their own repositories, and keeping them up to date

**Asked for:** 2026-10-26 · **Status:** In progress

## 1. Introduction

Four mods began as their own repositories and were moved into GAIFA with `git subtree` (full history) on 2026-10-06 ([backend-plan.md](../backend-plan.md) Phases 7–10):

| Mod | Repository | Branch | Visibility | Old clone (left alone) | GAIFA commits since the move |
| --- | --- | --- | --- | --- | --- |
| `relay` | `brendondgr/Relay` (was DashLLM; GitHub redirects) | `main` | public | `~/Tools/DashLLM`, 1 ahead (the "Moved" commit) | 14 |
| `lcpp` | `brendondgr/LLMs` | `master` | private | `~/Models/LLMs`, 5 ahead (4 unpushed + "Moved") | 20 |
| `tts` | `brendondgr/LocalTTS` | `main` | public | `~/Projects/LocalTTS`, 2 ahead (1 unpushed + "Moved") | 20 |
| `gen3d` | `brendondgr/3DGenerate` | `main` | private | `~/Projects/3DGenerate`, 1 ahead ("Moved") | 29 |

Since then all their work happened in GAIFA, so the repositories stopped on GitHub in September. The user wants each of these to be a real repository of its own again: worked on in its own branches and worktrees, runnable on its own, and used by GAIFA as a mod. The user chose **git submodules** and **a pinned commit, updated on command** (2026-10-26). GAIFA records the exact mod commit it was tested with, and `gaifa repos update <id>` moves it forward. Warnings say when anything drifts.

The approach:
- **Phase 1** gives each repository the history GAIFA added, as a fast-forward with nothing rewritten.
- **Phase 2** turns each folder into a submodule in place, so its ignored files (venvs, `runtime/` engines, `.env`, `data/`) aren't touched.
- **Phase 3** adds the update system: state, `gaifa repos`, hub warnings, settings and the doctor.
- **Phase 4** writes the workflow into the docs and skills, and tests it end to end on a fresh clone.

Touches architecture §3 (layout), §4.8 (adding a mod), §10 (the existing apps), §12 (risks); [docs/mods.md](../mods.md); setup (Phase 23, [docs/setup/README.md](../setup/README.md)). The plan [llm-servers.md](llm-servers.md) builds on this one: its relay and lcpp work happens in those repositories.

## 2. Gaps & unanswered questions

- **Publishing GAIFA-era code to public repositories.** Relay and LocalTTS are public. Pushing them publishes 14 and 20 GAIFA commits, with their `AIHub (…)`/`GAIFA (…)` messages and paths. *Needs a human answer at step 1.3:* the user reads the preflight report (secrets scan, absolute paths, file list) and approves each push.
- **The old clones** (`~/Tools/DashLLM`, `~/Models/LLMs`, `~/Projects/LocalTTS`, `~/Projects/3DGenerate`) hold their unpushed "Moved to AIHub" commits. *Assumption:* the plan never touches them. Their unpushed real commits are already in GAIFA's history, because each subtree was added from the commit before "Moved". Deleting them is the user's call, afterwards.
- **Rewriting history.** *Assumption:* never. Every push is a fast-forward of the remote branch. A push that isn't one stops the step and asks.
- **URLs in `.gitmodules`.** *Assumption:* SSH (`git@github.com:brendondgr/<repo>.git`), like the user's clones. Another machine needs SSH access to the two private repositories. `gaifa setup` says so when a clone fails (4.3), and [docs/platforms.md](../platforms.md) notes it.
- **Commit messages inside a mod repository.** *Assumption:* the mod's own style (`<what was done>`, no `GAIFA (…)` prefix). GAIFA's pin commits name the plan as usual: `GAIFA (<slug> N.k): relay → <short sha> (<what changed>)`.
- **Background fetching contacts GitHub.** *Assumption:* on, once a day (`[repos] fetch_every_h = 24`). It can be turned off, and a failed fetch is a quiet info line, never an error.
- **Automatic updates.** *Assumption:* none. The user chose updates on command. A newer commit is a notice with an Update button.
- **Mods without a repository of their own** (`agent`, `comfy`, `vllm`, `web`, …) stay folders in GAIFA. A mod can become a submodule later with the same steps (documented in 4.1).

## Phase 1 — Give each repository GAIFA's history (M)

- [x] **1.1 Each mod ignores its own files: `services/{relay,lcpp,tts,gen3d}/.gitignore`.**
  - **What:** GAIFA's root `.gitignore` covers `/services/*/.venv/`, `/services/*/runtime/` and `/services/*/.env`, plus per-mod entries like lcpp's machine-specific `data/models.json` (plan 23.11). Once a folder is a submodule, only its own `.gitignore` applies. Copy every rule that matches inside the folder into the mod's `.gitignore`, written relative to the mod. The check is `utils/repos.py: ignore_gap(sid) -> list[str]`: the paths that `git status --ignored --porcelain` in GAIFA ignores under `services/<sid>/` but the mod's own rules don't (checked with `git check-ignore --no-index` in the folder).
  - **Why first:** these commits must be in the history that 1.2 splits out, so the repository never shows a venv or a key as untracked.
  *Done when:* `ignore_gap` is empty for all four; `utils/tests/repos/test_ignore_gap.py` builds a temp GAIFA-like repo with a mod folder and covers a missing rule, a negated rule and a rule only the root has.
- [x] **1.2 Split and preflight: `utils/repos_migrate.py`, `utils/repos_split.py`.**
  - **Split:** `utils/repos_split.py` does what `git subtree split --prefix services/<sid> -b split/<sid>` does, with plumbing (`git subtree` isn't installed on this machine): every GAIFA commit that changed the folder becomes a commit of that folder with its author, dates and message, on top of the commit the subtree add brought in. It's deterministic, so splitting again gives the same ids.
  - **Fast-forward check:** fetch the remote branch and check that it's an ancestor of `split/<sid>`. It should be, because the subtree was added without squash on top of the remote's history plus the unpushed commits.
  - **Report:** `data/state/repos/preflight-<date>.md`. Per mod it gives:
    - the commits to push: count, first and last, every subject
    - every tracked file over 50 MB
    - matches of a secrets scan over the files and the diff: `sk-…`, `AKIA…`, `ghp_…`, `-----BEGIN … KEY`, `.env`-shaped `KEY=value` lines with long values
    - absolute home paths (`/home/<user>/`)
    - whether the push is a fast-forward
  - **Nothing is pushed here.**
  *Done when:* `utils/tests/repos/test_preflight.py` covers fast-forward vs diverged, a planted fake key, a planted absolute path and a large file, using a temp repo and a bare "remote"; the real report for the four mods is written and shown to the user.
- [x] **1.3 Push, after the user's approval: `utils/repos_migrate.py push <sid>`.**
  - **Needs:** the user's yes per mod, after reading 1.2's report. Relay and LocalTTS are public.
  - **What:** `git push <url> split/<sid>:<branch>`, never forced, then `git ls-remote` to confirm the branch head equals the split head. Anything the scan found is fixed by a GAIFA commit and 1.2 is run again, never by editing the split.
  *Done when:* each repository's branch head on GitHub equals `split/<sid>`; the old clones are untouched (their `git status` is unchanged).
  - **Done 2026-10-26** (the user approved all four): Relay `main` → `4716ca0`, LLMs `master` → `373047d`, LocalTTS `main` → `c7eca45`, 3DGenerate `main` → `823d8cd`.

**Checks & deliverables — Phase 1**
- [x] Each repository's GitHub page shows the GAIFA-era commits on top of its September history.
- [ ] Delivered: the four `.gitignore` files, `utils/repos_migrate.py`, the preflight report, tests.

## Phase 2 — Submodules in place (M)

- [x] **2.1 Convert one folder without touching its files: `utils/repos_migrate.py adopt <sid>` (`utils/repos_adopt.py`).**
  - **Before:** a snapshot of the folder: path, size and mtime of every file, ignored ones included (`.venv`, `runtime/`, `data/`, `.env`), saved in `data/state/repos/adopt-<sid>-before.json`.
  - **Steps:**
    1. `git rm -r --cached services/<sid>`: the index only, files stay.
    2. In the folder: `git init`, `git remote add origin <url>`, `git fetch origin <branch>`, `git reset --mixed origin/<branch>`. The working tree is unchanged and `git status` is clean, because the split from Phase 1 is exactly this folder's tracked content.
    3. GAIFA's commit is built in a private index (the folder's files out, the gitlink and the `.gitmodules` entry with `branch` in), the way `git submodule add -b <branch>` would stage it, because another session may share the index; `main` moves only if it hasn't moved meanwhile, and only these two paths of the shared index and working tree follow. Then `git submodule init` and `git submodule absorbgitdirs services/<sid>`, which moves its `.git` into GAIFA's `.git/modules/`.
  - **After:** compare with the snapshot. Any difference stops the step and prints it.
  - **Running mods:** the files don't change, so a running mod keeps running; `gaifa check <sid>` runs at the end.
  - **Refuses:** a folder with uncommitted changes in GAIFA, a remote head that isn't the split head, or a missing snapshot.
  *Done when:* `utils/tests/repos/test_adopt.py` adopts a fixture mod folder with ignored files (a fake `.venv/`, `runtime/`, `.env`), checks the snapshot is identical and `git submodule status` shows it, and covers each refusal.
- [x] **2.2 Adopt the four mods, one at a time.**
  - **Order:** `relay`, `lcpp`, `tts`, `gen3d`. Each is a GAIFA commit that adds `.gitmodules` and the gitlink.
  - **Between mods:** `uv run pytest` and `gaifa check <sid>`; the mod's page loads on the installed hub.
  *Done when:* `git submodule status` lists all four at their branch heads; `gaifa doctor` passes; `uv run pytest` passes; relay still answers a chat through `/v1`.
  - **Done 2026-10-26:** relay `7859329`, lcpp `b64fdf4`, tts `536f937`, gen3d `c1cebfe`; no file changed but the running relay's log; `gaifa check` passes for each (lcpp's running checks skipped: it was stopped); the doctor's one warning is opencode's `OPENCODE_PROJECT_DIR` (as before); `uv run pytest` 1,935 passed.
- [x] **2.3 The hub and tests with a folder that isn't checked out: `utils/services/discovery.py`, `utils/tests/conftest.py`.**
  - **Hub:** an empty `services/<sid>/` with no `service.toml`, the state of a submodule that was never initialized, is skipped by discovery (it already was: `manifest.discover` skips a folder without `service.toml`; now a test pins it) and listed in `GET /api/repos` (3.3) as `not_checked_out`, not reported as a broken manifest.
  - **Tests:** hub tests that read a mod's files are skipped with the reason `services/<sid> isn't checked out: git submodule update --init services/<sid>` when the folder is empty. These are `test_cli_setup*.py`, `test_backup.py`, `test_setupdocs.py`, `test_setup_block.py`, `test_idle_unload.py`, `test_gpu_slot.py`, `gen3d-chat.test.mjs`, `tts-chat.test.mjs`, `mod-status-cards.test.mjs`, `api.test.mjs` and `settings-search.test.mjs`. Use a shared `needs_mod(sid)` marker in `conftest.py`, and the same check in the Node tests' helper.
  *Done when:* `utils/tests/core/test_uninitialized_mod.py` covers discovery and the marker, and with `services/gen3d` moved aside in a temp copy the suite passes with those tests skipped.

**Checks & deliverables — Phase 2**
- [x] Every mod runs as before; `gaifa backup` still includes the four mods' `.env` and state files (2026-10-26: relay's `.env` and the mods' `data/state/*` files are in the archive; adoption snapshots are removed after a successful adoption).
- [x] Delivered: `.gitmodules`, the four gitlinks, the adopt tool, the discovery test, the test marker; docs: architecture §3 and §10 (each of the four is a submodule of its repository), `docs/structure.md`.

## Phase 3 — Keeping them up to date (L)

- [x] **3.1 Each repository's state: `utils/repos.py`.**
  - **Library:** standard library only (the CLI imports it); it runs `git` with `subprocess`, `-C <folder>`, `GIT_TERMINAL_PROMPT=0` and a timeout.
  - **`repo_state(root, sid) -> RepoState`:** `{id, path, url, branch, pinned` (the gitlink in GAIFA's `HEAD`)`, staged_pin` (in the index, if different)`, head, on_branch` (branch name or null when detached)`, dirty` (tracked changes)`, untracked` (count)`, ahead, behind` (vs `origin/<branch>` from the last fetch)`, unpushed` (commits on `head` that are on no remote branch)`, pinned_on_remote, checkout_vs_pin` (`same|ahead|behind|diverged`)`, last_fetch_ts, initialized, problems: [Problem]}`.
  - **`Problem` = `{code, level, title, detail, fix}`.** The codes, with their levels:

    | Code | Level |
    | --- | --- |
    | `not_checked_out` | error |
    | `dirty` | warn |
    | `unpushed` | warn |
    | `pin_not_on_remote` | warn |
    | `checkout_behind_pin` | warn (GAIFA was pulled, the submodule wasn't) |
    | `checkout_ahead_of_pin` | info (you committed in the mod and haven't pinned it) |
    | `diverged` | error |
    | `updates_available` | info |
    | `fetch_failed` | info, with the git message: offline, no access, renamed repository |
    | `wrong_remote` | warn (origin isn't the `.gitmodules` URL) |
    | `untracked` | warn (untracked files in the mod: new files, or a missing ignore rule; 1.1's check no longer applies once it's a submodule) |
    | `git_error` | error (git itself failed on the folder) |

  - **`list_states(root)`** reads `.gitmodules` for the mods, and `fetch(root, sid)` fetches the branch only.
  *Done when:* `utils/tests/repos/test_repo_state.py` builds GAIFA-like temp repos with a bare remote per mod and covers every problem code, a detached head at the pin (no problem), a fetch with no network (an unreachable URL gives `fetch_failed`, never an exception), a remote branch renamed (`fetch_failed` naming the branch) and a missing `.gitmodules` (an empty list).
- [x] **3.2 `gaifa repos`: `utils/cli_repos.py`, `utils/repos_update.py`, `utils/cli.py`.**
  - **`gaifa repos [status] [--json]`:** one line per mod (pin, checkout, branch, ahead/behind, problems) and exit code 1 when any warn or error. `gaifa repos fetch [<sid>|all]`.
  - **`gaifa repos update <sid>|all [--to <rev>] [--dry-run] [--commit]`:**
    1. **Refuses:** `dirty`, `unpushed`, `diverged`, `not_checked_out`, a mod busy with jobs (its status shows running jobs; `--force-busy` overrides), and a second update running (a lock in `data/state/repos/update.lock`).
    2. Fetch, then check out `origin/<branch>` (or `--to`) detached.
    3. When `uv.lock`, `pyproject.toml`, `requirements*.txt`, `package-lock.json` or the install script changed between the pins, run the mod's install (`run_install`).
    4. `gaifa check <sid>`, and a restart if it was running (through the hub when it's up).
    5. **Any failure** checks out the old pin again, reinstalls if needed, restarts, and reports what failed.
    6. **On success:** stage the gitlink (`git add services/<sid>`) and print the commits it brought in. `--commit` also runs `uv run pytest` and commits `GAIFA (repos): <sid> → <short> (<n> commits)` when it passes.
  - **`gaifa repos pin <sid>`:** records the checkout as the pin (after you committed and pushed in the mod). It refuses `unpushed` and `dirty`.
  - **`gaifa repos sync [<sid>|all]`:** `git submodule update --init` for mods whose checkout is behind the pin, after a GAIFA pull. It refuses `dirty`, and a checkout ahead of or split from the pin.
  - **One flow:** `utils/repos_update.py` holds update, pin and sync; how to install, restart, check, test and whether the mod is busy come in as `Hooks` (the CLI's go through the hub's HTTP API, 3.3's are the hub's own). With the hub down, an update still moves and installs and says it couldn't check.
  - **Why `repos` and not `mods`:** `gaifa models` already exists, and `mods`/`models` are one letter apart.
  *Done when:* `utils/tests/repos/test_cli_repos.py` covers status output and exit codes, an update that fast-forwards, an update whose `gaifa check` fails and rolls back (a fixture mod whose new commit breaks its manifest), a dependency change that runs the install, each refusal, the lock, `pin` and `sync`.
- [x] **3.3 The hub watches them: `utils/repos_watch.py`, `utils/routes/repos.py`, `utils/config.py`, `config.example.toml`.**
  - **Settings (`[repos]`):** `fetch_every_h = 24` (0 = never contact GitHub), `notify = "warnings"` (`all` also shows `updates_available` and `checkout_ahead_of_pin`; `off`), `check_on_start = true`.
  - **Watcher:** a lifespan task, started in the §5 order, never at import. It computes states at start and after each fetch, and on `POST /api/repos/fetch`. It raises and clears alerts through `hub.alerts` with ids `repos.<sid>.<code>`, so a fixed problem's alert goes away. Alerts are warn or error only (brief `Alert`): warnings and errors keep their level; info problems are alerts (as warn) only with `notify = "all"`, and new commits on a branch go to the activity log once either way. The text carries the fix.
  - **Manifests:** after a checkout (and after a rollback) the hub reads the mod's manifest again (`rescan`, a `reload` hook) before the restart and the check, so `gaifa check` sees the new `service.toml`.
  - **Routes:**
    - `GET /api/repos`: states plus `last_fetch_ts` and the settings.
    - `POST /api/repos/fetch`.
    - `POST /api/repos/{sid}/update {to?}`: the 3.2 flow as an operation (`utils/operations.py`) with progress events, 409 `repo_refused` with the problem codes.
    - `POST /api/repos/{sid}/pin`.
    - Errors use the envelope.
  *Done when:* `utils/tests/repos/test_repos_routes.py` and `test_repos_alerts.py` (temp repos, a fake clock) cover alerts raised and cleared per code, `notify` levels, `fetch_every_h = 0` never fetching, an update through the route with its progress and its rollback, and 409s; the contract test covers the new routes; architecture §6 and brief §6 list them.
- [x] **3.4 The doctor: `utils/doctor.py`.**
  - **What:** a `repos` area with one `check(...)` per problem, the same title and fix text as the alerts, shown in `gaifa doctor` and Settings → About.
  *Done when:* `utils/tests/core/test_doctor.py` covers a `dirty` and a `not_checked_out` mod.
- [x] **3.5 Settings → Services → Repositories: `web/settings/schema.js`, `web/settings/blocks-repos.js`, `web/settings/repos-view.js`.**
  - **Group:** "Repositories", with summary "4 repositories · 1 update · 1 warning".
  - **Per mod:** the repository (linked), branch, pinned and checked-out commits, ahead/behind, the problem badges with their fix, and Update / Pin / Fetch buttons. Update shows the incoming commits first (`GET /api/repos/{id}/incoming`, a dry run) and the operation's progress after.
  - **The API:** `GET/PUT /api/settings` carry `repos` (`Settings.repos`), and `api.js` gains the repos methods (area and event `repos`).
  - **Settings rows:** the `[repos]` keys, each with its `config.toml` key, default and Reset like every row.
  - **Overview:** shows the alerts as it shows others.
  *Done when:* `utils/tests/web/settings-repos.test.mjs` covers the summary, badges per state and the update confirmation; on a second hub (`--dev --demo-mods`, temp repos) each state draws, and the settings search finds "repositories", "submodule" and "update".

**Wire — Phase 3:** Settings → Services → Repositories goes live; Overview's alerts include the repositories'.

**Checks & deliverables — Phase 3**
- [ ] On the installed hub: a commit pushed to Relay from another clone shows as "1 update" after Fetch, Update brings it in, the relay restarts, and the pin is staged.
- [ ] Delivered: `utils/repos.py`, `utils/repos_watch.py`, `utils/cli_repos.py`, `utils/routes/repos.py`, `web/settings/blocks-repos.js`, tests.

## Phase 4 — The workflow, written down and tested end to end (M)

- [x] **4.1 Docs: [docs/mods.md](../mods.md) §10 "Mods with their own repository", architecture §12.**
  - **Day to day:**
    - Branch and commit in the mod: `cd services/<sid>` or `git -C`. A worktree of the mod goes outside GAIFA.
    - Run the mod's own tests.
    - Push to its repository.
    - In GAIFA: `gaifa repos pin <sid>`, `uv run pytest`, commit the pin.
  - **Pulling GAIFA:** then `gaifa repos sync`.
  - **Making another mod a submodule:** Phase 1–2's steps with the tools.
  - **What never to do:**
    - `git clean -x` anywhere, submodules included.
    - `git submodule update` over a dirty checkout.
    - A force push to a mod's branch.
    - Committing GAIFA with a pin that isn't pushed.
  - **Edge cases:**
    - A GAIFA worktree has empty mod folders until `git submodule update --init`, and even then it has no venvs or `runtime/`. Run mods from the main checkout, and edit a mod in a worktree of the mod's own repository.
    - Two sessions editing one mod: use a mod branch each.
    - The relay running while its code changes: it reloads only on restart.
  *Done when:* `gaifa docs --check --strict` passes and the doc's commands are the ones 3.2 built.
- [x] **4.2 Project instructions and skills: `CLAUDE.md`, `AGENTS.md`, `.claude/skills/gaifa/SKILL.md`, `.claude/skills/gaifa-mod/SKILL.md`, the root `README.md`.**
  - **Rules:** commit in the mod first, then the pin, with tests passing in both; check `gaifa repos status` before committing GAIFA; where the four repositories are.
  - **Clone:** a clone needs `--recurse-submodules` (or `gaifa setup` does it, 4.3).
  *Done when:* the rules appear in each file and agree with docs/mods.md §10.
- [ ] **4.3 Setup on a fresh clone: `utils/cli_setup*.py`, `docs/setup/README.md`, each of the four mods' `setup/*.md`.**
  - **What:** `gaifa setup [<mod>…]` runs `git submodule update --init services/<sid>` for the chosen mods that are submodules. `--plan` lists it. A clone failure (no SSH key, no access to a private repository) stops that mod with the git message and the fix ("add an SSH key with access to brendondgr/LLMs, or skip lcpp"). `gaifa report` records it.
  *Done when:* `utils/tests/core/test_cli_setup.py` covers the init step in the plan, a failing clone (a bad URL) and skipping it; a fresh `git clone` of GAIFA into the scratchpad (no `--recurse-submodules`), `gaifa setup relay --plan` and then `gaifa setup relay` with the hub's port changed reach a passing `gaifa check relay` and stop there, without touching the installed hub.

**Checks & deliverables — Phase 4**
- [ ] An end-to-end run on this machine:
  1. Make a commit on a branch in `services/relay`, run Relay's tests and push the branch.
  2. Merge it on GitHub (or push `main`).
  3. Fetch: Settings shows the update.
  4. Update: relay restarts, `gaifa check relay` passes.
  5. The pin is committed, and `gaifa repos status` is clean.
- [ ] Each edge case in 3.1's table seen once on real repositories (made and undone): a dirty file, an unpushed commit, a pin behind after `git checkout` of an older GAIFA commit, the network off during a fetch.
- [ ] Delivered: docs, skills, setup changes.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Ignore rules | each mod ignores its own venv, runtime, secrets and machine files | `services/{relay,lcpp,tts,gen3d}/.gitignore` |
| Migration tool | split, preflight report, push, adopt in place with a snapshot check | `utils/repos_migrate.py` |
| Submodules | the four mods at their repositories' branch heads | `.gitmodules`, `services/{relay,lcpp,tts,gen3d}` |
| Repository state | pin, checkout, ahead/behind, problems with fixes | `utils/repos.py` |
| CLI | `gaifa repos status / fetch / update / pin / sync` | `utils/cli_repos.py` |
| Watcher and routes | daily fetch, alerts raised and cleared, `/api/repos*` | `utils/repos_watch.py`, `utils/routes/repos.py` |
| Settings | Services → Repositories, `[repos]` rows | `web/settings/blocks-repos.js`, `web/settings/schema.js` |
| Doctor | a `repos` area | `utils/doctor.py` |
| Docs | the workflow, the edge cases, setup on a fresh clone | `docs/mods.md` §10, architecture §3/§6/§10/§12, `docs/setup/README.md`, `CLAUDE.md`, `AGENTS.md`, skills |
| Tests | temp repos with bare remotes, every problem code, update with rollback, routes, alerts, UI | `utils/tests/repos/`, `utils/tests/core/test_uninitialized_mod.py`, `utils/tests/web/settings-repos.test.mjs` |
