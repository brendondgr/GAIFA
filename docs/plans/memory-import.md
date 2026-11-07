# Plan: Importing memories from ChatGPT, Claude and other assistants

**Asked for:** 2026-11-07 · **Status:** In progress

## 1. Introduction

Other assistants keep their own memory of the user, and the person wants it in GAIFA. None of them offers a file that is only the memory:
- **ChatGPT's** data export (Settings → Data controls → Export data) holds the chats (`conversations.json`), not the saved memories.
- **Claude's** export (Settings → Privacy → Export data) does include it: `memories.json` holds `conversations_memory`, one markdown text, and `project_memories`, one text per project id, named in `projects.json`.
- **Every assistant** can be asked to write out what it knows. Claude's own import uses this: a prompt pasted into the other assistant, whose answer is pasted back.

The person settled on this prompt (2026-11-07, adapted from Claude's). It asks for five sections (Instructions, Identity, Career, Projects, Preferences) and one entry per line as `[YYYY-MM-DD] - entry`, or `[unknown] - entry`, in one code block. They pasted a real answer: 113 lines, about half of them Instructions. It is kept outside git at `data/state/agent/memory-import-sample-2026-11-07.md` for the live checks.

This plan reads such an answer, and later Claude's export file, into GAIFA's memory with what [structured-memory](structured-memory.md) and [memory-auto-learning](memory-auto-learning.md) built:
1. Each line becomes one or more facts in the third person, with the line's date as when it began.
2. Projects become entries, with their old names as aliases.
3. Each fact is compared with what memory already holds: the same, a replacement, or new.
4. The auto-approval rules decide what is saved at once and what waits.

Nothing is saved until the person has seen a preview, and a whole import can be undone. The optional last phase runs the learner over the chats in an export. The work touches architecture §14 (the agent's memory), the brief's agent page (the Memory tab, Review), and `services/agent/agent/memory/`, `services/agent/agent/api_memory.py` and `services/agent/ui/`.

## 2. Gaps & unanswered questions

- **Instructions are rules for the assistant, not facts about the user. Where do they go?** *Assumption:* they become `preference` facts. The model files each one:
  - under the user (`you`) when it applies to any work ("Never run sudo yourself; give the user the commands");
  - under the topic or project it is for when it doesn't ("Cover letters must show fit, not tell it" under `topics/Cover letters`, the Ariadne rules under `projects/Ariadne`).

  General ones are in the profile; the others come in through recall and the chat's projects. Their imperative wording is kept, with "me"/"my" made "the user"/"their" (`wording.first_person` must pass). A separate kind for instructions is not added.
- **The profile's size.** The sample's general instructions alone are more than `PROFILE_MAX` (1500 characters). *Assumption:* 2.2 raises it to 3000. Preferences come newest first, and what doesn't fit is found by recall.
- **Is the preview the review?** *Assumption:* yes. The preview shows each line with what it becomes and a choice:
  - **Save** (the default when `auto.decide` passes);
  - **Review** (the default otherwise, with its reason; it waits in Review as now);
  - **Skip**.

  Imports always wait on the person's click: there is no import without a preview.
- **The auto-approval rules for imports.** *Assumption:* `auto.decide` with one change. The fact is grounded by its line, which the person pasted, so the quote check is replaced by "the line is in the pasted text". The other rules are unchanged:
  - the sensitive categories, and the model's `sensitive` flag;
  - not replacing a stated fact;
  - the third person;
  - the reading's `confidence ≥ auto_threshold`;
  - `auto_approve` on (when off, every line defaults to Review).

  From the sample, the Anni line (relationships), "Don't switch to a legal name" (legal) and Mycelium's grant ($) would default to Review. The person can still Save them in the preview.
- **Dates.**
  - `[YYYY-MM-DD]` → `valid_from` and the evidence's `ts` (noon that day), so interests fade from when they were said (memory-auto-learning 3.2).
  - `[unknown]` → no `valid_from`, and `ts` is the import's time.
  - Imported interests are retired by the nightly tidy like learned ones (`tidy.old_interests` reads `source in ("inferred", "imported")`).
- **Importing the same export again** (a month later, from the same assistant). *Assumption:*
  - a line whose text is already in an imported fact's evidence is `same` without asking the model;
  - a changed line is compared like any fact, so it may replace the old one, which keeps its span;
  - lines missing from the new export are left alone (the other assistant may simply have left them out).
- **Undo an import.** *Assumption:* every change the import made is undone through the log, newest first, so a fact it replaced comes back. A fact the person has changed since then is left as it is, and the undo says how many.
- **Privacy.**
  - The sample is the person's real data: it never goes in git. The tests use a made-up export in the same format.
  - Nothing leaves the machine: the model is the agent's background model (`llm.background_model`). On this machine that is skynet or the local lcpp.
- **Limits.** *Assumption:* 200 KB or 1000 lines per import, read in batches of 20 lines (about 6 model calls for the sample, plus the compare calls).
- **Learning from a whole chat history (Phase 4)** can mean hundreds of model calls, for an hour or more on this machine's GPU. *Needs a human answer* before it is run on the person's real export: which dates, and on which model.

## Phase 1 — Reading an export (M)

- [x] **1.1 The formats: `services/agent/agent/memory/sources.py` (new).**
  - **`EXPORT_PROMPT`:** the person's prompt, word for word, which the Import sheet shows with Copy (2.1).
  - **`read_lines(text) -> list[Line]`:** deterministic, with no model; `Line = {n, section, date, text}`.
    - It strips a surrounding code fence and anything after it ("This is the complete set…").
    - `## Header` and `**Header**` lines set `section`, normalised to `instructions|identity|career|projects|preferences`, else the header's own words.
    - A line `[YYYY-MM-DD] - text` gives `date`, and `[unknown] - text` gives none.
    - A plain line or bullet (`- text`, `* text`, `1. text`: what ChatGPT's Manage memories copies as) gives no date and no section.
    - An empty or header-only text is dropped.
  - **Why:** the structure is fixed, so reading it needs no model; the model only interprets each entry (1.2).
  *Done when:* `services/agent/tests/test_memory_imports.py` reads a made-up export in the person's format (`services/agent/tests/fixtures/memory-export.md`: five sections, a fence, the trailer, `[unknown]`, a bullet list without dates) and gets every line with its section and date. The real sample, read the same way in a check outside the tests, gives 113 lines: 53, 9, 7, 31 and 13 per section.
  *As built:* `**Instructions**:` written as the prompt's own list ("1. **Instructions**: Rules…") is read as a header; `[n/a]`, `[?]`, `[date saved, if available]` give no date; the same entry twice is read once.
- [x] **1.2 Interpreting the lines: `services/agent/agent/memory/imports.py` (new), `READ` prompt.**
  - **Work:** `interpret(llm, model, lines, entities) -> list[Cand]`. It makes one model call per 20 lines with the held entries' paths and aliases, and asks for each line's facts:
    - `text`: the third person ("The user…") for identity, career and preferences, and the imperative for instructions; never "I"/"me"/"my";
    - `kind`: `preference` for instructions and preferences, `interest` for what the user is into for now, else `fact` or `event`;
    - `about`: `you`, `projects/<Name>`, `topics/<Topic>`, `organizations/<Name>`, `people/<Name>`;
    - `sensitive` and `confidence`.

    Instructions get `about` by the rule in §2. The answer is checked by the same code as the learner's (`_json`, the thinking fallback in `MemoryLearner.ask`), and a batch that isn't JSON is tried once more and then shown as "couldn't read" lines.
  - **Projects:** the line's first words name the entry, and a project line gives `entity: {name, aliases, summary}`. The aliases come from "(formerly X)", "(X)" and "renamed from X"; the summary is the first clause, under 120 characters. A long line may become up to 4 facts, so a sensitive part (a grant's amount) can wait without holding the rest. An entry that already exists (`resolve` by name or alias, e.g. GAIFA) is reused and gains the new aliases.
  - **Wording:** a `Cand` still in the first person is reworded once (`wording.reword`) and marked if it stays so, as in learn.py `_third_person`.
  *Done when:* `test_memory_imports.py`, with the scripted model (`fakemodel.py`), checks:
  - the prompt holds the lines and the entries;
  - a project line makes an entry with its alias and summary;
  - "for me" comes back as "for the user";
  - a batch that isn't JSON is tried again and then reported.

  *As built:* an entry the model leaves out of its answer is "couldn't read this line" too; an identity, career or preference fact is filed under the user as well as what it names; `confidence` defaults to 0.9 when the model gives none (the entry is the user's, not a guess); an entry imported before isn't sent to the model again (1.3).
- [x] **1.3 Comparing and deciding: `imports.py`, `auto.py`.**
  - **Compare:** for each `Cand`:
    - a line already in an imported fact's evidence (`evidence[].line`, normalised) is `same`;
    - otherwise `search` finds held current facts, and the learner's `DECIDE` prompt answers same/replaces/adds/skip in batches (factored out of learn.py `_facts` into a shared `compare(m, hub, llm, model, cands)`, which the learner then calls too);
    - `ended_fact` handles "no longer X".
  - **Decide:** `auto.decide_import(cand, replaced, cfg) -> (bool, why)`: `decide` without the quote check (§2).
  - **Why shared:** two copies of the compare step would drift; the learner's tests must still pass unchanged.
  *Done when:* `test_memory_imports.py` checks:
  - a line already imported is `same`;
  - a changed interest replaces the old one, which keeps its span;
  - a sensitive line defaults to Review with its reason;
  - replacing a stated fact defaults to Review.

  `test_memory_learn.py` and `test_memory_auto.py` pass as they are.

  *As built:* `services/agent/agent/memory/compare.py` holds `DECIDE`, `ends_of`, `ended_fact` and `compare(m, hub, ask, cands, meaning_wait, batch)` (the learner asks in one batch, imports 20 at a time, waiting 3 s for meaning); an entry imported before becomes its held facts, each `same`, without a model call; the compare's `skip` defaults to Skip ("not worth keeping").
- [x] **1.4 The preview, saving and undo: `imports.py`, `store.py`, `api_memory.py`.**
  - **Store:** a table `mem_imports (id, made, source, lines, state, result, saved, undone)`:
    - `source` is `chatgpt|claude|gemini|other`;
    - `state` is `reading|ready|saved|undone|failed`;
    - `result` is the preview's JSON (each line with its `Cand`s, op, held fact, default choice and why).
  - **Routes:**
    - `POST /v1/memory/imports {text, source}` → `202 {id}`. The reading runs as a background task (one at a time, 409 while one is reading). Text over 200 KB or 1000 lines → 413 with a fix.
    - `GET /v1/memory/imports/{id}` → `{state, done, total, lines: [{n, section, date, text, facts: [{text, kind, about, op, held, choice, why}]}], counts}`.
    - `POST /v1/memory/imports/{id}/save {choices: {"<n>.<k>": "save|review|skip"}}` saves:
      - `add_fact(source="imported", by="import", evidence=[{import: id, from: source, line: text, section, ts}], valid_from=date)`;
      - then `set_fact_state(..., "active", op="fact_auto")` for Save;
      - entries made with their facts, aliases added;
      - `same` adds the evidence (`saw`).
    - `GET /v1/memory/imports` lists them with counts.
    - `DELETE /v1/memory/imports/{id}` undoes one (§2) → `{undone, kept}`.
  - **Facts:** `GET /v1/memory/facts?import=` filters by import, like `thread=` (memory-auto-learning 3.3).
  - **Docs:** architecture §14 (memory: imports).
  *Done when:* `test_memory_imports.py` runs the whole route path with the scripted model: preview → save with mixed choices → the facts, entries, aliases and log are as chosen → `DELETE` brings back what was replaced and removes the rest, leaving a fact edited since then as it was. 413 and 409 are checked.

  *As built:* the routes are their own file, `services/agent/agent/api_imports.py`, with `GET /v1/memory/imports/prompt`; `mem_imports` is made by `Importer` (`imports.py`, like `mem_learned` in learn.py) with `done` (progress), `error` and `logs` (the log ids it made) as well; an import still reading when the agent restarts is marked failed. Save adds facts directly as active or proposed (not `fact_auto`: the preview was the review, so they don't fill Review's "Learned on its own"); a waiting fact's new entry is proposed with it (`resolve_about(propose=)`). Undo counts `undone` and `kept` facts; `422` for an unknown choice, `409` saving before ready.

**Checks & deliverables — Phase 1**
- [x] On the installed hub with the agent's model: the person's sample is read as a preview only (nothing saved). Its 113 lines come back with their sections, Mycelium, Mytheca (alias Velora), GAIFA (alias AIHub, the entry that already exists) and KDence (alias TimeKeeper-v2) as entries, the general instructions under the user, the cover-letter ones under a topic, and the Anni, legal-name and grant lines defaulting to Review. Then a made-up export titled `[memory-test]` is imported and undone, and memory is exactly as before (counted by state and kind). *As checked (2026-11-07, skynet):* the sample's preview (nothing saved) read all 113 entries in about 20 minutes (6 batches): 137 facts; 32 project entries, among them Mytheca (Velora), KDence (TimeKeeper-v2), GAIFA (AIHub; memory held no project yet, so it would be new), DashLLM (relay), CSC Textiles storefront (CSC-Project); 37 instructions under the user and the rest under their topic or project (Cover letters, Exam solutions, Ariadne, Mycelium…); 133 defaulting to Save and 4 to Review: Anni (sensitive), the legal-name line (sensitive: legal), Mycelium's grant (sensitive: money, split from its other three facts), and "About Me page", wrongly caught as the first person. Fixed: a capitalised "Me", "My", "We" counts only where a sentence starts (`wording.py`); a project name with "/" ("ProQuest/Pivot-RP scraper") is kept as a name with the "/" form as an alias, not read as a path; the prompt asks for quoted words in their double quotes (the model had dropped some). Then the made-up export with a `[memory-test]` line was imported (9 saved, 3 waiting: the sister, the $40k pitch, the test line at "not sure: 0.50"; Lantern with its alias Firefly and summary) and undone: 12 facts undone, 0 kept, and memory as before (10 facts, 12 waiting, no project entries).
- [x] Delivered: `sources.py`, `imports.py`, the shared compare step, `decide_import`, `mem_imports`, the routes, the fixture and tests, and docs: architecture §14, `docs/structure.md`, this plan, the plans index.

## Phase 2 — The Import sheet (M)

- [x] **2.1 Import on the Memory tab: `services/agent/ui/memimport.js` (new), `memory.js`.**
  - **The sheet** (an **Import** button beside the Memory tab's search) has three steps:
    1. **"Ask your other assistant":** the prompt (`GET /v1/memory/imports/prompt` → `EXPORT_PROMPT`) with **Copy**, and a line saying where each assistant keeps its memory (ChatGPT: Settings → Personalization → Manage memories; Claude: Settings → Your Claude).
    2. **"Paste its answer":** a box, and From (ChatGPT / Claude / Gemini / Other).
    3. **Preview:** grouped by section. Each line shows the facts it becomes, where each is filed, "already known", "replaces: …", or the reason it waits, with Save / Review / Skip. There are counts per section, "Save all that passed", and a progress line while reading.
  - **After saving:** "Imported 96 · 12 wait in Review · Undo import".
  - **Elsewhere:** the Memory tab's **Imports** list (date, source, counts, Undo). Review and the Timeline show "imported from Claude, 2026-11-07" and the original line.
  - **Docs:** the brief's agent page (Memory tab, Review).
  *Done when:* `utils/tests/web/agent-memory.test.mjs` renders the preview from a recorded `GET` result with the fake DOM: the sections, the choices and their defaults, the counts, and Undo import.
  *As built:* the card and the Imports list are `importCard` in `memimport.js`; the Memory tab draws them (Import… beside Search, the card above the entries, Imports (N) under them). A reading import redraws every 2.5 s and can be left and opened again from Imports. Changing a choice redraws only the card. Review's `byChat` also groups by import, and `importText` gives "imported from Claude · “the entry”".
- [x] **2.2 The profile after an import: `profile.py`.**
  - **Work:**
    - `PROFILE_MAX` becomes 3000;
    - the user's preferences come newest first (by `valid_from`, else `recorded`);
    - imported facts show their dates like learned ones;
    - recall (`profile.recall`) is unchanged.
  - **Docs:** architecture §14 (the profile).
  *Done when:* `test_memory_time.py` checks that the profile stays within 3000 characters with the fixture's 30 preferences, newest first. A recall test checks that a message about a cover letter brings back the cover-letter instruction filed under its topic.

**Checks & deliverables — Phase 2**
- [x] A browser walk-through on the installed hub with a made-up export titled `[memory-test]`: Import → Copy prompt → paste → preview (sections, defaults, reasons) → Save → the facts on the Memory tab with "imported", a waiting one on Review → Undo import → gone. Screenshots in `docs/reference/memory-import-2026-11/`. *As checked (2026-11-07):* in the browser on the installed hub, Import… → the prompt and Copy → the made-up export pasted (with a `[memory-test]` line, which the model left out as not a memory: "1 entry it couldn't read") → Read it → the preview (9 to save, 2 to Review: $40k and the sister) → Save → the facts on the Memory tab "imported from ChatGPT" with their dates, Lantern and Hearth under Projects, Cover letters under Topics → Review's "From your ChatGPT import" with the entries and reasons → Undo import (confirmed) → "Undone: 11 facts", memory as before (10 facts, 12 to review). The person's own 113-entry preview opened from Imports and showed its four waiting facts with their reasons (not saved). Fixed on the way: "1 entries"; the prompt's instructions now change only "me/my/I" (the model had written "unless told to the user").
- [ ] With the person's go-ahead, they import their sample from the sheet (or it is imported for them). Then a new chat answers from memory alone: "what are my projects?", "should you push to GitHub?" and "what am I into these days?".
- [x] Delivered: `memimport.js`, the Memory tab and Review changes, the profile change, and docs: the brief, `docs/structure.md` (no `web/` change, so no PATCHES entry), architecture §14 (the profile).

## Phase 3 — Files from Claude, and exporting GAIFA's memory (S)

- [x] **3.1 Claude's export file: `sources.py`, the sheet.**
  - **Work:** the sheet also takes a file, either Claude's export `.zip` (the first batch, which holds `memories.json`) or `memories.json` itself. It is read in the agent (`POST /v1/memory/imports` with a multipart file, 50 MB at most), and only `memories.json` and `projects.json` are opened.
    - `conversations_memory` (markdown with its own headings) → `read_lines` (each paragraph or bullet a line, its heading the section).
    - `project_memories[uuid]` → lines filed under `projects/<the project's name from projects.json>`.

    Missing or unexpected fields give "this file isn't a Claude export" with the files it found, never a 500.
  *Done when:* `test_memory_imports.py` reads a made-up Claude zip (with `memories.json`, `projects.json` and a large `conversations.json` that isn't read) and a bare `memories.json`. A ChatGPT zip gives the message that it holds no memories, with the prompt route to use instead.
  *As built:* the file comes as base64 in JSON (`POST /v1/memory/imports/file {name, data, source}`, like the skills upload), read by `sources.read_file`: a zip's `memories.json` and `projects.json` wherever they sit in it (20 MB each at most), else the file as `memories.json` (a dict or a list of one); `conversations_memory`'s headings become sections and each paragraph or bullet an entry; a project's entries start with its name ("Lantern: …") under `projects`. A ChatGPT zip or `conversations.json`, a zip without `memories.json`, or something else are a 422 `not_an_export` with what to do. The card's step 2 has a file chooser.
- [x] **3.2 Export: `GET /v1/memory/export`, the Memory tab.**
  - **Work:** the user's current facts and the projects' facts in the same five-section `[YYYY-MM-DD] - entry` format, as text to copy or a `.md` to download. That way the memory can be pasted into Claude's import or into another GAIFA. Reading GAIFA's own export back is `same` for every line.
  *Done when:* a round-trip test: export → import preview → every line `same`.
  *As built:* `Importer.export()` → `{text, count}`; sections: an imported preference goes back to the section it came from, otherwise a preference about someone ("The user prefers…", "Sam likes…") is Preferences and a rule ("Never push…") Instructions, the user's other facts Identity, projects' facts Projects, the rest Other. The preview treats an entry that is a current fact's own text as `same` without the model, so the round trip needs no model call. **Export** beside Import… shows the text with Copy and Download .md (`exportCard`).

**Checks & deliverables — Phase 3**
- [x] On the installed hub: a made-up Claude export zip is previewed, and Export's text, pasted back, previews as all known. *As checked (2026-11-07, skynet):* a zip shaped like Claude's (`memories.json` with work and personal context and one project memory, `projects.json` naming it Lantern, `conversations.json`, `users.json`; `[memory-test]` lines) gave 5 entries and 5 facts to save; saved, Export gave them in four lines under Identity and Projects (and "Sam prefers short answers." under Instructions, now fixed: the prompt says "The user" even where an entry uses a name, and Export reads a preference about someone as a Preference); pasted back, the preview was 5 already known at once, without the model; the import undone, memory as before.
- [x] Delivered: the file reader, export, and docs: architecture §14, the brief, `docs/structure.md`.

## Phase 4 — Learning from the chats in an export (L, optional)

- [ ] **4.1 Past chats as the learner's input: `services/agent/agent/memory/history.py` (new).**
  - **Formats:** ChatGPT's `conversations.json` (the `mapping` tree: `message.author.role`, `content.parts`, `create_time`) and Claude's (`chat_messages`: `sender` human/assistant, `text`, `created_at`).
  - **Work:** each conversation becomes a `render`-style transcript of the user's messages, with the assistant's shortened as the learner does now. It goes through the learner's `EXTRACT` and the shared compare step (1.3), and the facts' evidence is `{import, conversation title, ts}`.
  - **Order and limits:** newest first, from a date the person picks, at most N conversations; a background job with progress and Cancel, one model call at a time.
  - **Review:** everything it finds defaults to Review: the quote check is against the user's own messages, as in `auto.decide`.
  *Done when:* tests read both formats from made-up files and learn two facts from a scripted conversation, dated by the conversation.

**Checks & deliverables — Phase 4**
- [ ] Only with the person's answer to §2's last gap: a run over their real export's most recent month, with the counts and the time it took.
- [ ] Delivered: `history.py`, the job and its sheet step, and docs.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Formats | the export prompt; pasted answers, plain memory lists, Claude's export file read into lines | `services/agent/agent/memory/sources.py` |
| Import | lines interpreted into facts and entries, compared, decided, previewed, saved and undone | `services/agent/agent/memory/imports.py`, `auto.py`, `store.py` (`mem_imports`), `api_memory.py` |
| Import sheet | the prompt with Copy, paste or file, the preview with Save / Review / Skip, Undo import, the Imports list | `services/agent/ui/memimport.js`, `memory.js` |
| Profile | a larger budget, preferences newest first | `services/agent/agent/memory/profile.py` |
| Export | GAIFA's memory in the same format | `api_memory.py` |
| Past chats (optional) | the learner over an export's chats | `services/agent/agent/memory/history.py` |
| Tests | made-up exports (pasted, Claude zip, conversations), the scripted model, the preview render | `services/agent/tests/test_memory_imports.py`, `services/agent/tests/fixtures/`, `utils/tests/web/agent-memory.test.mjs` |
