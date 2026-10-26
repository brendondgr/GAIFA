# Plan: structured memory: entities, facts that change, search by meaning

**Asked for:** 2026-10-26 · **Status:** In progress

## 1. Introduction

What the agent knows about the user is two flat lists today. `remember` saves a hub preference with `scope = "agent"` (plan 21.4: one line of prose, in every prompt, at most 60 lines with the tool preferences), and the older `data/agent/memory/MEMORY.md` index and topic files (plan 14.9) still load into every prompt. Nothing knows that "GAIFA" is a project, that it used to be called "AIHub", which facts are about it, which fact replaced which, or when a fact stopped being true; nothing is searched, so memory only grows the prompt.

The user wants memory that is structured and searchable, kept up to date as things change: categories such as projects, with an entry per project; a rename that carries every related memory with it; facts that are replaced rather than piled up; and search by meaning so the agent finds what it needs in one call. Not a knowledge graph: **entities** in a tree (`projects/GAIFA`), each with a stable id, a name, aliases and anchors (a workspace folder, a git remote), and **facts** that say something about one or more entities, with when they held, where they came from and what they replaced. Grounded in what other systems do (2026-10-26 survey: Claude Code's index plus topic files, Claude.ai's per-project memory, Mem0's extract → compare → choose an operation, Zep/Graphiti's facts that are invalidated rather than deleted and its exact-match-before-LLM entity resolution, Letta's background consolidation, Supermemory's `updates`/`extends` links and its guidance that a display name is never an identity).

Memory belongs to the chat agent: it lives in the agent mod (`services/agent/agent/memory/`, tables in `agent.db`), is searched through the embed mod, and is **never offered to MCP clients** (the user, 2026-10-26). Tool preferences stay what they are (hub data that fills every caller's cards, plan 21); only the prose `agent` preferences move into memory. Writes still go through the hub's permissions (a `write` tool, as `remember` is today), and what the agent infers on its own waits for the user's approval on the Learning page, like inferred preferences. Touches architecture §14.1 and §14.5–14.6, the agent's README, the embed mod's README, the brief's §11.13, and backend-plan Phases 14.9, 21 and 28.5.

## 2. Gaps & unanswered questions

- **A graph?** No (the user, 2026-10-26): entities form a tree by `parent`; a fact may be `about` several entities; there are no typed relations between entities and no graph store.
- **Inferred memories:** answered: they need the user's approval, in the same review as inferred preferences (the agent mod's Learning page). What the user states (`remember`, "remember that…") is active at once.
- **MCP clients:** answered: memory is the agent's only. The memory tools carry `mcp = false` (3.1) and `/mcp` never lists them.
- **Which model writes memories in the background:** *Assumption:* the model the chat summaries use (plan 28.5, `summaries.py`), with JSON constrained by a schema where the server supports it (llama.cpp grammars through the relay).
- **What background learning may read:** *Assumption:* only the user's own messages, their answers to questions, their card edits and what the agent did (tool names and statuses), never tool results, documents or pages (plan 24.8's rule: text from outside never becomes a memory on its own).
- **Deleting:** nothing is deleted by the agent: a fact is retired (`valid_until` set, `replaced_by` filled) and stays in the history. "Forget" in the UI deletes for real, after asking (the user's own data, in the agent's database).
- **Without the embed mod:** *Assumption:* search falls back to names, aliases and SQLite FTS5 keywords; nothing fails.
- **Prompt cache:** recalled memories go on the turn's user message, not the system prompt, so a local server's prefix cache survives between turns (3.3).
- **The old memory files and agent preferences:** *Assumption:* imported once as stated facts about the user (1.3); the files stay where they are; the preferences become `retired` with a note pointing at the fact.

## Phase 1 — The store (M)

