# Plan: Memory that learns on its own, worded right, dated, and easy to find

**Asked for:** 2026-11-07 · **Status:** Planned

## 1. Introduction

[structured-memory](structured-memory.md) built the agent's memory: entities, facts that are replaced rather than overwritten, a learner that reads quiet chats, and a Review tab. On this machine (checked 2026-11-07) it has learned but not remembered anything. The learner went through 51 chats and proposed 10 facts and 2 entries. None of them are active, because every inferred memory waits for approval, and the person did not know where Review was. It sits on the agent's page behind the sidebar entry **Learning**, and the header's **Approvals** popover does not list it. Six of the ten proposals are also worded in the first person ("I work independently and hate qualifying exams.") because `EXTRACT` in `services/agent/agent/memory/learn.py` asks for the user's statements and copies them as they were said.

This plan changes the defaults so most memories just happen:
1. Every learned fact is written in the third person.
2. The learner rates each fact. Facts that are clearly stated, grounded in the user's own words and not sensitive become active on their own, with a visible record and Undo. Only uncertain or sensitive facts wait in Review.
3. Every fact keeps when it was said and how long it held. Changed interests replace older ones but stay on the timeline.
4. What waits for review appears in the header's Approvals popover and under a sidebar entry named for memory.

It touches architecture §14 (the agent: memory and learning lines), the brief's agent page and header sections, and the code in `services/agent/agent/memory/` and `services/agent/ui/`.

## 2. Gaps & unanswered questions

- **Which facts are "sensitive" and always wait for review?** *Assumption:* health, money and finances, legal matters, relationships and family, religion, politics, sexuality, and anything about another named person. These are the `SENSITIVE` categories in 2.1, and the person can change the list in Settings.
- **What confidence threshold auto-approves a fact?** *Assumption:* 0.8. The model's own score is only one input: a fact is auto-approved only when the user's quote is also found verbatim in a USER line of the chat (2.1). Settings → Agent → Memory exposes the threshold.
- **May an auto-approved fact replace an older fact?** *Assumption:* yes, when the older fact is inferred. Replacing a **stated** fact (from `remember`) always waits for review, as structured-memory promised that the user's own words are never changed by the agent.
- **Renames and merges:** *Assumption:* renames stay in Review (they rename an entry and all its facts), and nightly merges stay in Review.
- **The 10 proposals already waiting:** *Assumption:* 1.3 rewrites their wording (they are the learner's text, not the user's), and they stay proposed. They are not auto-approved after the fact, and the person decides on them in Review. One of them ("lost $50 million in the tech sell-off") looks like it came from a test or role-play chat.
- **Should auto-learning be on by default for everyone?** *Assumption:* yes (`auto_approve = true` in `data/agent/memory.json`), with a one-line note on the Memory tab and Settings saying so and how to turn it off. The person asked for this on 2026-11-07.
- **Should the chat say when it learned something?** *Assumption:* yes, quietly. When a chat is opened again after the learner saved facts from it, a small "Remembered 3 things · Review" line appears under the last turn (3.3). There is no popup.

## Phase 1 — Facts in the third person (S)

- [ ] **1.1 The extract prompt: `services/agent/agent/memory/learn.py` `EXTRACT`.**
  - **Prompt:** each fact is "one sentence in the third person about the user ('The user…', 'Their…'), never 'I', 'my' or 'me'". Add two examples next to the Lumen one: "I hate qualifying exams" → "The user dislikes qualifying exams." and "my advisor is supportive" → "The user's advisor is supportive."
  - **Also asked for (used by Phase 2):** `quote`, the user's own words the fact comes from, copied exactly; `confidence`, 0 to 1; and `sensitive`, true or false with the categories from §2.
  *Done when:* `services/agent/tests/test_memory_learn.py` checks that the prompt asks for the third person and for `quote`, `confidence` and `sensitive`, and that a scripted answer with these fields is read.
