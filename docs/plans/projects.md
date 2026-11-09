# Plan: projects: chats with standing instructions, files, live web pages, folders and their own memory

**Asked for:** 2026-11-08 · **Status:** In progress

## 1. Introduction

Chats in GAIFA share one context. A chat can work in one environment (a named set of workspace folders, backend-plan Phase 34), carry attachments and recall the agent's memory, but nothing gathers the chats about one piece of work around what they all need. A **project** does that, after Claude.ai's projects. A project has a name and a description, plus:
- **instructions** that every one of its chats follows;
- **files** (uploads, or outputs already in GAIFA);
- **web pages**, linked by URL and fetched again when a question needs them fresh;
- **folders**: one or more environments, plus folders of its own;
- **defaults** for its chats: model, mode, tool groups and MCP servers, skills;
- a **project memory** that grows from its chats.

The Chat page's sidebar gets a **Projects** entry under New, which opens the projects page: a grid of project cards with search, sort and pins. A project's page shows a composer for a new chat in the project, its chats in order, and a side column with Instructions, Files, Pages, Memory, Folders and Defaults.

Where things live:
- **The agent mod** (`services/agent`) owns projects. They are chat settings, prompt parts and memory, all of which the agent already holds. They are stored in `agent.db` and served at `/v1/projects`.
- **Files and pages** stay hub outputs (uploads, and the web mod's saved pages via `POST /api/web/read`). The project keeps references to them.
- **Search** over a project's sources uses the embed mod's text collections, one per project.
- **Folders** stay in the workspace mod. A project names environments, and its own folders sit in a hidden environment of its own. A project chat's calls carry every one of those environments in their origin, so levels, grants, limits and skill scanning all keep working.

Touches architecture §14 (the agent: routes §14.1, the event log §14.2, prompt and memory), §4.2 (the workspace mod's origin), the brief §11.13 (the Chat page), and the plans [structured-memory](structured-memory.md) (entities, anchors, recall), [memory-auto-learning](memory-auto-learning.md) (what is saved without asking), [skill-sources](skill-sources.md) (skills from a chat's folders), [chat-uploads-and-fast-presets](chat-uploads-and-fast-presets.md) and backend-plan 24.5/30.8 (documents and pages in chats), and [chat-history](chat-history.md), whose sidebar this plan extends with Group by Project.

## 2. Gaps & unanswered questions

Answered by the user on 2026-11-08:
- **Folders:** a project uses one or more environments and/or folders of its own. *Design:* its own folders live in a hidden environment the workspace mod makes for it (`project: "<pid>"`), so levels and limits work unchanged. The first environment in the project's list is its **primary** one.
- **Where projects are opened:** a **Projects** entry under **New** in the chat sidebar opens the projects page. A chevron beside it opens a dropdown listing the projects (pinned first, then the most recent, up to 8, then "All projects"). There are no organization tabs and no starter templates.
- **Project chats in the history:** shown like any chat. The View menu's Group by gains **Project**: a section per project (5 chats, then Show more, as chat-history does for environments), then a **No project** section. Grouped by environment, a project chat appears under the project's primary environment (its `settings.environment` is kept equal to it). Grouped by date, it appears by date.
- **When pages are fetched again:** only when a chat uses them, never on a schedule. Before each answer in a project chat, the user's message is compared by meaning with the project's pages. Matched pages older than their freshness limit (default 1 h) are fetched again before the model sees them. The agent can also refresh a page with a tool. Pages that no question touches are never fetched again.
- **How sources reach the model:** in full while all of them fit a budget (25 % of the model's window by default). Past that, the prompt lists them, and the agent searches and reads them with project tools.
- **Project memory:** an entity of kind `project` in the structured memory, anchored to the project. Facts from the project's chats are learned with today's rules: grounded, confident and non-sensitive facts are saved with Undo, and the rest go to Review. The project's Memory panel shows and edits them. They are used only in that project's chats. Personal memory applies everywhere, project chats included.
- **Defaults a project sets:** model, mode, tool groups and MCP servers, and skills.
- **Deleting a project:** its chats become ordinary chats, still in history. Its memory entity stays in Memory, where it can be deleted, with its project anchor removed. Its uploaded files stay in Outputs. Only the project record, its instructions, its page links, its embed collection and its hidden environment go. The confirm dialog says all of this.

Assumed:
- **Scheduled tasks** (the screenshot's last panel) are out of scope. A later plan adds them.
- **A chat belongs to at most one project.** A chat can be moved into a project or out of one from its ⋯ menu (**Move to project…**, **Remove from project**). Moving it in applies the project's environment, but not its model or mode: those stay as the chat had them. A new chat started in a project takes all of the project's defaults.
- **Instructions:** plain text (markdown), up to 16 000 characters, in the prompt of every project chat right after AGENT.md. Instruction files in the project's folders (CLAUDE.md, AGENTS.md…) keep working as they do now (skill-sources 2.2).
- **Always-on skills:** each skill's SKILL.md body is put into the prompt of the project's chats, up to 8 000 characters in total (the rest are listed first among the skills, marked "this project uses"). Skills keep their ids (`<folder>:<skill>` or the agent's own).
- **Tool groups and MCP servers:** stored as the thread settings they already are (`disabled`, `pinned`, `mcp_on`) and copied onto each new project chat. The composer's controls still change them per chat.
- **Files:** uploaded on the project page (the hub's `POST /api/outputs/upload`) or picked from Outputs. Removing a file from a project never deletes the output. *Limit:* 200 sources per project.
- **Pages:** added by URL through `POST /api/web/read` (the user asked for it, so there is no approval card, and the whole page is screened as now). Each fetch saves a new hidden output. The project keeps the newest one, and the old ones are left to `[outputs] hidden_keep_days` retention. A page whose fetch fails keeps its last copy and shows the error. In a chat, the agent is told that copy's age. Each page's freshness limit can be changed (15 min, 1 h, 6 h, 1 day, 1 week, or never refresh automatically).
- **Budget:** `project_share` (default 0.25) in the agent's document settings (`data/agent/documents.json`, Settings → Agent → Documents), next to `inline_tokens`. Sizes are counted the way `docs.py` counts them (4 characters per token).
- **Screening:** files and pages go into the prompt inside `<untrusted>`, as attached documents do, and page text uses the screening report `POST /api/web/read` keeps.
- **Embed collection:** `proj-<pid suffix>` in the embed mod's text collections. The agent chunks each source's text (about 3 000 characters with 300 of overlap, page and line kept) and sends the chunks. Hidden page outputs aren't in the embed library (backend-plan 30.9), so this path covers files and pages alike. Without the embed mod, matching falls back to words (BM25 over the chunks, in the agent), and search does too.
- **Ids:** projects are `p_<10 hex>`, sources `src_<10 hex>`.
- **The projects page's sort:** recent activity (default), name, or created. Pins are on top. Search is by name and description.

**Needs a human answer:** none. Every question above was answered on 2026-11-08 or carries an assumption to check during the live run.

## Phase 1 — Projects in the agent (M)

- [x] **1.1 The store: `services/agent/agent/projects/__init__.py`, `projects/store.py` (new).**
  - **Tables in `agent.db`:**
    - `projects(id, name, description, instructions, environments JSON, own_env, defaults JSON, memory_entity, pinned, created, updated)`;
    - `project_sources(id, project_id, kind 'file'|'page', output_id, url, title, max_age_s, fetched, chars, status 'ok'|'fetching'|'error', error, added, position)`.
  - **`defaults`:** `{model, mode, disabled, pinned, mcp_on, skills}`.
  - **`ProjectStore`:** `create`, `get`, `list(q, sort)`, `update`, `delete`, `sources(pid)`, `add_source`, `update_source`, `remove_source`, `reorder`.
  - **Thread link:** `threads.settings.project` names the project. Add `PROJ_OF` beside `ENV_OF` in `store.py`, so `Store.threads(project=[…])` and `Store.groups(by="project")` work. The value `none` means chats without a project.
  *Done when:* `services/agent/tests/test_projects_store.py` covers create, update, list with search and sort, sources added, reordered and removed, the 200-source limit, and thread filters by project (including `none`).
- [x] **1.2 Routes: `services/agent/agent/api_projects.py` (new), `server.py`.**
  - **Projects:** `GET/POST /v1/projects`, `GET/PATCH/DELETE /v1/projects/{pid}`.
  - **Chats:** `GET /v1/projects/{pid}/threads` (the same query as `/v1/threads`). `POST /v1/threads` accepts `settings.project`: a new chat in a project takes the project's defaults (model, mode, `disabled`, `pinned`, `mcp_on`) and its primary environment as `settings.environment`, under anything the request sets itself. `PATCH /v1/threads/{id}` with `settings.project` moves a chat in (environment set, nothing else) or out (`null`: project removed, environment kept).
  - **Delete:** clears `settings.project` from its chats, drops its sources and embed collection (Phase 3), asks the workspace mod to delete its hidden environment (Phase 2), and removes the project anchor from its memory entity (Phase 4). Each step is skipped when its mod is off, and logged.
  - **Primary environment:** when a project's environments change, every one of its chats gets the new primary as `settings.environment` (one `UPDATE`).
  - **Events:** every change publishes `{type: "project", id, project}` on the agent's streams (`streams.py`), so open pages follow it.
  - **Groups:** `GET /v1/threads/groups?by=project` returns `{project, count, updated, running}` (with `none`).
  *Done when:* `services/agent/tests/test_projects_api.py` covers:
    - CRUD;
    - a new chat taking the project's defaults while the request's own settings win;
    - move in and out;
    - groups by project;
    - delete leaving its chats as ordinary chats;
    - the `project` event.

  Update architecture §14.1 (the agent's routes).
  *As built:* `project` events belong to no chat, so they go to the `/v1/streams` connections opened with `watch=projects` (`Live.broadcast`), not to every chat's stream. A project with no environments sets none on its chats: they keep their own. The project's `chats` and `source_count` come with each row. Delete, creation and changes run hook lists on the agent (`project_cleanup`, `project_created`, `project_changed`) that later phases fill.
- [x] **1.3 Client and mock: `web/chat/chat-api.js`, `chat-mock.js`.** `c.projects({q, sort})`, `c.project(pid)`, `c.createProject`, `c.patchProject`, `c.deleteProject`, `c.projectThreads(pid, opts)`, `c.threadGroups({by})`, and for sources `c.addSource`, `c.patchSource`, `c.removeSource`, `c.refreshSource`. The mock keeps two fixture projects, one with files and pages.
  *Done when:* `utils/tests/web/chat.test.mjs` covers the project calls on the mock.
  *As built:* the mock's projects are in `web/chat/chat-mock-projects.js` (chat-mock.js was at 549 lines), spread into the mock client; `c.threads({project})` filters too. The client also has `c.watchProjects(onEvent)` (an EventSource on `/v1/streams?threads=&watch=projects`, see 1.2) and, ahead of 2.3 and 4.2, `c.projectFolders`, `c.addProjectFolder`, `c.patchProjectFolder`, `c.removeProjectFolder`, `c.projectMemory`, `c.patchProjectFact` and `c.forgetProjectFact` (the last two through the existing memory routes).

**Checks & deliverables — Phase 1**
- [x] `services/agent/tests` and `uv run pytest` are green.
- [x] Delivered: `projects/store.py`, `api_projects.py`, the changed `store.py`, `server.py`, `chat-api.js`, `chat-mock.js`, and tests.

## Phase 2 — Folders across environments (M)

- [x] **2.1 Several environments in an origin: `services/workspace/folders.py`, `environments.py`, `api_env.py`.**
  - **Origin:** `X-GAIFA-Origin` may carry `environments: [ids]` (primary first). `Folders.view(origin)` resolves the union of their folders. A folder that is in more than one gets the highest level any of them gives it. `environment` alone works as before. With both, `environments` wins. The folder grants (`origin.folders`) still add folders at Read. Every route that uses `view` (read, search, edit, run, preflight, undo, skills) gets this for free. Check each one in the tests.
  - **Project environments:** an environment may carry `project: "<pid>"`. `GET /v1/environments` leaves them out unless `?all=1`, and the Workspace page and the chat's environment chip never list them. `POST /v1/environments` takes `project`. `DELETE` works on them as on any environment, except the Default one.
  *Done when:* `services/workspace/tests/test_environments.py` (extended) and `test_origin_envs.py` (new) cover:
    - the union and the highest level;
    - an edit allowed through the second environment;
    - a run refused when no environment gives Run;
    - grants still at Read;
    - skills scanned across every environment's folders;
    - project environments hidden from the list.

  Update architecture §4.2/§10 where the workspace mod's origin is described, and `docs/mods.md` if it documents `X-GAIFA-Origin`.
  *As built:* the tests are all in `test_origin_envs.py`. An id in `environments` that names no environment is skipped (all unknown: Default, as for one). `GET /v1/folders` answers the primary as `environment` and, with more than one, `environments`; an explicit `?environment=` (the Workspace page) drops the origin's `environments`. The origin is described in architecture §14.7 (limits); `docs/mods.md` doesn't document the workspace origin, so it is unchanged.
- [x] **2.2 The agent sends a project's environments: `services/agent/agent/projects/origin.py` (new), `hubapi.py`, `loop.py`, `context.py`, `local.py`, `prompts.py`.**
  - **One helper:** `chat_envs(settings, projects) -> {environment, environments}` replaces the four places that read `settings.environment` today (`loop.py` ≈ 602, `local.py` ≈ 140, `context.py` ≈ 468/495, `hubapi._chat_origin`). For a project chat it returns the project's environments followed by its own hidden one. Otherwise it returns the chat's environment, as now.
  - **The prompt's Environment note** (`prompts.py` ≈ 140) names the project and each of its environments.
  *Done when:* `services/agent/tests/test_project_folders.py` covers:
    - a project chat's origin carrying every environment;
    - a plain chat unchanged;
    - the folders note listing the project's folders from each environment.

  `test_environments.py` still passes.
  *As built:* the hub client's `chat_folders`, `chat_skills` and `chat_skill_read` take the helper's dict in place of an environment id, and `context.chat_folders`/`chat_skills` take the agent's `ProjectStore`. A project that lists no environments lends the chat's own (else Default) as its primary. `/v1/skills/copy` (Settings → Skills) still names one environment, as before.
- [x] **2.3 The project's own folders: `api_projects.py`.**
  - `POST /v1/projects/{pid}/folders {path, level}` makes the hidden environment the first time (`POST /api/s/workspace/v1/environments {name: "<project> (project)", project: pid}`) and adds the folder to it. `PATCH` changes a folder's level and `DELETE` removes it.
  - Adding or removing a whole environment is a `PATCH /v1/projects/{pid}` of `environments`.
  - The workspace mod's rules apply unchanged: a folder starts at Read, the GAIFA folder and `data/models/` are capped at Read, and secrets are refused.
  *Done when:* `test_projects_api.py` covers the first folder making the hidden environment, a level change and a removal, with the workspace mod faked.
  *As built:* the calls are in `projects/folders.py`; `GET /v1/projects/{pid}/folders` lists them. The hidden environment's id is `proj-<the project id's hex>`; when "<project> (project)" is taken (two projects with one name) it is "<project> (project <hex>)". Deleting the project deletes it (`project_cleanup`).

**Checks & deliverables — Phase 2**
- [ ] On a second hub with the real workspace mod, a project with two environments and one folder of its own: a project chat lists all three folders, edits a file in an Edit folder, and is refused an edit in a Read one.
- [x] Delivered: the changed `folders.py`, `environments.py`, `api_env.py`, `projects/origin.py`, the agent's origin call sites, and tests.

## Phase 3 — Knowledge: files and pages (L)

- [x] **3.1 Sources and their text: `services/agent/agent/projects/sources.py` (new), `api_projects.py`.**
  - **Routes:**
    - `POST /v1/projects/{pid}/sources {kind:'file', output_id}` or `{kind:'page', url, max_age_s?}`;
    - `PATCH …/sources/{sid}` (title, `max_age_s`, position);
    - `DELETE …/sources/{sid}`;
    - `POST …/sources/{sid}/refresh`.
  - **Fetching a page:** through the hub's `POST /api/web/read`. The source keeps the newest `output_id`, `fetched`, `chars` and `status`. An error keeps the last copy and stores `error`.
  - **Text:** a file's or page's text is read through the hub's output text routes (`/api/outputs/{id}/text`, the same reader `hub_read_document` uses), in windows of `docs.MAX_FETCH`.
  - **Events:** `project_source` events show the fetching, ok and error states live.
  *Done when:* `services/agent/tests/test_project_sources.py` covers adding a file and a page (hub and web faked), a fetch error keeping the last copy, a refresh replacing the output, and the events.
  *As built:* adding a page answers at once with `status: fetching` and fetches in the background; `refresh` waits for its fetch and answers the source. A file must be a text or document output (`422 not_text` otherwise). The text is kept in memory per output id (64 outputs), since an output's text never changes.
- [ ] **3.2 The project's collection: `services/agent/agent/projects/index.py` (new).**
  - **Indexing:** `chunks(text) -> [{n, text, page?, line}]` (about 3 000 characters with 300 of overlap). `index_source(pid, src)` sends the chunks to the embed mod as `PUT /api/s/embed/v1/texts/proj-<suffix>/<sid>#<n>` with the title, and deletes the source's old chunks first. Removing a source or deleting the project forgets its chunks (`DELETE /v1/texts/{ns}?ids=` / the whole ns).
  - **Search:** `search(pid, query, k)` uses the embed search, or a BM25 fallback over the same chunks kept in `agent.db` (`project_chunks(sid, n, text, page, line)`) when the embed mod is off.
  - **Background work:** indexing runs in a task after a source is added or refreshed, and never holds up a route.
  *Done when:* `services/agent/tests/test_project_index.py` covers the chunk edges, re-indexing replacing old chunks, a search through the faked embed mod, and the BM25 fallback.
- [ ] **3.3 Knowledge in the prompt: `services/agent/agent/projects/knowledge.py` (new), `loop.py` (`system_prompt`), `prompts.py` (`build`).**
  - **Inline or listed:** `project_knowledge(pid, window) -> {mode: 'inline'|'listed', text, tokens}`.
    - *Inline:* while all sources' text fits `project_share` × the model's window, the sources go in full, each inside `<untrusted>` with its title, kind, URL and, for pages, "fetched <age> ago".
    - *Listed:* past that, each source is one line (`src_…`, title, kind, size, age), followed by a line on `project_search` and `project_read`.
  - **Order in `prompts.build`:** new parts `project` (the name, description and instructions, after AGENT.md) and `project_knowledge` (after Skills).
  - **The meter:** the context meter (`context.meter`) counts both parts.
  *Done when:* `services/agent/tests/test_project_prompt.py` covers inline under the budget, listed over it, untrusted wrapping, page ages, the part order, and a plain chat's prompt unchanged.
- [ ] **3.4 The project tools: `services/agent/agent/projects/tools.py` (new), `local.py`, `tools.py`.**
  - **Tools:** `project_search {query, k?}` (passages with `src_…` and line), `project_read {source, offset?, limit?}` (a window of a source's text, cited as `src_…:line`), and `project_refresh_page {source}`. They are local tools, loaded only in project chats, and never offered at `/mcp`.
  - **Citations:** results start with how to cite them, as workspace reads do (backend-plan 34.6).
  - **Risk:** search and read are read-only. Refresh is a network read of a page the user linked, so it gets no approval card.
  *Done when:* `services/agent/tests/test_project_tools.py` covers each tool and checks that they are absent from a plain chat's tool list.
- [ ] **3.5 Pages fetched again when a question needs them: `services/agent/agent/projects/fresh.py` (new), `loop.py` (beside `_recall_into`).**
  - **Matching:** for a project chat's user message, `fresh.match(pid, text)` searches the project's collection, keeping only page chunks and grouping them by source. A page counts as matched when its best score is at or above `MATCH_MIN`, or its title or URL words appear in the message. At most 3 pages are matched.
  - **Fetching:** matched pages older than their `max_age_s` (and not set to never) are fetched again in parallel, re-indexed, and a `project_refresh {for: seq, pages:[{sid, title, ok, error?}]}` event is written. The first model call waits for this alongside recall (`RECALL_WAIT_S`). A page that takes longer is used as its last copy, and the prompt says so.
  - **Activity:** the event draws as a step ("Refreshed 2 pages") in the activity fold (`chat-steps.js` `registerStep`).
  *Done when:* `services/agent/tests/test_project_fresh.py` covers:
    - a matching message refreshing a stale page;
    - a fresh page not fetched;
    - an unrelated message fetching nothing;
    - a slow fetch timing out to the last copy;
    - the event.

  Update architecture §14.2 (the `project_refresh` event).

**Checks & deliverables — Phase 3**
- [ ] On a second hub with the web and embed mods: a project with a short PDF and a news page. A question about the page's subject refreshes it (the step shows) and answers from it. An unrelated question refreshes nothing. With 30 large documents the knowledge switches to listed, and `project_search` finds a passage.
- [ ] Delivered: `projects/sources.py`, `index.py`, `knowledge.py`, `tools.py`, `fresh.py`, the changed `loop.py`, `prompts.py`, `local.py`, and tests.

## Phase 4 — Instructions, defaults and project memory (M)

- [ ] **4.1 Skills that are always on: `projects/knowledge.py`, `knowledge.py`.**
  - A project's `defaults.skills` are read once per prompt build: through `read_skill`'s path for the agent's own skills, and through `hub.chat_skill_read` for workspace skills. Their bodies go in a "Skills this project uses" block, up to 8 000 characters. Skills over the cap are listed first among the skills.
  *Done when:* `test_project_prompt.py` covers both kinds and the cap.
- [ ] **4.2 Project memory: `services/agent/agent/memory/model.py`, `store.py`, `profile.py`, `learn.py` / `auto.py`, `api_projects.py`.**
  - **The entity:** creating a project creates (or adopts, by name) a `project` entity with an anchor `{kind: 'project', value: pid}` (a new anchor kind). Renaming the project renames the entity, so the old name stays as an alias.
  - **`chat_projects`:** also matches a chat whose `settings.project` is the anchor's value.
  - **Kept to its own chats:**
    - entities with a `project` anchor, and their children, are left out of the "Projects:" line in other chats' profiles;
    - `profile.recall` leaves out their facts unless the chat is in that project;
    - in that project's chats, its facts lead the profile (the `CHAT_MAX` budget is raised to 1 500 characters for a project chat).
  - **Learning:** the learner and auto-save are told that the chat is in project `<name>` (entity path). Facts about the work are filed under that entity, and facts about the user stay under You. The rules for what is saved without asking are unchanged.
  - **Routes:** `GET /v1/projects/{pid}/memory` lists the entity's facts (with the existing fact shape), and the Memory panel edits them through the existing memory routes.
  *Done when:* `services/agent/tests/test_project_memory.py` covers:
    - the entity made and anchored;
    - a rename keeping the alias;
    - facts shown in the project's chats and absent from others (profile and recall);
    - a learned work fact filed under the project;
    - delete removing the anchor and keeping the entity.

  `test_memory_prompt.py` and the memory suites still pass. Update `docs/plans/structured-memory.md`'s anchor kinds in passing (one line) and architecture §14 (memory).

**Checks & deliverables — Phase 4**
- [ ] On a second hub: a project with instructions ("answer in French") and a pinned skill. Its new chat answers in French and quotes the skill's rule. A fact said in it ("our deadline is Dec 1") lands under the project in Memory and isn't in a plain chat's prompt.
- [ ] Delivered: the changed memory modules, `projects/knowledge.py`, and tests.

## Phase 5 — The UI (L)

- [ ] **5.1 The projects page: `web/chat/chat-projects.js` (new), `chat.js`.**
  - **Route:** `#/chat/projects` draws `ProjectsPage` in the main area (as chat-history's Show all does).
  - **Header:** a title "Projects", a search, a sort menu (Recent activity, Name, Created) and **New project**.
  - **Cards:** a two-column grid (one column when narrow). Each card shows an icon, the name and the date of its last activity, and a pin toggle on hover. Pinned cards come first. A card opens `#/chat/projects/<pid>`.
  - **New project:** a dialog asks for the name (required), a description and instructions (optional). It creates the project and opens it.
  - **Empty state:** one line and the New project button.
  *Done when:* `utils/tests/web/chat-projects.test.mjs` (new; sorting, pins first, search) passes. In the browser on the mock, the grid, search, sort, pin and New project work.
- [ ] **5.2 The project page: `web/chat/chat-project.js`, `chat-project-panels.js` (new).**
  - **Route:** `#/chat/projects/<pid>`.
  - **Left column:**
    - the name (rename in place) and the description;
    - a composer ("New chat in <project>"; the shared composer, with the project's model and mode shown and changeable for this chat; the existing `c.create({settings: {project}, message})` makes the chat and opens it in the panes);
    - **Recents**: the project's chats in recent-activity order, each row with its title and date, 20 shown and then Show all (the Show all page filtered to the project).
  - **Right column panels**, each with a header and Add / Edit / View:
    - **Instructions:** a markdown text box with Save;
    - **Files:** the list with size, and Add (upload, or pick from Outputs) and remove;
    - **Pages:** the list with title, URL, "fetched 2 h ago", status, freshness menu, Refresh and remove, and Add (a URL box);
    - **Memory:** the project's facts, with edit, forget and "Open in Memory";
    - **Folders:** the environments it uses (add from a list, remove, set primary by dragging to the top) and its own folders with their level (Add folder opens the desktop's folder chooser, as `chat-envedit.js` does);
    - **Defaults:** model, mode, tool groups and MCP servers, and skills, using the composer's existing pickers;
    - a **Delete project** link at the bottom, with a confirm that says what stays.
  - **Live updates:** panels follow `project` and `project_source` events.
  *Done when:* `utils/tests/web/chat-project.test.mjs` (new; the panels' pure helpers: page ages, freshness choices, folder order) passes. In the browser on the mock, every panel adds, edits and removes.
- [ ] **5.3 A project chat: `web/chat/chat-header.js`, `chat-env.js`, `chat-list.js`.**
  - **Header:** a project chat shows a project chip (the project's name, linking to its page) instead of the environment chip. Its menu lists the project's folders and offers "Remove from project".
  - **Chat menu:** the chat's ⋯ menu gains **Move to project…** (a list of projects) and **Remove from project**.
  - **Composer:** a new chat started from a project's page keeps the project when it opens in a pane.
  *Done when:* `utils/tests/web/chat-env.test.mjs` / `environments.test.mjs` cover the project chip's choice of label and menu. In the browser on the mock, Move to project and Remove work.
- [ ] **5.4 The sidebar: Projects under New, and Group by Project: `web/chat/chat-list.js`, `chat-groups.js`, `chat-all.js`.** *Needs chat-history Phase 2 (and 3 for the Show all filter) merged first.*
  - **Projects entry:** a **Projects** row under **New** (icon, label, chevron). The row opens `#/chat/projects`. The chevron opens a dropdown with pinned projects, then the most recent, up to 8, then **All projects**. Whether the dropdown is open is page state.
  - **Group by Project:** `GROUP_BY` gains `['project', 'Project']`. It draws a section per project (5 chats, then Show more, as environments do; `c.threadGroups({by: 'project'})`, `c.threads({project})`), then **No project**. Each section header has New chat in the project and a ⋯ menu with Open project.
  - **Show all:** the page gains a project filter.
  *Done when:* `chat-groups.test.mjs` covers project sections, their order and No project. In the browser on the mock, the Projects row, its dropdown and Group by Project work. Update the brief §11.13 and `web/PATCHES.md` (one entry for the Projects UI).
- [ ] **5.5 Docs: `docs/structure.md`, `web/PATCHES.md`, `docs/architecture.md` §14, the palette (`web/Hub.dc.html`).** The palette gains "Projects" and each project by name ("Project: <name>"). The structure doc lists every new file.
  *Done when:* the docs and web tests are green.

**Wire — Phase 5:** the Chat page's sidebar has Projects, the projects grid, each project's page with its panels, project chats with their chip, and Group by Project.

**Checks & deliverables — Phase 5**
- [ ] On the installed hub after merging and `gaifa restart`, with the user's agreement to make a test project:
  - a project with instructions, one uploaded PDF, one web page, an environment and a folder of its own;
  - a new chat from its page follows the instructions, cites the PDF, and refreshes the page when asked about it;
  - the chat shows under the project with Group by Project, and under its primary environment with Group by Environment;
  - a fact said lands in the project's Memory panel;
  - deleting the test project leaves its chat as an ordinary chat.

  Screenshots of the projects grid and a project page go with the check.
- [ ] Delivered: `chat-projects.js`, `chat-project.js`, `chat-project-panels.js`, the changed chat files, the docs, and tests.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Project store and routes | projects, sources, thread link, defaults, delete, events | `services/agent/agent/projects/store.py`, `api_projects.py` |
| Folders across environments | `environments` in the origin, hidden project environments | `services/workspace/folders.py`, `environments.py`, `api_env.py`; `services/agent/agent/projects/origin.py` |
| Sources and index | files and pages, fetching, chunks in the embed mod, BM25 fallback | `services/agent/agent/projects/sources.py`, `index.py` |
| Knowledge and tools | inline or listed in the prompt, `project_search`, `project_read`, `project_refresh_page` | `services/agent/agent/projects/knowledge.py`, `tools.py` |
| Fresh pages | pages matched to a message fetched again before the answer | `services/agent/agent/projects/fresh.py`, `loop.py` |
| Project memory | a `project` entity anchored to the project, kept to its chats, learned into | `services/agent/agent/memory/*` |
| UI | the Projects entry and dropdown, the grid, the project page and panels, the project chip, Group by Project | `web/chat/chat-projects.js`, `chat-project.js`, `chat-project-panels.js`, `chat-list.js`, `chat-groups.js`, `chat-header.js`, `chat-env.js` |
| Tests | each module above, with the hub, web, workspace and embed mods faked | `services/agent/tests/test_project_*.py`, `services/workspace/tests/test_origin_envs.py`, `utils/tests/web/chat-projects.test.mjs`, `chat-project.test.mjs`, `chat-groups.test.mjs`, `chat.test.mjs` |
