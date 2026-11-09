# Plan: scheduled tasks: chats that run on their own, on a schedule, gated by the judge

**Asked for:** 2026-11-09 · **Status:** In progress

## 1. Introduction

GAIFA's chats only run when someone types. A **scheduled task** starts a chat on its own, after Claude's scheduled tasks:
- hourly, daily, on weekdays, weekly or monthly, at a time you set;
- with a name, detailed instructions, skills that are always on, a model and a mode;
- in folders of its own, or in a project's;
- in the background, with no one watching, so every tool call is decided without a card.

A task stands alone or is attached to a project. An attached task runs in the project's context: its instructions, folders (and the instruction files in them), skills and memory. Each run is a new chat that never sees the runs before it. A run may keep short **notes on how to do the task** (where things are, what worked), which later runs read.

Unattended calls go through three gates, in order:
1. the task's **pre-allows** (tools, sites, MCP servers), written as grants for the run's chat;
2. the hub's rules;
3. the Auto judge, the decide mod's d3-lite.

What would have been a card is **refused**, with the reason, and the run goes on without it. Four safeguards keep this honest:
- a **test run** you watch, whose approvals can become pre-allows;
- a **check on save** (screened instructions; the model, skills, tools, servers and folders must exist);
- a **judge health check** before each run;
- a **judgement log** on every run, plus eval cases for unattended runs.

Where things live:
- **The agent mod** owns tasks (`services/agent/agent/tasks/`, `/v1/tasks`, tables in `agent.db`). Its scheduler loop is like the learner's (`learn/schedule.py`). Runs are threads with `settings.task`.
- **The hub** gains `origin.unattended` (ask → refused) and `POST /api/grants` for a chat's grants.
- **Folders** stay in the workspace mod. A task's own folders sit in a hidden environment, as a project's do.
- **The Chat page** gets a **Scheduled** row under Projects, the tasks grid (`#/chat/tasks`), a task's page (`#/chat/tasks/<id>`) and a Scheduled panel on the project page.

Touches architecture §14.1 (the agent's routes), §14.7 (permissions, grants, the judge), the brief §11.13 (the Chat page), and the plans [projects](projects.md) (the model for all of this), [web-approvals](web-approvals.md) (the judge and grants), [structured-memory](structured-memory.md) and [memory-auto-learning](memory-auto-learning.md) (what runs read and never learn), [chat-history](chat-history.md) (the sidebar), and backend-plan 30.3–30.6 (the Auto judge and its eval).

## 2. Gaps & unanswered questions

Answered by the user on 2026-11-09:
- **Approvals in a run:** pre-allows first, then the judge. Whatever the judge isn't sure of is **refused and the run continues**; the run lists what was refused. All four safeguards are in the first version.
- **Projects:** a task can stand alone or be attached to a project, and then runs in the project's context. Its schedule is set on the project's page too. A project may have several tasks.
- **Runs:** each run is a fresh chat with only the instructions; no summary of the previous run.
- **Memory:** runs read your profile and, in a project, the project's memory. Each task has **Use profile** and **Use project memory** switches, both on by default. Runs may write **notes on how to do the task**, so later runs are quicker (the user's ask); they never learn facts about you.
- **Modes:** Plan, Accept edits, Auto and Bypass. Bypass skips the judge, so only the folders' levels limit it; the task shows a warning.
- **Missed runs:** when the hub comes back, the latest missed run runs once, marked late. Older misses aren't run.
- **Notifications:** in the app only: unread dots on runs and the Scheduled row, each task's last status, and a run's last message as its summary.
- **Waiting:** a run doesn't wait because you're chatting. It starts on time, and its model calls queue in the hub's GPU queue like any chat's, so it waits only as long as the GPU needs.
- **Hourly:** every N hours at minute MM, with an optional window (e.g. 08:00–18:00) and an optional weekdays-only switch.
- **A finished run is a normal chat:** you can reply in it, and from then on it's interactive, with cards.
- **History:** every run is kept; runs older than 30 days (per task) are archived, never deleted.
- **Pre-allows** name tools (or globs), sites (or every site) and MCP servers. Folder access stays with the folder levels.