- [ ] **1.2 A wording check: `services/agent/agent/memory/wording.py` (new).**
  - **`first_person(text) -> bool`:** whole-word "I", "I'm", "I've", "me", "my", "mine", "myself", "we", "our", outside quotation marks.
  - **`reword(llm, model, facts) -> list[str]`:** one call that rewrites the given facts in the third person and keeps their meaning. The learner uses it on any fact that `first_person` catches. A fact that still fails after one rewrite is saved as proposed (never auto-approved) and logged.
  - **Never:** it is used only on `source = "inferred"` facts. Stated facts (`remember`) keep the user's words.
  *Done when:* `services/agent/tests/test_memory_wording.py` checks that the five first-person Nov 5 sentences are caught, that "The user said 'I can't'" is not caught, and that a scripted reword is applied while a failed one leaves the fact proposed.
- [ ] **1.3 The proposals already saved: `POST /v1/memory/reword` (`services/agent/agent/api_memory.py`).**
  - **Work:** this rewords every proposed or active **inferred** fact that `first_person` catches, through `MemoryStore.set_text` (or the existing correct-a-fact path in `facts.py`). Each change is logged as `fact_edit` by `learner`, so it can be undone.
  - The tidy pass (`tidy.py`) also calls it every night.
  *Done when:* the route test rewords an inferred first-person fact and leaves a stated one untouched. On the installed hub, the six first-person proposals from 2026-11-05 read "The user…" on Review, and each one's History shows the old text with Undo.

**Checks & deliverables — Phase 1**
- [ ] A chat on the installed hub that says "I prefer short answers and I'm learning Rust", left quiet (or `POST /v1/memory/learn?thread=`), produces "The user prefers short answers" and "The user is learning Rust".
- [ ] Delivered: `wording.py`, the prompt change, the route, and the docs: architecture §14 (the learner) and the structured-memory plan's 4.1 note linking here.

## Phase 2 — Auto-approval of confident facts (M)

- [ ] **2.1 The decision: `services/agent/agent/memory/auto.py` (new).**
  - **`decide(cand, chat_users, held, settings) -> "auto" | "review" | "skip"`:** the result is `auto` only when all of these hold:
    - `settings["auto_approve"]` is on;
    - `confidence ≥ settings["auto_threshold"]` (default 0.8);
    - `quote` is found in one USER line after normalising spaces and case. This is the grounding check: the model cannot auto-approve something the user did not say;
    - `sensitive` is false, and the fact text matches none of the `SENSITIVE` keyword lists (a second deterministic net);
    - it does not replace a **stated** fact;
    - the third-person check from 1.2 passes;
    - the chat is not `no_learn`, a dry run or an eval chat (already skipped by `due()`).
  - A fact the learner sees again (`same`) that is still proposed also becomes active once `seen ≥ settings["auto_after_seen"]` (default 2), if it is not sensitive.
  - **Settings:** `data/agent/memory.json` gains `auto_approve` (true), `auto_threshold` (0.8), `auto_after_seen` (2) and `always_review` (the category list). `profile.settings()` returns their defaults.
  *Done when:* `services/agent/tests/test_memory_auto.py` covers each rule on its own: a high score with no matching quote goes to review, a sensitive fact goes to review, replacing a stated fact goes to review, a repeat becomes active at `seen = 2`, and switching auto-approval off sends everything to review.
- [ ] **2.2 The learner uses it: `learn.py` `_facts`.**
  - **Work:** after the `same`/`replaces`/`adds` choice, `decide` sets the state: `add_fact(..., state="active")` for `auto`, otherwise proposed. Each auto-approved fact is logged with op `fact_auto` by `learner`, with its confidence and quote in the log entry, and `MemoryStore.undo` turns it back into a proposal. A new entity that comes with an auto-approved fact is made active with it (the path `set_state` already takes for approvals).
  - **Indexing:** auto-approved facts are sent to the embed mod's `memory` collection like approved ones (`index.py`).
  *Done when:* `test_memory_learn.py` (scripted model) checks that a grounded, confident, non-sensitive fact is active with a `fact_auto` log entry, that undoing it leaves it proposed, and that the other facts in the same pass stay proposed.