- [x] **1.1 Entities and facts: `services/agent/agent/memory/store.py`, `memory/model.py`.**
  - **Tables (in `agent.db`):** `mem_entities {id, kind, name, parent, summary, scope, state (active|merged|archived), merged_into, created, updated}`; `mem_aliases {entity, alias, normalized, added}` (unique per normalized alias among active entities); `mem_anchors {entity, kind (folder|git|workspace), value}`; `mem_facts {id, text, kind (preference|fact|event|procedure), valid_from, valid_until, recorded, source (stated|inferred|imported), state (proposed|active|retired|rejected), confidence, replaces, replaced_by, evidence (json: thread, seq), seen, last_used, updated}`; `mem_fact_entities {fact, entity}`; `mem_log {id, ts, op, target, before, after, by}` (every change, for undo and the history view); `mem_fts` (FTS5 over facts and entity names and aliases).
  - **Kinds:** `user` (one, the person), `project`, `person`, `place`, `tool`, `topic`, `organization`. A path is the names up the `parent` chain (`projects/GAIFA` for a project whose parent is the kind's root).
  - **Operations (`MemoryStore`):** `entity_create`, `rename(id, name)` (the old name becomes an alias; every title is drawn from the id, so nothing else changes), `alias_add/remove`, `move(id, parent)`, `merge(a, into)` (facts and aliases move, `a` becomes `merged` with `merged_into`; undoable from the log), `fact_add`, `fact_replace(old, new)` (old gets `valid_until` and `replaced_by`), `fact_retire`, `approve/reject`, `undo(log_id)`, `resolve(name)` (exact name, then alias, normalized: case, spaces, punctuation; never a model).
  - **Why in the agent mod:** memory is the agent's only (§1), and the agent already owns its database and data folder.
  *Done when:* `services/agent/tests/test_memory_store.py` covers create, rename (old name resolves to the same id), merge and its undo, replace (history kept, only the current fact listed as current), retire, a clash of aliases, FTS search and the log.
- [x] **1.2 The routes: `services/agent/agent/api_memory.py`.**
  - **Routes:** `GET /v1/memory/tree` (kinds → entities with counts), `GET /v1/memory/entities/{id}` (with current facts, replaced facts, aliases, anchors, history), `POST /v1/memory/entities`, `PATCH /v1/memory/entities/{id}` (`name`, `parent`, `summary`, `aliases`), `POST /v1/memory/entities/{id}/merge {into}`, `GET /v1/memory/facts?state=&entity=&q=`, `POST /v1/memory/facts`, `PATCH /v1/memory/facts/{id}` (text, entities, valid dates, state), `DELETE /v1/memory/facts/{id}` (forget), `POST /v1/memory/undo/{log_id}`, `GET /v1/memory/log`.
  - **Errors:** the envelope `{detail, code, fix?}`.
  *Done when:* `services/agent/tests/test_api_memory.py` covers each route over the app (TestClient), including 404s, a merge into itself (422) and an undo.
- [x] **1.3 Importing what exists: `memory/importer.py`.**
  - **Once, at start:** each active `agent`-scope preference (`GET /api/prefs?scope=agent&state=active`) and each line of `data/agent/memory/*.md` becomes a `stated` (or `imported`, for the files) fact about the `user` entity (a topic file's name becomes a `topic` entity it is also about); the preferences are retired with the note "moved to memory: <fact id>"; a marker in `data/agent/memory/.structured` stops a second run.
  - **Then:** `Knowledge.memory_index` lists the current facts from the store (and, until 5.2 removes Settings' MEMORY.md editor, its lines that aren't facts); `import_memory` goes. *As built:* preferences are looked for at every start (each one moved is retired), so a `remember` made before 3.2 still moves; the files once. `Knowledge.preferences` keeps listing `agent`-scope preferences until 3.2 moves `remember`.
  *Done when:* `services/agent/tests/test_memory_import.py` (fake hub): preferences and files become facts once, the preferences are retired, a second start imports nothing.

**Checks & deliverables — Phase 1**
- [x] On the installed agent, the import runs, `GET /v1/memory/tree` lists the user and topic entities, and nothing in a chat's prompt is lost (the profile of Phase 3 isn't built yet: the facts list under "Memory" as before, from the store). *As checked (2026-10-26):* this machine had no memory files and no agent preferences: the import wrote its marker, the tree holds the user alone.
- [x] Delivered: `memory/store.py`, `facts.py`, `model.py`, `api_memory.py`, `importer.py`, tests; docs: the agent's README, architecture §14.5.

## Phase 2 — Search by meaning (M)

- [x] **2.1 Text collections in the embed mod: `services/embed/embed/api_texts.py`, `store.py`.**
  - **Generalize `chats`:** a `texts` table `{ns, id, title, text, meta, state, vector}`; `PUT /v1/texts/{ns}/{id}`, `DELETE /v1/texts/{ns}/{id}`, `DELETE /v1/texts/{ns}?ids=`, `GET /v1/texts/{ns}` (counts), `POST /v1/texts/{ns}/search {query, limit, ids?}` → `[{id, score, title, meta}]`. Embedded under the same idle rule and GPU lease as the chats; `ns` is `[a-z][a-z0-9-]{1,31}`.
  - **The chats:** `/v1/chats…` stay as they are. *As built:* the chats keep their own table; the texts get theirs (`texts`), and the indexer embeds both between outputs (`store.queued`). A text put again with the same words keeps its vector.
  *Done when:* `services/embed/tests/test_texts.py` (fake backend) covers put, re-put with new text, delete, search ranking, `ids` filtering and the chats routes unchanged.
- [x] **2.2 Keeping the index: `memory/index.py`.**
  - **What is embedded:** each current fact (`text` plus its entities' paths and names) as `fact:<id>`; each entity (path, name, aliases, summary) as `entity:<id>`, in `ns = "memory"`.
  - **When:** after each change (a queue in the agent, sent in batches); a retired or forgotten fact is deleted from the index; a rename re-sends the entity and its facts. A full re-send on `POST /v1/memory/reindex` and when the embed mod reports an empty namespace.
  *Done when:* `services/agent/tests/test_memory_index.py` (fake hub): a new fact, a rename and a retire send the right puts and deletes; nothing is sent for proposed facts.
- [x] **2.3 `memory_search`: `memory/search.py`, a local tool in `tools.py` and `local.py`.**
  - **Search:** three lists fused by reciprocal rank (k = 60): names and aliases found in the query (exact, normalized), FTS5 keywords, and the embed mod's `memory` search; then the facts of matched entities, one step down the tree for a matched parent. Current facts only unless `history: true`.
  - **Tool:** `memory_search {query, entity?, kind?, history?, limit?}` → facts with `{id, text, entities: [paths], valid_from, source, replaced?}` and the matched entities with their summaries; a read-only local tool (never in the hub's catalog, so never at `/mcp`).
  *Done when:* `services/agent/tests/test_memory_search.py`: a query naming an old alias ("AIHub") finds GAIFA's facts; a meaning-only query finds a fact through the fake embed scores; without the embed mod the keyword and name lists still answer.

**Checks & deliverables — Phase 2**
- [x] On the installed hub with the embed mod running: after the import, `memory_search` in a chat finds a fact by a paraphrase. *As checked (2026-10-26):* a fact sent through the agent reached the `memory` collection, and "what aspect ratio does the user like for desktop backgrounds?" found "Prefers widescreen 16:9 pictures for wallpapers" at 0.82 (the user entity 0.59); then forgotten.
- [x] Delivered: `api_texts.py`, `memory/index.py`, `memory/search.py`, tests; docs: the embed mod's README, the agent's README.

## Phase 3 — Memory in chats (M)

- [x] **3.1 Tools only the agent sees: `mcp = false`: `utils/manifest.py`, `utils/tools/catalog.py`, `utils/tools/mcp.py`.**
  - **Field:** `ToolSpec.mcp: bool = True` (and the same key in `tools_source` rows); `ToolDef.mcp`; the MCP endpoint leaves such tools out of `tools/list` and answers `tools/call` for one as an unknown tool. The chat and the hub's own API still see them.
  *Done when:* `utils/tests/tools/test_mcp.py` gains a fake-mod tool with `mcp = false`: absent from both protocol eras' lists, refused on call, present in `/api/tools`; the docs: architecture §4.3 (the field) and §14.7.
- [x] **3.2 Writing from a chat: the agent's `[tools]` and `remember`.**
  - **Tools (`services/agent/service.toml`, routes in `api_memory.py`, all `mcp = false`):** `agent_memory_save {text, about?: [names or paths], kind?, replaces?: fact id, valid_from?}` (`write`): resolves `about` (1.1's `resolve`; an unknown name makes an entity, its kind guessed from the words around it or `topic`), saves a `stated` fact, and when `replaces` is given or one current fact of the same entities says the opposite (2.3's search, top 3, the model shown them in the tool's result) the agent may pass `replaces`; `agent_memory_entity {id or name, rename?, alias_add?, parent?, summary?}` (`write`); `agent_memory_forget {fact}` (`destructive`).
  - **`remember`:** stays the name the model knows (so harness notes and evals keep working) and runs as `agent_memory_save` through the hub, as it runs as `hub_set_preference` today (`loop.py`); Plan mode refuses it and a chat that read untrusted text gets a card, as now. *As built:* `agent_memory_save` and `agent_memory_entity` join `hub_set_preference` in the default ask list and in `ASK_AFTER_UNTRUSTED` (`utils/config.py`, `utils/tools/approvals.py`); `Knowledge.preferences` stops listing prose (`agent`-scope) preferences; saving a sentence already saved, with `replaces`, links the two instead of making a copy; the base system prompt says what goes where.
  *Done when:* `services/agent/tests/test_memory_tools.py` (fake hub): `remember` with `about: ["GAIFA"]` saves a fact on the project, a rename through `agent_memory_entity` keeps its facts, `replaces` retires the old fact; `uv run pytest` passes with the manifest change.
- [ ] **3.3 Reading in every chat: `knowledge.py`, `loop.py`, `prompts.py`.**
  - **The profile (system prompt, ≤ 1,500 characters):** the `user` entity's current facts (preferences first), then the active projects' names and one-line summaries; replaces the "Memory" section's index and agent preferences. It changes only when memory does, so the prefix cache holds.
  - **The chat's projects:** projects anchored to the chat's workspace folders (by folder id, path or git remote) get their current facts in the profile too, under "This chat works in: GAIFA (…)".
  - **Recall per turn:** before each user turn, 2.3's search on the message (top 8 facts above a score floor, ≤ 800 characters, none already in the profile) is stored on the user event (`memory_recall: [fact ids]`) and drawn into that message as a `<memory>` block (`ctx.rebuild`), so earlier turns stay byte-identical. `last_used` is stamped.
  - **Off:** a chat with `no_learn` still reads memory; Settings → Agent → Memory gains "Recall memories in each turn" (`memory.recall`, default on).
  *Done when:* `services/agent/tests/test_memory_prompt.py`: the profile's shape and cap, a workspace chat's project facts, recall stored on the event and rebuilt the same on the next turn, the setting off.

**Wire — Phase 3:** chats use the new memory; the composer's "Remembered" step shows the entity it was saved under.

**Checks & deliverables — Phase 3**
- [ ] On the installed hub: in one chat say "remember that GAIFA's mods use ports 5100–5199"; in a new chat in an environment holding `~/Agents/GAIFA`, ask about the ports: the fact is in the profile or recalled, without a tool call; in Claude Code, `/mcp`'s tool list has no memory tool.
- [ ] Delivered: the manifest field, the agent's tools, the profile and recall, tests; docs: architecture §4.3, §14.1, §14.5, the brief's §11.13.

## Phase 4 — Learning memories in the background (M)

- [ ] **4.1 After a chat goes quiet: `memory/learn.py`, called next to `summaries.py`.**
  - **Input:** the chat's user messages, answers and card edits since the last pass (the learner's rendering, `learn.loop.render`, without tool results or document text), plus the profile.
  - **Steps:** (1) the model lists candidate facts as JSON `[{text, about: [names], kind, valid_from?}]`; (2) each `about` name is resolved without a model (1.1's `resolve`), an unknown one becomes a proposed entity; (3) for each candidate, the 5 nearest current facts of the same entities (2.3); (4) the model picks one operation per candidate: `same:<id>` (`seen` + 1), `replaces:<id>`, `adds`, `skip`; (5) results are saved as `proposed` facts (and `proposed` replacements) with their evidence (thread, seq). An empty or malformed answer is logged and retried once next pass, never read as "nothing to learn".
  - **Limits:** at most 20 candidates a pass; `no_learn` chats, dry runs and eval threads are skipped; `[learning] enabled = false` stops it.
  *Done when:* `services/agent/tests/test_memory_learn.py` (scripted fake model): a new fact is proposed with its evidence, a repeat bumps `seen`, a change ("we renamed AIHub to GAIFA") proposes a rename of the existing entity, a malformed answer is retried, tool results never reach the model's input.
- [ ] **4.2 Tidying: `memory/tidy.py` in the nightly learner run (`[learning] nightly_at`).**
  - **Work:** facts whose `valid_until` passed are retired; entities whose names or aliases normalize alike, or whose embeddings are very close, become a proposed merge; an entity with new facts gets its summary rewritten (one sentence, from its current facts); facts unused for `[memory] fade_days` (default 180) that were inferred are proposed for retiring.
  - **Never:** it changes no `stated` fact and merges nothing without approval.
  *Done when:* `services/agent/tests/test_memory_tidy.py` covers each kind of work and that stated facts are untouched.

**Checks & deliverables — Phase 4**
- [ ] On the installed hub, a chat that mentions a new project and a changed preference, left quiet, produces proposed memories with their evidence.
- [ ] Delivered: `memory/learn.py`, `memory/tidy.py`, tests; docs: architecture §14.6.

## Phase 5 — The Memory page and review (M)

- [ ] **5.1 Memory and Review tabs: `services/agent/ui/page.js`, `services/agent/ui/memory.js`.**
  - **Memory tab:** the tree (kinds → entities), an entity's page (name with Rename, aliases, anchors, summary, current facts with Edit and Forget, replaced facts folded with when and why, the history from `mem_log` with Undo), search across memory (2.3), and "New memory".
  - **Review tab:** proposed facts, replacements, renames and merges next to the proposed preferences, each with its evidence (a link to the chat at that message), Approve / Edit / Reject, and "Approve all from this chat".
  - **Header badge:** the agent's status reports `memory_review` (a count); the nav's Agent entry shows it.
  *Done when:* `utils/tests/web/agent-memory.test.mjs` covers the tree, an entity page and the review rows; on the installed hub the user renames an entity, approves a proposed fact and undoes a merge.
- [ ] **5.2 Settings → Agent → Memory: `web/chat/chat-settings.js` (`MemoryCard`), `web/settings/schema.js`.**
  - **Rows:** recall per turn (3.3), fade days (4.2), a link to the Memory tab, the count of facts and entities; the old AGENT.md editor stays; the MEMORY.md editor goes.
  *Done when:* `utils/tests/web/settings-schema.test.mjs` covers the rows; Settings → Agent shows them on the installed hub.

**Wire — Phase 5:** the agent's page gains Memory and Review; Settings → Agent → Memory is the new card.

**Checks & deliverables — Phase 5**
- [ ] Rename "GAIFA" to "GAIFA hub" on the page: every fact shows the new name, "AIHub" and "GAIFA" still find it, the history shows the rename and Undo restores it.
- [ ] Delivered: `ui/memory.js`, the page's tabs, the settings card, tests; docs: the agent's README, the brief's §11.13.

## Phase 6 — Measuring it (S)

- [ ] **6.1 A memory eval: `services/agent/evals/memory.py`.**
  - **Scripted conversations:** a project renamed midway, a preference changed, a fact that expires, a question memory can't answer (the agent must say it doesn't know); plus LongMemEval's knowledge-update and abstention questions run through the store and `memory_search` (not the full 115k-token histories).
  - **Measures:** right answers, wrong current fact (stale), proposals that the reviewer would reject (a scripted judge), tokens per turn.
  *Done when:* the eval runs on skynet (`localhost:9090`) and this machine's chat model, and the numbers are in `docs/agent-eval.md`.

| Deliverable | Description | Location |
| --- | --- | --- |
| Store | entities, aliases, anchors, facts, the log | `services/agent/agent/memory/store.py`, `model.py` |
| Routes | the Memory page's and the tools' API | `services/agent/agent/api_memory.py` |
| Search | names, keywords and meaning, fused | `services/agent/agent/memory/search.py`, `index.py`, `services/embed/embed/api_texts.py` |
| In chats | profile, per-turn recall, `remember`, the memory tools | `knowledge.py`, `loop.py`, `prompts.py`, `services/agent/service.toml` |
| Background | learning after a chat, nightly tidying | `services/agent/agent/memory/learn.py`, `tidy.py` |
| Agent-only tools | `mcp = false` | `utils/manifest.py`, `utils/tools/catalog.py`, `utils/tools/mcp.py` |
| UI | Memory and Review tabs, the settings card | `services/agent/ui/memory.js`, `page.js`, `web/chat/chat-settings.js` |
| Tests | store, routes, import, index, search, tools, prompt, learning, tidying, UI, eval | `services/agent/tests/test_memory_*.py`, `services/embed/tests/test_texts.py`, `utils/tests/tools/test_mcp.py`, `utils/tests/web/agent-memory.test.mjs` |