Assumed:
- **Ids:** tasks are `k_<10 hex>`. Thread ids start with `t_`, projects with `p_`, and a task id goes in URLs next to both. Runs are `r_<10 hex>`, notes `n_<10 hex>`.
- **Time:** the machine's local time. A monthly task on the 29th–31st runs on the month's last day when the month is shorter. A daylight-saving gap moves a run to the next valid minute, and a repeated hour runs once.
- **Overlap:** a task whose last run is still going skips the new one (state `skipped`, why `still running`).
- **Parallel runs:** at most 2 runs at once across tasks (`AGENT_TASKS_PARALLEL`). More wait in a queue. A run that waited more than 60 minutes is `skipped` (why `busy`).
- **Missed runs:** "missed" means due more than 2 minutes before the scheduler saw it (a hub that was down). The late run's note says how many earlier ones were missed.
- **`ask_user` in a run:** answered at once with "no one is here to answer; decide, and say what you assumed". `show` and the other local tools work as in a chat.
- **Learning:** runs carry `no_learn` (no preference mining) and the memory learner skips them. `remember` in a run is decided like any call (in Auto, the judge; unattended, refused unless pre-allowed). The task's notes are the run's way to keep what it learned about the work.
- **Notes:** at most 20 per task, 500 characters each, read in the prompt under "How to do this task (notes from earlier runs)". The `task_note` tool (local, only in task runs) adds, replaces or removes one. You can edit and delete them on the task's page.
- **The first message** of a run is the task's instructions, as a user event with `by: "schedule"`. The judge reads it as the user's words: you wrote it. A note from the app says the run is unattended and when it was due.
- **The run's title** is `<task name> · <Mon 10 Nov 07:00>`.
- **Folders:** a task has its own folders in a hidden environment (the workspace mod's `project` field carries the task id; the field only hides). A standalone task uses only those (or Default when it has none). A project task uses the project's folders plus its own, or **only its own** when the task's switch says so. That is how a task is kept to one directory.
- **Model:** the task's model, else the project's default, else the agent's default. A cloud model is allowed (a run is a chat).
- **The judge health check:** in Auto, the run asks `GET /api/judge/status` first. When the judge isn't available, the run still starts. A note says only pre-allowed calls will run, and everything else is refused (the judge fails closed). The run's row says `judge: unavailable`.
- **Unread:** a run is unread until its chat is opened (the pane marks it seen). The Scheduled row shows a dot while any run is unread.
- **Deleting a task:** its runs stay as ordinary chats (`settings.task` cleared), its hidden environment and grants go, and the confirm dialog says so. Deleting a project detaches its tasks, which become standalone and are switched off until you look at them.
- **Turning a task off** keeps its history; turning it on computes the next due time from now (no catch-up).
- **Settings → Agent** gets no new section. Limits are environment variables of the agent mod, like its others.

**Needs a human answer:** none.

## Phase 1 — Tasks in the agent (M)

- [x] **1.1 When: `services/agent/agent/tasks/when.py` (new).**
  - **Schedule shape:**
    - `{kind: "hourly", every: 1–24, minute: 0–59, from?: "HH:MM", to?: "HH:MM", weekdays?: bool}`
    - `{kind: "daily" | "weekdays", time: "HH:MM"}`
    - `{kind: "weekly", day: 0–6 (Mon = 0), time}`
    - `{kind: "monthly", day: 1–31, time}`
  - **Functions:**
    - `check(schedule) -> list[str]`: the problems;
    - `next_after(schedule, t) -> float`: local time, last-day rule, DST;
    - `describe(schedule) -> str`, e.g. "Weekdays at 07:00", "Every 2 hours at :15, 08:00–18:00";
    - `missed(schedule, last_due, now) -> int`.
  *Done when:* `services/agent/tests/test_task_when.py` covers each kind, the window and weekdays for hourly, the 31st in February, a DST change (`TZ` set in the test), `describe`, and `missed`.
- [x] **1.2 The store: `tasks/__init__.py`, `tasks/store.py` (new).**
  - **Tables in `agent.db`:**
    - `tasks(id, name, instructions, project_id, schedule JSON, enabled, model, mode, skills JSON, allow JSON, settings JSON, own_env, only_own, use_profile, use_project_memory, keep_days, next_due, created, updated)`;
    - `task_runs(id, task_id, thread_id, due, started, ended, state 'queued'|'running'|'done'|'failed'|'skipped', why, late, test, refused, judge, seen)`;
    - `task_notes(id, task_id, text, thread_id, added, updated)`.
  - **Shapes:** `allow` is `{tools: [globs], sites: [hosts | "*"], mcp: [servers]}`. `settings` holds the chat's tool groups (`disabled`, `pinned`, `mcp_on`).
  - **`TaskStore`:** `create`, `get`, `list(q, project)`, `update`, `delete`, `runs(task, limit, before)`, `add_run`, `update_run`, `run_of_thread`, `unread()`, `notes`, `add_note`, `update_note`, `remove_note`. Instructions are up to 16 000 characters.
  - **Thread link:** `threads.settings.task` names the task. `Store.threads(task=…)` filters by it.
  *Done when:* `services/agent/tests/test_tasks_store.py` covers CRUD, runs in order, unread, notes with their limit, and the thread filter.
- [x] **1.3 Routes: `services/agent/agent/api_tasks.py` (new), `server.py`.**
  - **Tasks:** `GET/POST /v1/tasks` (`?project=`), `GET/PATCH/DELETE /v1/tasks/{kid}`. A body's schedule is checked (`422 invalid_schedule`). `next_due` is recomputed when the schedule changes or the task is turned on.
  - **Runs:** `GET /v1/tasks/{kid}/runs`, `PATCH /v1/tasks/{kid}/runs/{rid}` (`seen`), `GET /v1/tasks/unread` (`{count, tasks: {kid: n}}`).
  - **Notes:** `GET/POST /v1/tasks/{kid}/notes`, `PATCH/DELETE …/notes/{nid}`.
  - **Events:** each change publishes `{type: "task", id, task}` (and `task_run`) to the streams opened with `watch=tasks` (as `watch=projects`, `streams.py`).
  - **Delete:** clears `settings.task` from its runs' chats and removes its hidden environment (Phase 2).
  *Done when:* `services/agent/tests/test_tasks_api.py` covers CRUD, a bad schedule, `next_due`, runs and unread, notes, the events, and delete leaving ordinary chats.

  Update architecture §14.1.
  *As built:* the store is `agent.scheduled` (`agent.tasks` already holds the running turns). The folder routes (`/v1/tasks/{id}/folders`) landed here, with `projects/folders.py` generalised to an owner kind (`task-<hex>`, "<task> (scheduled)"). Deleting a project detaches its tasks through `project_cleanup` (first in the list). `watch=tasks` and `watch=projects` both get every event that belongs to no chat.

**Checks & deliverables — Phase 1**
- [x] `services/agent/tests` and `uv run pytest` are green.
- [x] Delivered: `tasks/when.py`, `tasks/store.py`, `api_tasks.py`, the changed `store.py`, `server.py`, `streams.py`, and tests.

## Phase 2 — Running unattended (L)

- [x] **2.1 The hub: `utils/tools/calls.py`, `utils/routes/tools.py`, `utils/tools/grants.py`.**
  - **`origin.unattended`:** a call whose verdict would be `ask` is refused: `{status: "denied", error: {code: "unattended", detail: "<tool>: <why>; no one is here to approve it", fix}}`, with `judge` when the judge decided. It's recorded in `judged` with verdict `refused` (Settings → Permissions shows it) and in the refused calls. Plan mode's and the preflights' refusals are unchanged.
  - **`POST /api/grants`:** `{tool, key?, kind?, thread, note?}` writes a `thread` grant (never `always`; `422` without a thread). Tool globs are allowed. `kind: "url:any"` with key `*` is every site, which keeps the judge's URL rules.
  - **Records:** a call a grant ran answers with `grant` (its id), so the run's log can say "pre-allowed".
  *Done when:* `utils/tests/tools/test_unattended.py` covers an ask refused, a grant still allowing, a judged call refused with its verdict recorded, `POST /api/grants` (thread only, globs, every site under the URL rules), and `grant` in the answer.

  Update architecture §14.7.
- [x] **2.2 The runner: `tasks/runner.py` (new), `hubapi.py`.**
  - **`Runner.start(task, why, due, late=0, test=False) -> run`:**
    - makes the chat: title, model, mode, settings `{task, task_run, project?, unattended: not test, no_learn: true, disabled, pinned, mcp_on, task_env?, task_only?, use_profile, use_project_memory}`;
    - writes the pre-allows as the chat's grants (`hubapi.add_grant`);
    - in Auto, checks the judge (`GET /api/judge/status`) and notes the answer;
    - sends the instructions as the first message (`by: "schedule"`).
  - **The run's end:** an `on_turn_end` hook finishes the run row:
    - `done`, or `failed` on an error;
    - `refused`: the count of `unattended` refusals;
    - `seen: false`.
    A test run ends like any chat (it may wait on a card).
  - **Limits:** parallel runs, the queue, and skipped when still running or busy (§2).
  - **Folders:** `projects/origin.chat_envs` reads `task_env` and `task_only`. The task's own folders are created through the workspace mod as a project's are (`projects/folders.py`, generalised to an owner).
  *Done when:* `services/agent/tests/test_task_runner.py` (hub and model faked) covers:
    - a run's chat settings, grants and first message;
    - Auto with the judge down (a note, the row's `judge`);
    - a refused call counted;
    - an overlapping run skipped and the queue;
    - a project task's environments and `task_only`.
- [x] **2.3 The scheduler: `tasks/schedule.py` (new), `server.py`.**
  - **The loop:** a check every 30 s starts due tasks and advances `next_due`.
  - **Start-up:** a task due more than 2 minutes ago runs once, `late`, with the count of missed runs.
  - **Upkeep:** daily, run chats older than their task's `keep_days` are archived.
  - **Routes:** `POST /v1/tasks/{kid}/run` (Run now) and `POST /v1/tasks/{kid}/test` (a test run, Phase 3).
  *Done when:* `services/agent/tests/test_task_schedule.py` (a fake clock) covers due, not due, a missed run once on start-up with its count, a turned-off task, Run now, and archiving.
- [x] **2.4 The run's prompt and tools: `prompting.py`, `prompts.py`, `local.py`, `memory/learn.py`, `tasks/notes.py` (new).**
  - **The prompt's Scheduled task note:** the task's name, that no one is watching, that refused calls are to be worked around and reported, that `ask_user` can't be answered, and to end with a short summary (done, refused, left open). Then the task's notes.
  - **`task_note`:** a local tool, in task runs only: `{action: add | replace | remove, id?, text}`.
  - **`ask_user` in an unattended run:** answered at once (§2).
  - **The memory switches:** `use_profile: false` leaves the user's facts out of the profile and recall. `use_project_memory: false` leaves the project's out.
  - **The memory learner** skips task chats.
  *Done when:* `services/agent/tests/test_task_prompt.py` covers the note and the notes in the prompt, `task_note` (limits), `ask_user` unattended, each memory switch, and the learner skipping a run.
  *As built (2.2–2.4):* the agent's calls carry `origin.unattended` from the run chat's settings (`loop.py`), and `grant_id` rides on a call's `call` and `tool_result` events. `projects/knowledge.project_skills` takes a label, so a task's skills are always on the same way. The memory learner already skips `no_learn` chats, which every run is; the switches are `profile.build`/`recall`'s `user` and `own_project`. A run's `refused` also counts an `ask_user` answered with `unattended`.

**Checks & deliverables — Phase 2**
- [x] On a second hub (port 7078, the remote test LLM): a task made through the API runs on Run now. A pre-allowed call runs, and an un-allowed write in Auto is refused and counted. The run's chat reads as a chat.
  *As built (2026-11-09, port 7078 from the worktree, the agent on port 5190):* the remote test LLM at localhost:9090 was down and this machine's GPU wasn't to be used without asking, so the agent's model was a scripted server (the tests' `FakeModel` on its own port); the hub, the agent process, grants, the judge's status (the installed decide mod: `ok`) and HTTP were real. Task A pre-allowing `agent_memory_save`: its run's `remember` ran through the grant (`grant_id` on the result), the run `done`, `refused` 0. Task B without it: the same call was refused (`unattended`, no card, no pending approval), the run `done` with `refused` 1. A daily task set a minute ahead started on its own 19 s after its time, and its `next_due` moved to the next day. A reply in B's finished run got an answer, and the run stayed `done`. Both runs were unread. The check with a real model is Phase 5's.
- [x] Delivered: the hub's `calls.py`, `grants.py` and `routes/tools.py`, `tasks/runner.py`, `tasks/schedule.py`, `tasks/notes.py`, the changed prompt, local tools and origin, and tests.

## Phase 3 — Safeguards (M)

- [ ] **3.1 Check on save: `tasks/check.py` (new), `api_tasks.py`.**
  - **`check(task) -> {problems: [{field, detail, fix}], warnings: [...]}`:**
    - the instructions screened (`POST /api/screen`), a flag being a problem;
    - the model served by the relay;
    - each skill found (the agent's own and the folders');
    - each pre-allowed tool glob matching a catalog tool (`/api/tools/index`);
    - each MCP server known (the mcp mod);
    - each folder present;
    - warnings: Bypass, and pre-allowed `execute`/`destructive` tools.
  - **Routes:** `POST /v1/tasks/{kid}/check`. Turning a task on, or Run now, with problems answers `409 task_problems` with them.
  *Done when:* `services/agent/tests/test_task_check.py` covers each problem and warning and the 409.
- [ ] **3.2 Test run and suggested pre-allows: `api_tasks.py`, `tasks/runner.py`.**
  - **Test run:** `POST /v1/tasks/{kid}/test` starts a run with `test: true`: not unattended, so cards appear.
  - **Suggestions:** `GET /v1/tasks/{kid}/runs/{rid}/allows` lists the run's approved calls as suggested pre-allows (a tool; a site for a `url:host` tool; a server for an `mcp_` tool), leaving out what's already allowed.
  - **Adding:** `POST /v1/tasks/{kid}/allow` adds entries.
  *Done when:* `test_tasks_api.py` covers a test run's settings, the suggestions from approved and denied cards, and adding them.
- [ ] **3.3 The judgement log: `tasks/log.py` (new), `api_tasks.py`.**
  - **Route:** `GET /v1/tasks/{kid}/runs/{rid}/log` lists, per tool call of the run in order: tool, a short summary, `allowed | refused | denied | asked`, `by` (`pre-allow`, `rules`, `judge`, `mode`, `you`), and the reason.
  - **Sources:** the chat's events and the hub's `GET /api/judge/recent?thread=`.
  *Done when:* `services/agent/tests/test_task_log.py` covers each `by` and refused calls.
- [ ] **3.4 Judge eval cases for unattended runs: `services/agent/evals/judge/scheduled.py` (new), `bench.py`, `run.py`.**
  - **Cases:** about 30, each the task's instructions as the user's words with one call:
    - routine work the instructions ask for (allow);
    - writes outside what they ask, shell commands they don't name, and pages fetched from untrusted text (ask, so refused).
  - **The runner:** `--source scheduled` runs only them.
  *Done when:* `test_evals.py` checks the cases load. A live run of d3-lite over them is recorded in `docs/agent-eval.md`, with how many routine calls would have been refused.

**Checks & deliverables — Phase 3**
- [ ] On the second hub: a task with a missing skill can't be turned on; a test run shows a card, and its approval becomes a pre-allow; the next run's log says `pre-allow`.
- [ ] Delivered: `tasks/check.py`, `tasks/log.py`, `evals/judge/scheduled.py`, and tests.

## Phase 4 — The Scheduled UI (L)

- [ ] **4.1 Client and mock: `web/chat/chat-api.js`, `chat-mock-tasks.js` (new).**
  - **Client calls:** `c.tasks`, `c.task`, `c.createTask`, `c.patchTask`, `c.deleteTask`, `c.taskRuns`, `c.seeRun`, `c.tasksUnread`, `c.runTask`, `c.testTask`, `c.checkTask`, `c.taskNotes` with add, patch and remove, `c.runAllows`, `c.addAllows`, `c.runLog`, and `c.watchTasks`.
  - **The mock:** two tasks (one in a project), with runs, notes and a log.
  *Done when:* `utils/tests/web/chat-tasks.test.mjs` covers the calls on the mock.
- [ ] **4.2 The Scheduled row and routes: `chat-tasks.js` (new), `chat.js`.**
  - **The row:** **Scheduled** under Projects, an accordion like Projects. It folds open to the tasks (on first, then by next run, up to 8, then All scheduled · N), each with its next time and an unread dot. Open or folded is kept on the hub as `hub.chat.tasks.open`.
  - **Routes:** `#/chat/tasks` (the grid) and `#/chat/tasks/<id>` (a task).
  *Done when:* `chat-tasks.test.mjs` covers the row's order and dots, and the routes.
- [ ] **4.3 The grid and the editor: `chat-tasks.js`, `chat-task-edit.js` (new).**
  - **The grid:** cards with the name, the schedule in words, the next run, the last status, a project chip and an on/off switch. Search; New task.
  - **The editor:** name; instructions; the schedule picker (Hourly / Daily / Weekdays / Weekly / Monthly with their fields); project; model; mode (Bypass warns); skills; folders (only its own, or the project's too); pre-allows (tools, sites, MCP servers); Use profile; Use project memory; keep days.
  - **Saving:** checks the task and shows its problems and warnings.
  *Done when:* `chat-tasks.test.mjs` covers the schedule picker's output for each kind, the problems shown, and the Bypass warning.
- [ ] **4.4 The task's page: `chat-task.js` (new), `chat-task-panels.js` (new).**
  - **The page:** a header (name, schedule, next run, switch, Run now, Test run, Edit) and its runs (status, late, refused count, unread; opening one opens its chat).
  - **The side column:** Notes (edit and delete); the selected run's judgement log; suggested pre-allows after a test run, each with Add.
  - **Opening a run's chat** marks it seen.
  *Done when:* `chat-tasks.test.mjs` covers the runs list, seen, the log rows and adding a suggestion.
- [ ] **4.5 The project page's Scheduled panel: `chat-project-panels.js`.** The project's tasks with their next run, and New task (the project preset).
  *Done when:* `chat-project.test.mjs` covers the panel.

  Update the brief §11.13 and `web/PATCHES.md`.

**Wire — Phase 4:** the Chat page's Scheduled row, grid, task page and the project's panel read the live agent.

**Checks & deliverables — Phase 4**
- [ ] In the browser on `?mock`: the row, the grid, the editor, a task's page and the project's panel draw, with no console errors.
- [ ] Delivered: `chat-tasks.js`, `chat-task.js`, `chat-task-edit.js`, `chat-task-panels.js`, `chat-mock-tasks.js`, the changed `chat.js`, `chat-api.js`, `chat-project-panels.js`, and tests.

## Phase 5 — On the installed hub (S)

- [ ] **5.1 The live check.** After `gaifa restart` and restarting the agent mod:
  - a standalone task with a folder of its own runs on a schedule a few minutes ahead;
  - a project task runs in the project's context;
  - a test run's approval becomes a pre-allow;
  - a refused call shows in the log;
  - the unread dot clears when the run is opened.
  The test tasks are deleted and their chats archived. CLAUDE.md's status, the plans index and the structure doc are updated.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Schedules | the shape, next time, words, missed runs | `services/agent/agent/tasks/when.py` |
| Store | tasks, runs, notes | `services/agent/agent/tasks/store.py` |
| Routes | tasks, runs, notes, run, test, check, allows, log | `services/agent/agent/api_tasks.py` |
| Runner and scheduler | unattended runs, limits, missed runs, upkeep | `services/agent/agent/tasks/runner.py`, `tasks/schedule.py` |
| Notes, check, log | how-to notes, check on save, the judgement log | `tasks/notes.py`, `tasks/check.py`, `tasks/log.py` |
| Hub | `origin.unattended`, `POST /api/grants`, `grant` in answers | `utils/tools/calls.py`, `grants.py`, `utils/routes/tools.py` |
| Eval | unattended judge cases | `services/agent/evals/judge/scheduled.py` |
| UI | the Scheduled row, grid, editor, task page, project panel | `web/chat/chat-tasks.js`, `chat-task*.js` |
| Tests | the agent's, the hub's, the web's | `services/agent/tests/test_task*.py`, `utils/tests/tools/test_unattended.py`, `utils/tests/web/chat-tasks.test.mjs` |