- [ ] **2.3 Review shows both lists: `services/agent/ui/memory.js` `memoryReview`.**
  - **Needs your look:** the proposals, as now, each with a short reason it is waiting ("sensitive: health", "not sure: 0.55", "would change something you said").
  - **Learned on its own (last 14 days):** the auto-approved facts, newest first, each with the date, the chat link, the quote, **Keep** (which clears it from this list) and **Not this** (which undoes it, so the fact is rejected). "Keep all" works per chat.
  - **Memory tab:** an inferred fact shows "learned 2026-11-05" next to it, and a stated fact shows "you said 2026-11-05".
  *Done when:* `utils/tests/web/agent-memory.test.mjs` covers both lists, the reasons, Keep and Not this.
- [ ] **2.4 Settings → Agent → Memory: `web/chat/chat-settings.js`.**
  - **Rows:** "Save what I learn without asking when I'm sure" (`auto_approve`), "How sure" (the threshold as Cautious 0.9 / Normal 0.8 / Eager 0.65), and "Always ask about" (the categories as chips).
  - **Docs:** the brief's Settings → Agent row.
  *Done when:* the settings test writes and reads `memory.json`. On the installed hub, switching the setting off makes the next learned fact wait in Review.

**Checks & deliverables — Phase 2**
- [ ] On the installed hub, a quiet chat with "I'm writing my thesis on sparse solvers, and I prefer Python over Julia" makes both facts active with a `fact_auto` entry each. The next chat's profile holds them. "Learned on its own" lists them, and Not this removes one from the profile.
- [ ] A chat with "my doctor says I should cut caffeine" leaves that fact in Review with the reason "sensitive: health".
- [ ] Delivered: `auto.py`, the learner change, both Review lists, the settings rows, and docs: architecture §14 (inferred memories become active on their own when grounded and confident; the rest wait), the structured-memory plan's §2 answer with a pointer here, and the brief.

## Phase 3 — Dates and changing interests (M)

- [ ] **3.1 When a fact was said: `learn.py`, `facts.py`.**
  - **Work:** a learned fact's `valid_from` defaults to the date of the USER message its quote was found in, read from the event's `ts`, when the model gives none. `recorded` stays the time it was saved. Each new piece of evidence (`saw`) keeps its message date, so a fact has a first date and a last date it was said (`evidence[].ts`).
  - **Interests:** add `interest` to `FACT_KINDS` (`model.py`) for what the user is into for now ("is learning HPC", "is into Blender"), apart from lasting facts. The extract prompt says when to use it.
  *Done when:* `test_memory_learn.py` checks that a fact without `valid_from` gets the message's date and that a repeat adds a later date to its evidence. `test_memory_store.py` checks that `interest` is a kind.
- [ ] **3.2 Old interests fade; new ones replace them: `tidy.py`, `profile.py`.**
  - **Profile:** `profile.build` writes each fact with its time: "(since 2026-11)", or for an interest "(2026-09 – 2026-11)" once it has been replaced. Interests are listed by the last date they were said, and an interest not said for `interest_days` (default 90) moves to a short "Earlier interests" line instead of the main list.
  - **Tidy:** an auto-learned **interest** not said or used for `interest_days` is retired on its own (logged, with Undo). Other inferred facts keep the 180-day `fade_days` proposal. A replacement keeps the old fact as retired, with `valid_until` set to the new fact's `valid_from`, so the timeline has no gaps.
  *Done when:* `services/agent/tests/test_memory_profile.py` checks that the profile shows dates, that an old interest moves to "Earlier interests", and that replacing an interest sets `valid_until`. `test_memory_tidy.py` checks that an unused interest is retired and that a stated fact is never retired.
- [ ] **3.3 The timeline: `services/agent/ui/memory.js`, the chat.**
  - **Entity page:** a **Timeline** section lists current and past facts with their spans, oldest at the bottom, each with its chat link. `memory_search` (`search.py`) gains `when="past"|"all"` so the agent can answer "what was I into last year?" from retired facts.
  - **Chat notice:** when a chat is reopened after the learner saved facts from it, a muted line under the last turn reads "Remembered: The user is learning Rust · +2 · Review". It is drawn from `GET /v1/memory/log?thread=` (a new filter on the log route) in `web/chat/` (the pane's footer area).
  *Done when:* `agent-memory.test.mjs` covers the timeline, a chat test covers the notice, and `test_memory_search.py` checks that `when="past"` finds a retired fact.

**Checks & deliverables — Phase 3**
- [ ] On the installed hub, a chat saying "I'm into Unity now, not Blender" replaces the Blender interest. The profile shows Unity with its date, and Blender's timeline shows its span. Asking "what tools was I using before?" in a new chat finds Blender.
- [ ] Delivered: the dates, `interest`, fading, the timeline, `when=`, the chat notice, and docs: architecture §14 (memory and time) and the brief (the entity page, the chat notice).

## Phase 4 — Finding it (S)

- [ ] **4.1 The header's Approvals popover: `web/Hub.dc.html` (`loadApprovals`, the popover), `web/api.js`.**
  - **Work:** the popover gains a **Memories** section under the tool approvals: "N memories wait for you — Review", linking to `#/s/agent/review`. The count is read from the agent's status stat `memory_review` (already reported by `services/agent/agent/server.py`) through `GET /api/services/agent`, refreshed when the popover opens and on the agent's status events. The badge number stays tool approvals only, because those block a running chat. When only memories wait, the badge shows a small dot instead of a number.
  - **Docs:** the brief's header section, PATCHES.
  *Done when:* `utils/tests/web/` has a header test with tool approvals, memories, both or neither. In the browser, with proposals waiting, the popover shows the Memories line and its link opens Review.
- [ ] **4.2 The sidebar entry: `web/Hub.dc.html` (the nav list, line ~1648), `services/agent/service.toml` `[ui] page` comment.**
  - **Work:** rename **Learning** to **Memory** and point it to `#/s/agent/memory`. The Memory tab opens with "You" and the count waiting in Review as its first lines, plus a link. Put the Review tab right after Memory (`page.js` `tabs`). The command palette entry says "Memory & learning".
  *Done when:* the nav test and a browser check show that the sidebar's Memory entry lands on the Memory tab with the review count.

**Checks & deliverables — Phase 4**
- [ ] A browser walk-through on the installed hub, starting from the Overview: the person can reach the waiting memories from the header and from the sidebar in one click each. Screenshots go in `docs/reference/memory-auto-2026-11/`.
- [ ] Delivered: the popover section, the renamed nav entry, the tab order, and docs: the brief, PATCHES, and `docs/structure.md` (new files: `wording.py`, `auto.py`, tests, this plan).

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Third-person wording | prompt, check and reword, the reword route | `services/agent/agent/memory/learn.py`, `wording.py`, `api_memory.py` |
| Auto-approval | grounded, confident, non-sensitive facts become active with Undo | `services/agent/agent/memory/auto.py`, `learn.py` |
| Dates and interests | when each fact was said, `interest` kind, fading, timeline, `when=` | `learn.py`, `facts.py`, `model.py`, `tidy.py`, `profile.py`, `search.py` |
| Review and Memory UI | two lists with reasons, Keep / Not this, the timeline, the settings rows | `services/agent/ui/memory.js`, `page.js`, `web/chat/chat-settings.js` |
| Finding it | the Approvals popover's Memories section, the sidebar's Memory entry, the chat notice | `web/Hub.dc.html`, `web/api.js`, `web/chat/` |
| Tests | wording, auto rules, learner, profile and tidy, search, UI | `services/agent/tests/test_memory_{wording,auto,learn,profile,tidy,search}.py`, `utils/tests/web/agent-memory.test.mjs`, the header and nav tests |
