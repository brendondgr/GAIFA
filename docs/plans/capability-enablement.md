# Plan: mods that say when they're off, and turn on from the app, the chat or your coding agent

**Asked for:** 2026-11-15 · **Status:** Planned (revised 2026-11-15 with the user's answers)

## 1. Introduction

A new user clones GAIFA, has a coding agent run the setup, and gets a working Chat. Then they ask something that needs a mod they never set up. One report: web wasn't set up, and the chat agent spent about six minutes trying to reach the web before it gave up and answered from what it knew. Nothing told the user why.

This plan fixes that in four ways.

1. **The hub knows what's off.** It learns the difference between *stopped* and *never set up*, and says so in one place every caller reads.
2. **The agent says so and stops.** It knows every tool that exists and which ones are off, stops after the first refusal, tells the user in one sentence what is missing, and can turn it on itself: start a stopped mod, turn on one that was turned off, or set up one that was never installed.
3. **Turning something on is easy, three ways:** a **Set up** button in the app, asking GAIFA's chat agent, or handing a ready-made prompt to your own coding agent (Claude Code, Codex), which follows the setup docs. All three run the same `gaifa setup`, and all three ask first and show what will be installed.
4. **The hard ones get easier.** Search works out of the box (GAIFA's own SearXNG container, or yours if you have one), Chat can use a model server you already run, and the two GPU mods (`decide`, `embed`) are tested on your machine and offer smaller models, with pointers to where such models are compared.

It touches architecture §4.3 (manifest), §4.6 (status), §5 (start), §6 (hub API), §9 (`config.toml`), §14.1 (the agent) and §14.7 (the judge), the brief §6 / §11.7, [docs/mods.md](../mods.md) §9, and builds on backend-plan Phase 23 (`gaifa setup`), Phase 26 (web and SearXNG), Phases 28 and 30 (`embed`, `decide`), Phase 47 (fix-it cards), Phase 51 (`tools_rev`), [llm-servers](llm-servers.md), [calendar](calendar.md) (main views) and [lan-access](lan-access.md) (what stays on this machine).

### 1.1 The audit (2026-11-15): what turning each one on takes today, and after this plan

There is no setup or install route in the hub and no Set up button anywhere in `web/`. Today every mod is turned on from a terminal with `gaifa setup <id>`.

| What you get | Mod | Today | After this plan |
| --- | --- | --- | --- |
| Chat | `agent` + a model it can reach | two venvs (0.4 GB) and the relay, always; asks which model. `AGENT_LLM_URL` can point elsewhere but setup never offers it and there is no key setting | Setup asks how Chat reaches a model: GAIFA's relay, or an OpenAI-compatible server you already run (Phase 6) |
| Read and fetch web pages | `web` | a venv (70 MB) | One click |
| **Web search** | `web` + a SearXNG | **by hand**: SearXNG "runs outside GAIFA", a compose file and a `settings.yml` you write (`services/web/setup/web.md`) | One click: yours is used if one answers, else GAIFA starts its own container on its own port (Phase 5) |
| SearXNG's health and settings | `searxng` | a venv (28 MB) | Set up together with `web` |
| Folders, edits, running code | `workspace` | a venv and a `podman build` of the sandbox image (1.1 GB); the host needs podman and git | One click when podman is there; when it isn't, the one `sudo` command is shown, and the coding-agent prompt is offered first |
| Auto mode's judge, page screening | `decide` | a PyTorch venv (6.6 GB) and d3-lite (1.7 GB); one model, no test unless you pass `--smoke` | Tested on your machine after install, with its speed shown; a CPU variant and smaller models where one fits (Phase 7) |
| Search by meaning | `embed` | a PyTorch venv (6.6 GB) and EmbeddingGemma 2 (1.5 GB); the code is tied to that one model at 768-d | The same test; a choice of smaller encoders; a link to where they're compared (Phase 7) |
| Other MCP servers' tools | `mcp` | a venv (0.2 GB) | One click |
| Calendar | `calendar` | a venv (0.1 GB) | One click |

Once a mod is set up it is on: `enabled` and `autostart` default to true for every mod (`utils/manifest.py:587`), a stopped mod's tools start it on first use (`utils/tools/calls.py:546`), and the agent already has `hub_start_service`. So *stopped* is handled. *Never set up* is not.

### 1.2 What goes wrong today

1. **The hub has no "not set up" state.** A mod with no venv is `stopped`, `enabled: true` (`utils/services/model.py:16`; `GET /api/services` has no `installed` field, `utils/services/views.py:15`). `ServiceManager.installed()` exists (`manager.py:263`) but only boot autostart uses it, and what it finds goes into `last_error`, which the stopped banner, the sidebar, `hub_list_services` and the agent's prompt never show.
2. **The model is handed tools that cannot work.** A never-set-up mod's tools are listed from its manifest with an empty schema and "Web is stopped; a call starts it first" (`utils/tools/catalog.py:192`, `:313`). `web_search` and `web_fetch` are `core`, so the model always has them, and the base prompt tells it to search for real-world questions (`services/agent/harness/systemprompt.md:19`).
3. **The refusal contradicts itself.** Calling one returns `tool_unavailable`, "web_search has no route", with the fix "Web is stopped; a call starts it first" (`calls.py:594`): no start is tried (the route check runs first), and the fix says to call again. The same happens to a mod that is set up but has never run.
4. **The agent never reads availability.** `available` and `why` are dropped when tools are built for the model (`services/agent/agent/tools.py:91`); the prompt lists mods as `web (stopped)` (`prompts.py:46`).
5. **Nothing stops a varied retry.** The repeat guard only counts identical arguments (`services/agent/agent/loop.py:736`); there is no count of failures in a row and no clock on a turn, only 25 steps. One error even asks for it: `searxng_failed`'s fix is "try again with a different query" (`services/web/server.py:237`).
6. **Start has no installed check.** `POST /api/services/<id>/start` on a never-set-up mod tries to launch it (`manager.py:96`) and returns "couldn't launch: can't run .venv/bin/python: No such file or directory" under the subprocess backend. Under systemd it was read from the code, not run.
7. **`gaifa setup` recommends nothing.** Its list has no pre-ticked mods (`utils/cli_setup.py:237`), and `docs/setup/hub.md`'s order table leaves out calendar, decide, embed, mcp, voice and workspace.

Most likely the six minutes were items 2 to 5 together: a tool that looks callable, an error that says to try again, and no guard for trying differently. Which state that chat was in (web never set up, or web running with no SearXNG) isn't known; step 1.1 reproduces both before anything is changed.

**What already degrades well, and stays:** without `decide`, Auto is offered disabled and cards ask (`utils/tools/judge.py:275`), and screening falls back to fixed patterns with a note to the model; without `embed`, memory and project search fall back to words; `chat_search` says it needs the Embeddings mod; the dictation mic is hidden without `stt`; a SearXNG that doesn't answer returns "tell the user … and don't retry now".

### 1.3 The Calendar question

The Calendar is in the sidebar whenever `services/calendar/ui/page.js` exists; the mod's state isn't looked at (`utils/services/views.py:46`, `web/nav/nav-model.js:77`). Opening it when the mod isn't running shows a box: **Calendar is not running · Start it to use the calendar · Start Calendar** (`web/mod-kit.js:32`). So for a *stopped* Calendar it is the graceful version. For a Calendar that was *never set up* it is the same box, and Start then fails with the raw launch error in a toast, with no word about setup. Two smaller faults: after pressing Start the box keeps saying "not running" until the mod is ready, and a page opened during a start that then fails stays on "Calendar is starting…" (`web/ModPage.dc.html:35`). Read from the code, not clicked through: Phase 3's checks do it in a browser.

## 2. Gaps & unanswered questions

Answered by the user on 2026-11-15:

- **SearXNG:** GAIFA runs its own, in SearXNG's own container image, on a port of its own (never the usual 8080). If the user already has a SearXNG answering on this machine, GAIFA connects to that and creates nothing.
- **What is required:** only the agent, and it needs a model it can reach. The relay is the usual way; a separate OpenAI-compatible server on localhost is another, and then the relay isn't needed.
- **Asking first:** setup started from the app or the agent always asks, and shows every detail the user needs: what is installed, where, how big, what is downloaded and from where, licences, commands, containers and ports.
- **The agent knows every tool,** also the ones that are off, so it can say what could be turned on. A mod that is set up and only stopped or turned off, it turns on itself.
- **`decide` and `embed`** depend on the machine: they are tested there, smaller models can be chosen, and the app points to where such models are compared (local models only): embeddings at <https://huggingface.co/spaces/mteb/leaderboard>, decision models at <https://huggingface.co/spaces/multimodalart/jev-decision-index>.
- **Your own coding agent** is a first-class way to set things up: the app and the docs offer a prompt to paste.
- **Any decision model can be the judge** (2026-11-15): the user sets up whichever decision model they want in the `decide` mod, and may make it the Auto judge and the page screener. The machine test (7.2) reports and advises; it never blocks setting a model up or choosing it, and a model that fails it, or scores low, stays selectable with the result shown next to it. The rule that stays: the judge is a decision model in `decide` with a structured answer, never a chat model through the relay, never Gemma 4 26B. d3-lite stays the default.

Assumptions:

- **Recommended set:** `workspace`, `web`, `searxng`, `decide`, `embed`, `mcp`, `calendar`, and `relay` unless Chat uses a direct endpoint. Pre-ticked in `gaifa setup`, offered together in the app, each can be left out, and a chat without one says so. About 17 GB, most of it the two PyTorch venvs.
- **GAIFA's SearXNG port:** `5200` by default (just above the mods' 5100–5199, so `gaifa new` never picks it), on `127.0.0.1` only; if it is taken at setup, the next free port up to 5209, saved in `config.toml`.
- **A SearXNG of yours that answers but refuses JSON:** the dialog asks: turn the JSON format on in yours (the `searxng` mod can, with a backup) or start GAIFA's own beside it.
- **GAIFA's container and "deleting the folder removes the mod":** the container and its image live in podman's or Docker's store, as the workspace sandbox image and ComfyUI's do. The mod's page gets **Remove GAIFA's SearXNG**, its setup doc says to press it before deleting the folder, and the doctor flags a `gaifa-searxng` container left without its mod.
- **A main view whose mod isn't on** stays in the sidebar, dimmed, and opens to a prompt: **Set up**, **Turn on** or **Start**. The sidebar's "In sidebar" switch still hides it.
- **Setup from the hub runs commands on this machine:** refused in a scheduled run and from a device on the network (`utils/lan/limits.py`), never offered at `/mcp`, never `sudo`: a host fix that needs root is shown as a command to copy.
- **Small setups** (no question, under 0.5 GB, no host problem: `mcp`, `calendar`, `web`) need no dialog: the box shows what it installs and its size, and the button is the yes.
- **A smaller embedding model** may read text only: picture, audio and video search then say they need the full model. Changing the model re-indexes everything, in the background, and says so first.
- **Which smaller models are suggested** isn't decided here: step 7.3 picks them from the two leaderboards by measuring on this machine and on the CPU.
- **A direct endpoint loses** what the relay adds: Settings → LLMs' servers and keys, the usage charts, GAIFA's GPU slot per request, and cloud models. Setup says so before the choice.
- **The harness learner** edits the agent's prompt files. The "Not available" section is built in code (`prompts.py`), outside what the learner rewrites; the new rule lines go in the base `systemprompt.md` (read `agent/harness.py` first for how a base change reaches the active version).
- **The word "capability"** already means other things in architecture §4.2 and Phase 20: the manifest field is `[agent] provides`.
- **No clock on a turn:** a 3D model or a video is minutes of honest work; the guard counts failures, not seconds.

- **The judge's threshold is per model:** 0.35 was tuned on d3-lite. An adapter may declare its own default `threshold`; one that doesn't gets 0.35, and Settings → Permissions → Auto judge says the threshold wasn't tuned for that model and lets the user change it.
- **A model needs an adapter:** `decide` reads a model through an adapter for its family (`services/decide/decide/models/`, the code pinned at one revision; no `trust_remote_code` from a download). The model question accepts any Hugging Face repository or local folder; if no adapter fits, setup says so and offers the coding-agent prompt to write one (7.3's guide), rather than refusing the choice silently.

Open: none.

## How to work this plan

One step at a time: each numbered step is one commit (`GAIFA (capability-enablement <phase>.<step>): …`) with its own tests, its docs and its tick, and leaves the hub working. Take them in order; a step names a tool from a later step only as text, never as a call that must exist: `fix.tool` names a tool only once it is in the catalog (`hub_enable_service` from 1.7, `hub_setup` from 4.1; before that the fix is the command), and until 3.6 a fix-it card with `setup` shows the command to copy. Run a phase's Checks before the next phase. The mod and CLI work of Phases 5, 6 and 7 depends only on Phase 1 and may be taken before 3 and 4 if the user asks; what they add to the dialog (3.4) and the agent's tools (4.1) waits for those steps.

## Phase 1 — The hub knows what's off, and says so (M)

- [x] **1.1 Reproduce the loop before fixing it: `services/agent/evals/missing.py`.**
  - An eval with four cases, each a real-world question ("what's the weather in Tallahassee this weekend?") on a scratch hub: (a) `web` never set up (its `.venv` absent in a fixture copy), (b) `web` set up, no SearXNG answering, (c) `web` turned off (`enabled = false`), (d) `web` whose start fails. It records, per case: steps, tool calls by name and error code, seconds, and whether the reply says web isn't available.
  - Pass (used from 2.4 on): at most 3 model steps and 1 call to the missing mod's tools after the first refusal, no `workspace_run`/`workspace_python` reaching for the network, and a reply that names what is missing and offers to turn it on (or answers from knowledge and says it couldn't check).
  - **Why:** the report is second-hand; this shows which path loops and gives the number to beat.
  *Done when:* the eval runs against today's code and its baseline (steps, seconds, calls per case) is a table in `docs/agent-eval.md`; `services/agent/tests/test_eval_missing.py` checks the scoring on recorded transcripts.
  *As built (2026-11-15):* the eval builds a scratch root per case (the agent linked from this checkout, `web` as a folder of links with its `.venv` left out, its server swapped for one that exits, or its SearXNG at a dead port; `config.toml` with ports 7078/5190/5192) and starts a hub there with `--dev`. Baseline on the remote test LLM, two runs a case: 6 of 8 within the bar, every run under 14 s; the six-minute loop didn't reproduce on this model. What did: the refused tool called again (a, d), `hub_start_service` on a mod never set up, and no reply saying why or offering to turn it on.
- [x] **1.2 One answer for "can this mod be used": `utils/services/availability.py`.**
  - `availability(mgr, svc) -> {"status", "why", "fix"}` with `status` one of `on` (ready, degraded, starting), `starts_on_use` (stopped, set up, enabled), `off` (`enabled = false`), `not_set_up` (`installed()` false), `cant_run` (`mgr.unavailable(svc)`), `failed` (state `failed`, or the last start failed), `broken` (manifest errors). `fix` is `{"kind": "setup" | "enable" | "start" | "logs" | "none", "id", "command", "tool"}` (`command`: `gaifa setup <id>` and the like; `tool`: the hub tool that does it, `hub_setup`, `hub_enable_service` or `hub_start_service`).
  - `utils/services/views.py` `summary()` adds `installed` and `availability`; `utils/api_models.py`'s `Service` model too.
  - `ServiceManager` sets `last_error = "not set up: …"` whenever it finds a mod not installed (boot, rescan), not only at boot autostart.
  *Done when:* `utils/tests/services/test_availability.py`: each status from a fake mod (no command file, disabled, failed start, bad manifest, accel mismatch); the contract test and `utils/tests/web/` pass with the new fields in `web/mock.js`. Brief §6 (`Service`) and §11.7, architecture §6 updated.
  *As built:* *not set up* wins over *off* (a mod turned off and never installed needs setup first); an external mod that doesn't answer is `failed` with no fix; `fix.tool` is filled from `FIX_TOOLS`, which holds only `hub_start_service` until 1.7 and 4.1 add theirs. The brief's types are `Availability` and `AvailabilityFix` in §6 next to `ServiceSummary` (§11.7 lists methods, and no method changed). The mock computes the same answer from its own fields (`mockAvailability`).
- [x] **1.3 Start refuses what was never set up: `utils/services/manager.py`, `utils/services/discovery.py`, `utils/cli.py`.**
  - `start()` raises `409 not_set_up` ("Web isn't set up on this machine", fix `gaifa setup web`) before any launch; the rescan autostart (`discovery.py:102`) and `gaifa start all` (`cli.py:429`) skip such mods with that line.
  - A failed start records `svc.start_failed_at`; `availability` reads it.
  *Done when:* `utils/tests/services/test_start_not_set_up.py`: 409 with the code and fix, no process launched; `gaifa start all` on a fixture root prints the skip. Architecture §5 and §6 (error codes) updated.
  *As built:* `not_set_up` is checked after a broken manifest and before *turned off*; `start_failed_at` is set by every failed launch and readiness wait and cleared when the mod is ready or stopped. The `gaifa start all` check runs the CLI in-process with the hub faked, so the test never touches this machine's unit. The error codes live in the brief §6 (architecture §6 points there).
- [ ] **1.4 What each mod gives, and which are recommended: `utils/manifest.py`, `utils/setupdocs/block.py`, every `services/<id>/service.toml` and setup doc.**
  - Manifest: `[agent] provides = "search the web and read pages"`, a phrase that completes "I can't …" (optional; at most 80 characters). Setup block: `recommended = true`.
  - `provides` for every mod; `recommended` on relay, workspace, web, searxng, decide, embed, mcp, calendar (the agent is required, not recommended). `relay`, `lcpp`, `tts` and `gen3d` are submodules: the hub's change lands first, then each mod's commit and pin (docs/mods.md §10).
  - `summary()` carries `provides` and `recommended`; `services/_template/service.toml` shows the field.
  *Done when:* `utils/tests/core/test_manifest_provides.py` (parsed, too long is a manifest error) and `utils/tests/docs/test_setup_recommended.py`; `gaifa docs --check --strict` and `gaifa check <id>` pass for each mod. Architecture §4.3, docs/mods.md §2 and §9 updated.
- [ ] **1.5 Tools that say they're off: `utils/tools/catalog.py`, new `utils/tools/unavailable.py`, `utils/tools/calls.py`, `utils/tools/fixes.py`.**
  - `ToolDef.public()` adds `state` (the mod's availability status) and `turn_on` (the fix's `tool` and arguments) next to `available` and `why`; `why` for `not_set_up`, `off`, `cant_run`, `broken` reads as a sentence for a person ("Web isn't set up on this machine"). Every tool stays in the catalog whatever its mod's state: callers always see what exists.
  - A call to a tool whose mod is `not_set_up`, `off`, `cant_run` or `broken` answers at once with code `capability_unavailable`: detail "I can't search the web or read pages: Web isn't set up on this machine", fix "tell the user what is missing and offer to turn it on (`hub_setup` with id web); don't retry and don't reach for it another way". No start is tried. `utils/tools/unavailable.py` builds the error (`calls.py` is at 747 lines: nothing more goes into it than the call).
  - A mod that is `starts_on_use` with no cached route (set up, never run) is started first and its tools read again, then the call runs: the "has no route … a call starts it first" answer goes.
  - After a failed start, calls to that mod's tools fail at once for 60 s (`service_not_running`, "Web didn't start: <last_error>", fix "don't retry in this turn; tell the user (its Logs tab says why)"), so three calls aren't three 45 s waits.
  - `fixes.py`: `capability_unavailable` → `{"label": "Set up Web", "setup": "web"}` or `{"label": "Turn on Web", "service": "web", "action": "enable"}` by `fix.kind`; no Retry.
  *Done when:* `utils/tests/tools/test_unavailable.py`: each status's error and fix; a never-run mod's first call starts it and succeeds; the second call inside the cool-down doesn't start anything. `/api/tools?view=model` and `/mcp` list `state`. Architecture §14.1 (tool errors), brief §11.7 and §11.12 (fix-it cards) updated.
- [ ] **1.6 A mod may say one of its tools is off: `utils/services/status.py`, `utils/tools/catalog.py`, `services/web/server.py`.**
  - A status may carry `tools_off = {"<tool>": {"why": "…", "fix": "…"}}` (validated like `tools_rev`: known tool names, short strings). The catalog marks those tools `available: false`, `state: "off_by_mod"`, and a call answers `capability_unavailable` with the mod's words.
  - The web mod reports `search` off while its SearXNG probe fails or JSON is refused (it already probes for its status, `server.py:167`): "no SearXNG answers at <url>" with the fix "set up search: `hub_setup` with id searxng". `searxng_failed`'s fix changes from "try again with a different query" to "try once more; if it fails again tell the user".
  *Done when:* `utils/tests/services/test_tools_off.py` (parse, problems for unknown tools) and `services/web/tests/test_search_off.py` (status with and without a fake SearXNG). Architecture §4.6 and docs/mods.md (status) updated.
- [ ] **1.7 The hub's own tools and the doctor: `utils/tools/hub_tools.py`, `utils/doctor.py`.**
  - `hub_list_services` rows gain `provides`, `tools` (their names) and `availability` (`status`, `why`, `fix.command`, `fix.tool`). New `hub_enable_service` (`write`): turns on a mod that was turned off (`enabled = true`) and starts it; `hub_start_service` keeps starting a stopped one and now answers `not_set_up` with the fix for one that was never installed.
  - `gaifa doctor` gains a **What works** section: one line per mod with `provides` ("search the web and read pages: not set up · gaifa setup web"), plus the cross-mod lines (search needs a SearXNG; Auto needs `decide`; Chat needs a model that answers). A recommended mod that isn't set up is a warning, not a note (Settings → About shows it without "Show all").
  *Done when:* `utils/tests/tools/test_hub_tools.py` and `utils/tests/core/test_doctor_what_works.py`.

**Wire — Phase 1:** nothing new in the UI yet; `Service.availability` is live for Phase 3.

**Checks & deliverables — Phase 1**
- [ ] On a scratch hub whose `web` has no `.venv`: `GET /api/services` shows `availability.status: "not_set_up"`; `POST /api/tools/web_search/call` answers `capability_unavailable` in under a second; `POST /api/services/web/start` is 409 `not_set_up`; `gaifa doctor` lists it under What works.
- [ ] On the installed hub after `gaifa restart`: with SearXNG stopped by the user, `web_search` shows `state: "off_by_mod"` within a status poll, and comes back when SearXNG does.
- [ ] Delivered: `availability.py`, `unavailable.py`, `provides` and `recommended` in every mod, `tools_off`, `hub_enable_service`, the doctor's section, the baseline eval.

## Phase 2 — The agent knows, says so, and can turn it on (M)

- [ ] **2.1 The model knows every tool, and calls only those that can run: `services/agent/agent/tools.py`, `prompts.py`, `prompting.py`.**
  - `refresh()` gives function schemas for tools whose `state` is `on` or `starts_on_use` (a stopped mod's tools stay callable: the call starts it, as today). Tools in any other state are not callable, and are listed.
  - A new prompt section, **Off on this machine**, from the index: one line per mod that isn't usable, with what it gives, its tool names, the reason and the one tool that turns it on:
    `- search the web and read pages (web: web_search, web_fetch): not set up. Turn on: hub_setup {"ids": ["web"]}, after the user says yes.`
    `- keep your calendar and reminders (calendar: calendar_agenda, …): turned off in Settings. Turn on: hub_enable_service {"id": "calendar"}.`
    Left out when everything is on. The Environment line shows `web (not set up)` in place of `web (stopped)`. `find_tools` and `load_tools` answer for such a tool with its `why` and `turn_on`.
  *Done when:* `services/agent/tests/test_prompt_unavailable.py`: the section, the tool names and the schemas for a fake index with one mod in each status; a chat with everything on has no section. Architecture §14.1 updated.
- [ ] **2.2 The rule: `services/agent/harness/systemprompt.md`.**
  - "If what the user asks needs something under *Off on this machine*: a mod that is stopped, just call its tool. One that is turned off: say so and turn it on with `hub_enable_service` if the user asked for what it does. One that isn't set up: say in one sentence what is missing and offer to set it up (`hub_setup`); don't try to reach it another way (no shell, no other tool standing in). If you can still answer well without it, do, and say what you couldn't check." and "A result with code `capability_unavailable` is final for this turn unless you turn the mod on."
  - The web-search line becomes "when `web_search` is among your tools".
  *Done when:* the harness tests pass and the active version carries the lines (`services/agent/tests/test_harness.py`).
- [ ] **2.3 A guard for failures, not only repeats: new `services/agent/agent/guard.py`, `loop.py`.**
  - `guard.py` (the loop is at 793 lines: the repeat guard's three helpers move here too): `out_for_turn(events)` → the mods whose tools answered `capability_unavailable`, `tool_unavailable` or `service_not_running` since the user's message and that no `hub_setup`, `hub_enable_service` or `hub_start_service` has since turned on; a further call to any tool of such a mod is answered locally with the first error and "you already know this isn't available in this turn". `failing(events)` → true after `AGENT_MAX_FAILS` (default 4, `services/agent/service.toml`) error results in a row, whatever the tools and arguments; the next model call gets `tool_choice = "none"` and a wrap-up note listing what failed.
  - The turn's activity fold gets a plain row ("Web isn't set up") from the first refusal, with the fix-it button from 1.5.
  *Done when:* `services/agent/tests/test_guard.py`: a scripted model that calls `web_search` with five different queries is refused once by the hub and then locally, and the turn ends on the next step; four different failing tools in a row end the turn; a failure followed by a success resets the count; a mod turned on mid-turn is callable again.
- [ ] **2.4 The eval passes: `services/agent/evals/missing.py`, `docs/agent-eval.md`.**
  - Run 1.1's four cases, plus `workspace` not set up ("what's in my Documents folder?"), `decide` not set up in Auto (a card asks; the reply doesn't stall), `embed` not set up ("find the chat where we talked about X"), and `calendar` turned off ("what's on tomorrow?": the agent turns it on and answers). Results next to the baseline.
  *Done when:* every case passes 1.1's bar on the agent's default local model and on one relay cloud model if a key is set; the table is in `docs/agent-eval.md`.

**Checks & deliverables — Phase 2**
- [ ] On a scratch hub with `web` not set up, in the Chat page: a real-world question gets its answer or "I can't search the web: Web isn't set up. Want me to set it up?" within three steps, with the row and the button in the activity fold.
- [ ] The learner's gate eval (`eval <task>` chats) still passes: a chat where everything is on is unchanged.
- [ ] Delivered: `guard.py`, the prompt section and rule, the eval and its results.

## Phase 3 — Turn it on from the app, or hand it to your coding agent (L)

- [ ] **3.1 Setup as a hub job: new `utils/setup_jobs.py`, `utils/routes/setup.py`, `utils/lan/limits.py`.**
  - `GET /api/setup/plan?ids=web,decide` runs `bin/gaifa setup --plan --json <ids>` and returns everything the user must see before saying yes: per mod its `summary`, the venv or image and where it goes, `disk_gb`, `images`, each download with its source repository, size and licence, the steps as commands with their `what`, `questions`, `host` problems with their `fix` and `needs_root`, the variant chosen for this machine and whether it was tested on this kind of machine, containers and ports it will open, `unavailable`.
  - `POST /api/setup` `{ids, answers}` → 202 `{job}`: one job at a time (`409 setup_busy`). It writes the answers to `data/state/setup/answers-<job>.json` (0600, removed after), runs `bin/gaifa setup <ids> --json --answers <file>` in its own process group, sends each progress line (stderr) as a `setup` event and through `utils/live.py`, and on exit reads the report, rescans, starts each mod it set up and runs its check. Exit code 2 becomes state `needs_you` with the question or the command to run. `GET /api/setup/job` (the current or last job), `DELETE /api/setup/job` (stops the process group).
  - `POST /api/setup/test?id=decide` runs the setup block's `smoke` (real work on this machine) as a job and returns what it measured: passed or not, seconds, the device it ran on, the log.
  - The runner is injected (`SetupJobs(run=…)`) so tests use a fake `gaifa`. `limits.refused` refuses `POST`/`DELETE /api/setup*` from the network.
  - **Why the CLI and not its functions:** setup stays one process for a person, a coding agent and the app, with one log (`data/state/setup/logs/`) and one resume file.
  *Done when:* `utils/tests/routes/test_setup_jobs.py`: a plan from a fixture root; a job's events, report, rescan and start with a fake runner; `needs_you`; busy; cancel; a test job's result; refused from a network address. Architecture §6, brief §6 (`SetupPlan`, `SetupJob`) updated; the `setup` area registers as live.
- [ ] **3.2 The prompt for your own coding agent: `utils/cli_setup.py` (`gaifa setup --prompt <ids>`), `GET /api/setup/prompt?ids=`.**
  - One text, the same from the CLI, the route and the docs, with this clone's real path and the chosen mods filled in. It tells a coding agent where it is, what to read (`AGENTS.md`, the `gaifa-setup` skill in `.agents/skills/` or `.claude/skills/`, each mod's `services/<id>/setup/*.md`), and what to do: run `bin/gaifa setup --plan --json <ids>`, tell the person the size and every question, run it with their answers, hand them any `sudo` command or login step, run `bin/gaifa doctor`, and stop when the mods show under What works. It ends with what to do on a failure (`bin/gaifa report`).
  - **Why:** a person who set GAIFA up with an agent should add to it the same way, without knowing where the instructions are.
  *Done when:* `utils/tests/core/test_cli_setup_prompt.py`: the text names the path, the ids, the skill and the docs, and nothing from `config.toml`; the route returns the same text.
- [ ] **3.3 One box for a mod that isn't on: new `web/mod-off.js`, `web/mod-kit.js`, `web/ModPage.dc.html`, `web/Hub.dc.html`, the four mod pages with their own copy.**
  - `modOff(el, ctx, what)` draws by `service.availability.status`: *not set up* ("Calendar isn't set up on this machine" · what it gives · what it installs and its size · **Set up Calendar** · *or have your coding agent do it*, which opens the prompt with Copy), *off* (**Turn on**), *stopped* (**Start**), *starting* (no button), *failed* (the error, **Start** and **View logs**), *can't run* (why), *broken* (the manifest errors). `requireRunning` calls it; `services/agent/ui/page.js`, `mcp`, `searxng` and `web` drop their own versions.
  - A small setup (section 2) runs straight from the button with its progress in the box; anything with a question, a host problem or 0.5 GB and more opens the dialog.
  - `ModPage` mounts again when `availability.status` changes, not only when `up` flips; the `#/s/<id>` banner uses the same words and shows `last_error`.
  *Done when:* `utils/tests/web/mod-off.test.mjs` (each status's text and buttons, the small-setup rule, a remount on a status change). `web/PATCHES.md` entry; brief §8 (states) and §11.10 updated.
- [ ] **3.4 The Set up dialog: new `web/setup-dialog.js`, `web/api.js`, `web/mock.js`.**
  - Opens from any Set up button with one or more ids. First screen, two ways on, side by side: **Set it up here** and **Have your coding agent do it** (the prompt, Copy, and one line on why: it reads the same docs, runs the same command, and can fix what goes wrong on your machine).
  - *Set it up here:* everything from the plan (3.1) in plain words, nothing hidden behind a fold that the user must decide on: what is installed and where, sizes, downloads with source and licence, containers and ports, host problems with a command to copy and **Check again**, the questions (licence yes/no, models, values); then **Set up**; progress with the live lines; `needs_you` shows the command to run and **I ran it**; then the test (for a mod with a `smoke`: "Decisions answered in 0.2 s on your GPU") with what to do when it fails (try the CPU variant, a smaller model, or the coding-agent prompt with the log's path); done starts the mod and closes onto its page. Reopening while a job runs shows that job.
  - `api.js`: `getSetupPlan`, `startSetup`, `getSetupJob`, `cancelSetup`, `testSetup`, `getSetupPrompt`; the mock's versions.
  *Done when:* `utils/tests/web/setup-dialog.test.mjs` and the `api.js` and contract tests; a browser check on the scratch hub sets up a fixture mod start to finish.
- [ ] **3.5 Settings → Services and the Overview: `web/settings/blocks-hub.js`, `web/settings/schema.js`, `web/overview-tiles.js`.**
  - Each service row shows its status in words and the right button (Set up, Turn on, Start), and **Test on this machine** for a mod with a `smoke`; the Enabled switch reads **On**. A group on top, **Recommended for chat**, lists the recommended mods with what each gives, **Set up the rest** (one job for all that aren't set up) and **Have your coding agent do it**.
  - The Overview's Needs you tile lists recommended mods that aren't set up, once, with Set up and **Not now** (remembered in `/api/ui/store`).
  *Done when:* `utils/tests/web/settings-blocks.test.mjs`, `overview-tiles.test.mjs`.
- [ ] **3.6 The sidebar and Chat: `web/nav/nav-model.js`, `web/chat/chat-forms.js`, `chat-header.js`, `chat-speak.js`, `chat-composer.js`.**
  - A main-view entry whose mod isn't `on` or `starts_on_use` is dimmed with its reason as the tooltip; it still opens (to 3.3's box).
  - A fix-it button with `setup` opens the dialog; with `action: "enable"` it turns the mod on.
  - Auto's disabled reason reads "Decisions isn't set up" (from `availability`), with Set up, in place of the raw URL error (`utils/tools/judge.py` `status()` adds the availability). Read aloud is hidden unless `tts` is `on` or `starts_on_use`; the tool groups menu shows each group's state and no longer says "Loading the tool catalog…" for an empty list.
  *Done when:* `utils/tests/web/nav.test.mjs`, `approvals.test.mjs` (the fix-it buttons), `modes.test.mjs`.

**Wire — Phase 3:** the `setup` area goes live; every mod page, the Services list, the sidebar and Chat's fix-it cards read `availability`.

**Checks & deliverables — Phase 3**
- [ ] **The Calendar, in a browser on a scratch hub**, in each state: never set up → the entry is dimmed, the page says "Calendar isn't set up" with **Set up Calendar**, one click installs it and the page opens; turned off → **Turn on**; stopped → **Start**, and the box changes to "starting…" and then the page; a failing start → the error with **View logs**. The same for `mcp`. Screenshots in `docs/reference/capability-enablement-2026-11/`.
- [ ] On a fresh clone (the Phase 23 fresh-clone check): `gaifa setup agent`, open the app, set up `web` and `workspace` from Settings → Services without a terminal; on a machine without podman the dialog shows the install command and the coding-agent prompt.
- [ ] The coding-agent prompt, pasted into Claude Code in a fresh clone (the user's, or a fresh session here): it sets up `web`, `searxng` and `workspace` and reports What works.
- [ ] From a phone on the network (the user's): the Set up button says to do it on the GAIFA machine.
- [ ] Delivered: the setup routes and job, the prompt, `mod-off.js`, `setup-dialog.js`, the Services and Overview changes.

## Phase 4 — Turn it on by asking (M)

- [ ] **4.1 The hub's tools: `utils/tools/hub_setup_tools.py`, registered beside `hub_status_tools.py`.**
  - `hub_setup_plan` (`read`): `{ids}` → the plan in words the model passes on in full: what it gives, what is installed and where, size, downloads with source and licence, minutes, containers and ports, questions, host problems.
  - `hub_setup` (`execute`, `mcp = false`): `{ids, answers?}` → starts 3.1's job and follows it as a job tool (`job_status`, cancel). Its card shows the same details as the dialog, with the questions as fields; it asks in every mode but Bypass, is refused when `origin.unattended`, and `needs_you` comes back as a result that tells the model what the user must run.
  - `hub_setup_test` (`read`): runs a mod's test on this machine and returns what it measured.
  *Done when:* `utils/tests/tools/test_hub_setup_tools.py`: the plan's text; the card's fields; a job followed to its report with the fake runner; refused unattended; absent from `/mcp`.
- [ ] **4.2 The agent's skill: `services/agent/harness/skills/turning-things-on/SKILL.md`.**
  - Stopped: call the tool, or `hub_start_service`. Turned off: `hub_enable_service`. Not set up: `hub_setup_plan`, tell the user everything it will do, ask the plan's questions, `hub_setup`, then `hub_setup_test` and say what works now and what still needs them. When a step needs the user's hands (a `sudo` install, a login), give the exact command, and offer the coding-agent prompt (`gaifa setup --prompt`) as the easier way. Named in the Off on this machine section's lines.
  *Done when:* the skill loads (`services/agent/tests/test_skills_files.py`), and `evals/missing.py` gains "turn on web search for me" (dry-run setup): plan, card, job, a reply that says what works.

**Checks & deliverables — Phase 4**
- [ ] On the scratch hub, in Chat: "what's the weather…" → "I can't search the web: Web isn't set up. Want me to set it up?" → "yes" → the card with the plan → Allow → progress → the question answered.
- [ ] Delivered: the three tools, the skill, the eval case.

## Phase 5 — Search out of the box: yours, or GAIFA's own SearXNG (M)

- [ ] **5.1 Find the user's SearXNG first: `services/searxng/searx.py`, `services/searxng/server.py`.**
  - `POST /v1/detect` already looks at `SEARXNG_URL`, `127.0.0.1:8080` and `:8888`, and a container whose image is `searxng/*`. It gains a `port` argument (the dialog's "mine is on port …") and returns one of `yours` (answers, JSON on), `yours_no_json` (answers, JSON refused), `none`, with the URL and the container it found. The choice is saved in `data/state/searxng/source.json` (`{"source": "yours" | "managed", "url"}`), and `GET /v1/endpoint` (what the web mod reads) follows it.
  *Done when:* `services/searxng/tests/test_detect_watch.py` gains the three answers and the saved choice with fake probes.
- [ ] **5.2 GAIFA's own SearXNG: new `services/searxng/managed.py`, `services/searxng/server.py`, `services/searxng/service.toml`.**
  - `POST /v1/managed` creates and starts a container `gaifa-searxng` with the runtime from `GAIFA_CONTAINER_RUNTIME` (podman, else Docker; rootless), from SearXNG's own image pinned by digest in the setup doc, published on `127.0.0.1:<SEARXNG_MANAGED_PORT>` (default 5200; never 8080, never host networking), with its settings folder `data/state/searxng/managed/` mounted: a `settings.yml` GAIFA writes (`use_default_settings: true`, `search.formats: [html, json]`, the limiter off, a random `secret_key`). It refuses while `source` is `yours`. `DELETE /v1/managed` stops and removes the container (and the image with `?image=true`).
  - The container starts with the mod and stops with it (lifespan), and the mod's status says which SearXNG it uses and whether it answers. The existing settings tools (engines, timeouts, safe search) work on either.
  - A port taken at creation: the next free one up to 5209, saved as `[services.searxng.env] SEARXNG_MANAGED_PORT`.
  - **Why not host networking and 8080** (the user's own setup uses both): two SearXNGs on one machine must not collide, and GAIFA's must not be reachable from the network.
  *Done when:* `services/searxng/tests/test_managed.py` with a fake runtime: the create command (name, image digest, port, mount, loopback), the settings file, start and stop with the mod, refusal when yours is chosen, the port fallback, removal. Live on this machine with the user's SearXNG left running on 8080: GAIFA's answers on 5200 with JSON, and removing it leaves the user's untouched. Architecture §10 and §12 updated, and `CLAUDE.md`'s and `docs/structure.md`'s "SearXNG in Docker outside GAIFA" wording.
- [ ] **5.3 Setup asks, then does it: `services/searxng/setup/searxng.md`, `services/web/setup/web.md`, `utils/setupdocs/block.py`.**
  - `web`'s setup block gets `after = ["searxng"]`: setting up web sets up search with it.
  - `searxng`'s block: after the venv, a step runs detect; `yours` → "Using your SearXNG at <url>" and nothing is created; `yours_no_json` → a question: turn JSON on in yours, or start GAIFA's own; `none` → a question (the yes is the default): "Start GAIFA's own SearXNG? A container from SearXNG's image (<size>), on 127.0.0.1:5200, settings in data/state/searxng/managed/." A "no" leaves search off, and the report's `next` says how to connect one later. When neither podman nor Docker is installed, the host stage shows the install command and the rest of the setup goes on.
  - The block's `smoke`: one real search through the web mod returns results.
  - If the block format needs a step whose question depends on an earlier step's output, `block.py` gains `ask_if` (a command whose exit code says whether to ask); say so in docs/mods.md §9.
  *Done when:* `utils/tests/docs/test_setupdocs.py` parses both blocks; `utils/tests/core/test_cli_setup.py` covers the three paths with fake commands; `gaifa docs --check --strict` passes.
- [ ] **5.4 The app: `services/searxng/ui/page.js`, `services/web/ui/page.js`.**
  - Both pages say which SearXNG search uses (yours at <url>, or GAIFA's on 5200) with **Switch**, **Use mine on port …**, **Start GAIFA's own**, **Remove GAIFA's SearXNG**, and, while `tools_off.search` is set, a "Search isn't connected" panel with the one button that fixes it.
  *Done when:* `services/searxng/tests/test_page_state.py` (the state the page reads) and a browser check of each state on the scratch hub.

**Checks & deliverables — Phase 5**
- [ ] A fresh clone on a machine with podman and no SearXNG: Set up Web, yes to GAIFA's own, and `web_search` returns results, with no file written by hand. The doctor's What works shows search.
- [ ] This machine: setup finds the user's SearXNG on 8080 and uses it; nothing is created.
- [ ] Delivered: detect with the saved choice, `managed.py`, the two setup blocks, the pages.

## Phase 6 — Chat's model: the relay, or a server you already run (M)

- [ ] **6.1 The agent takes a direct endpoint: `services/agent/agent/llm.py`, `server.py`, `services/agent/service.toml`.**
  - `AGENT_LLM_URL` may be any OpenAI-compatible `/v1`; new `AGENT_LLM_KEY` (in `services/agent/.env`, never in `config.toml` or a log) is sent as a bearer token when set. Without the relay's facts in `/v1/models`, the agent uses what the endpoint gives and safe defaults (window from `AGENT_WINDOW`, default 8192; tools assumed; vision off), and says so on its page.
  - `GET /v1/status` gains `llm = {"url", "kind": "relay" | "direct", "answers", "models", "detail"}`, probed at most every 30 s. The model check (`server.py:453`) says "<url> doesn't serve …" for a direct endpoint.
  *Done when:* `services/agent/tests/test_llm_direct.py`: a fake OpenAI server with and without a key; a chat turn through it; the status for an endpoint that is down.
- [ ] **6.2 Setup asks how Chat reaches a model: `services/agent/setup/agent.md`, `utils/cli_setup.py`, `utils/setupdocs/block.py`.**
  - The agent's block drops `after = ["relay"]` for a first question with two answers: **GAIFA's relay** (the default: local engines, your provider keys, usage charts; adds the `relay` setup to the run) or **A server I already run** (its URL, such as `http://127.0.0.1:9090/v1`, and a key if it needs one; probed at `/v1/models` before going on, and its models are the choices for `AGENT_MODEL`). The question says what a direct endpoint doesn't get (section 2). `block.py` gains what that needs: a choice that adds a setup (`adds = ["relay"]`).
  *Done when:* `utils/tests/core/test_cli_setup.py`: both answers with a fake endpoint; the plan's JSON lists the question; a direct answer installs no relay.
- [ ] **6.3 "No model answers" is said plainly: `utils/doctor.py`, `web/chat/chat.js`, `web/settings/blocks-llm.js`.**
  - The Chat page's banner and Settings → LLMs read the agent's `llm` status: "Chat has no model: nothing answers at <url>" with the fix that fits (Start LLM Relay; add a server in Settings → LLMs; or the direct endpoint's URL to change). The doctor's What works line for Chat uses it. Settings → LLMs shows, for a direct endpoint, the URL, **Test**, and **Switch to the relay**.
  *Done when:* `utils/tests/web/settings-blocks.test.mjs` and a `chat` test for the banner's three cases; `utils/tests/core/test_doctor_what_works.py` gains the Chat line.

**Checks & deliverables — Phase 6**
- [ ] On a scratch hub with no relay and `AGENT_LLM_URL` at this machine's test server (`localhost:9090`): a chat answers, tools run, the doctor says Chat works, and Settings → LLMs shows the direct endpoint.
- [ ] Delivered: the direct endpoint with a key, the setup question, the plain "no model" messages.

## Phase 7 — `decide` and `embed` fit the machine they run on (L)

- [ ] **7.1 Where to find models: `utils/setupdocs/block.py`, `services/decide/setup/decide.md`, `services/embed/setup/embed.md`.**
  - A new block key, `[[find]]` (`label`, `url`, `note`), shown in the dialog's model question, the plan's text for the agent, `gaifa setup`'s model prompt and the generated guide. `embed`: "Embedding models compared (MTEB leaderboard)", <https://huggingface.co/spaces/mteb/leaderboard>. `decide`: "Decision models compared (JEV decision index)", <https://huggingface.co/spaces/multimodalart/jev-decision-index>. Each with the note "local models only; pick by size and score for your machine". Any mod may use the key (lcpp, tts, comfy later).
  *Done when:* `utils/tests/docs/test_setupdocs.py` parses `[[find]]` (an `https` URL, short label); the plan's JSON carries it; docs/mods.md §9 updated.
- [ ] **7.2 Tested on your machine: the two setup blocks, `services/decide/decide/server.py`, `services/embed/embed/server.py`.**
  - Each mod's `smoke` reports numbers, not only pass: seconds for the first answer and for the next ten, the device and dtype it ran on, peak memory (from the mod's status). The dialog (3.4), `hub_setup_test` (4.1) and Settings → Services (3.5) show them as one sentence ("EmbeddingGemma 2 on your GPU: 40 texts a second, 3.0 GB").
  - When the test fails or runs on the CPU though a GPU was expected, the result says which, and offers: the CPU variant (`gaifa setup <id> --accel <id>=cpu`), a smaller model (7.3), or the coding-agent prompt with the log's path. It is advice, never a gate: setup finishes, the mod stays set up, and the model stays selectable (also as the judge) with its result shown beside it.
  *Done when:* `services/decide/tests/test_smoke_numbers.py` and `services/embed/tests/test_smoke_numbers.py` with the fake models; the live smokes on this machine print the sentence.
- [ ] **7.3 Smaller models to choose: `services/embed/embed/encoder.py`, `store.py`, `settings.py`; `services/decide/decide/models/`.**
  - **embed:** the encoder stops being EmbeddingGemma-only: `EMBED_MODEL` names a folder under `data/models/embed/`, each with a small `gaifa-model.toml` (`dim`, the kinds it reads: text, image, audio, video; query and document prompts; dtype). A generic sentence-transformers text backend reads any such model; `GemmaBackend` stays for the full one. The store records the model and `dim` per collection; a different model makes a new index beside the old one, built in the background (the library, chats, the agent's `memory` collection), and search uses the old one until the new is ready. A text-only model answers picture, audio and video searches with "this needs the full model".
  - **decide:** the user may set up any decision model they want. Another model family is another adapter (`models/__init__.py`'s contract: the code read at one pinned revision), which may declare its default judge `threshold`; a model of a family that has an adapter is chosen by its repository or folder under `DECIDE_MODELS_DIR` (the mod's default named by `DECIDE_MODEL`), with no code. The model question takes any repository or folder; one with no adapter is answered with that and the coding-agent prompt to write one. `services/decide/README.md` gains "Adding a decision model": the adapter's members, the threshold, the test to copy, how to measure it. Settings → Permissions → Auto judge lists every model the mod has, each with its last test result, and any can be the judge.
  - **The suggestions:** from the two leaderboards, measured on this machine and on the CPU: for `embed`, two smaller encoders (around a third and a tenth of the size) with an open licence that run in sentence-transformers; for `decide`, one smaller model if the index has one that fits an adapter, else the doc says d3-lite is the smallest GAIFA runs and the weaker choice is the CPU variant. Each becomes a `[[suggest]]` (not `required`; the full model stays the default) with its size, what it's good for and what it gives up. `required = true` on today's models becomes a default choice: the model question lets the user pick another.
  - Settings → Agent → Memory and the Embeddings page show the model in use with **Change…** (the same model question, then the re-index with its progress).
  *Done when:* `services/embed/tests/test_models.py`: two fake models of different `dim`, a switch that keeps search working during the re-index, a text-only model's answer for a picture search; `services/decide/tests/test_adapters.py` for any new adapter; `docs/embed-models.md` holds the measurements (model, size, speed on GPU and CPU, a small retrieval score on GAIFA's own fixture set). Architecture §14 (embed) updated.
- [ ] **7.4 The judge on a weaker machine: `utils/tools/judge.py`, `services/agent/evals/judge/run.py`.**
  - The judge is whichever decision model the user picks (section 2): `[agent.judge] model` takes any model id the `decide` mod lists, its `threshold` defaults to the adapter's (else 0.35), and a model the judge eval hasn't measured shows "not tuned for this model". On a machine where `decide` runs on the CPU, the judge's budget (`X-GAIFA-Answer-Within`) is set from the measured speed (7.2) so Auto doesn't fail closed on every call, and Settings → Permissions → Auto judge shows the measured time per judgement.
  *Done when:* `utils/tests/tools/test_judge.py` gains the budget from a measured speed, a non-d3-lite model id accepted as the judge with its adapter's threshold, and a fake model that failed its test still selectable; the judge eval's table has a CPU row.

**Checks & deliverables — Phase 7**
- [ ] On this machine: Set up Embeddings with a smaller encoder from the dialog, the test's sentence, a search by meaning that works, then **Change…** to the full model with the re-index running in the background.
- [ ] With `--accel decide=cpu` on a scratch hub: the test reports the CPU time, and Auto in a chat judges a `web_fetch` inside its budget.
- [ ] Delivered: `[[find]]`, the measured tests, embed's model choice with re-indexing, the decision-model guide, `docs/embed-models.md`.

## Phase 8 — A recommended set, docs an agent can follow, and the guide (M)

- [ ] **8.1 `gaifa setup` recommends: `utils/cli_setup.py`, `utils/cli_setup_run.py`, the `gaifa-setup` skill (both trees).**
  - With no targets, the list opens with **Recommended for chat** pre-ticked (Enter takes them) and the rest below; `gaifa setup --recommended` takes them without the list; the plan's JSON names `recommended`, and the report's `next` lists recommended mods left out, with what a chat loses without each. The skill tells an agent to offer the recommended set first, to pass every question on, and to run the tests (`--smoke`) for `decide` and `embed`.
  *Done when:* `utils/tests/core/test_cli_setup_recommended.py`; the skills test (the two trees identical).
- [ ] **8.2 Setup docs an agent can follow start to finish: `docs/mods.md` §9, `utils/setupdocs/render.py`, every recommended mod's `services/<id>/setup/*.md`.**
  - The setup-doc format gains two required sections for recommended mods: **Check** (the exact command and the output that means it worked) and **When it fails** (a table: what you see → what to check → the fix, each a command). `gaifa docs --check --strict` fails a recommended mod without them.
  - Rewritten to that standard, with nothing left to guess: `web` (pages, then search), `searxng` (yours or GAIFA's, the port, JSON, the `docker` group or podman), `workspace` (podman present or not, the image build, the sandbox's own check), `decide` and `embed` (the variant for each kind of GPU, the test, the smaller models), `mcp`, `calendar`, `agent` (the relay or a direct endpoint). Each opens with one line: "The easy way: paste `gaifa setup --prompt <id>`'s text into your coding agent."
  *Done when:* `utils/tests/docs/test_setupdocs.py` checks the two sections for recommended mods; `gaifa docs --check --strict` passes; a fresh coding-agent session given only the prompt sets up `web`, `searxng` and `workspace` in a fresh clone without asking where things are (Phase 3's check, run again against the new docs).
- [ ] **8.3 The guide: new `docs/turning-things-on.md`, `utils/setupdocs/render.py`, `docs/setup/README.md`, `docs/setup/hub.md`, `README.md`, `AGENTS.md`.**
  - One page for a person or an agent: a table made by `gaifa docs` (mod, what it gives, recommended, size, what a chat does without it, the command, where to find models), then by hand: the three ways on (your coding agent first, with the prompt; the app; asking GAIFA's agent), turning one off, what "not set up", "off", "stopped" and "failed" mean, search (yours or GAIFA's), Chat's model (the relay or your own server). `README.md`'s setup section and `AGENTS.md` point to it and show the prompt; `hub.md`'s order table gains calendar, decide, embed, mcp, voice and workspace; relay's setup `after` matches its manifest.
  *Done when:* `gaifa docs --check --strict` passes with the generated table; the docs tests pass. `docs/structure.md`, `CLAUDE.md` (status; the SearXNG line) updated.

**Checks & deliverables — Phase 8**
- [ ] A fresh clone set up by an agent following the `gaifa-setup` skill ends with the recommended set on and tested, or with the report naming what was left out and why.
- [ ] Delivered: the recommended list in the CLI, the setup docs' two sections, `docs/turning-things-on.md`.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Availability | one status, reason and fix per mod, in the API | `utils/services/availability.py`, `utils/services/views.py` |
| Refusals | `not_set_up` on start, `capability_unavailable` on a call, the cool-down | `utils/services/manager.py`, `utils/tools/unavailable.py`, `utils/tools/fixes.py` |
| `tools_off` | a mod says one tool is off (search without SearXNG) | `utils/services/status.py`, `utils/tools/catalog.py`, `services/web/server.py` |
| `provides`, `recommended`, `[[find]]` | what a mod gives; which are recommended; where to find models | `utils/manifest.py`, `utils/setupdocs/block.py`, each mod |
| The agent's guard | every tool known, off ones listed with how to turn them on, the failure guard | `services/agent/agent/tools.py`, `prompts.py`, `guard.py`, `harness/systemprompt.md` |
| Setup from the hub | plan, job, test, events, cancel, the coding-agent prompt | `utils/setup_jobs.py`, `utils/routes/setup.py`, `utils/cli_setup.py` |
| The app | the box, the dialog, Services, Overview, sidebar, fix-it buttons | `web/mod-off.js`, `web/setup-dialog.js`, `web/settings/blocks-hub.js`, `web/nav/nav-model.js`, `web/chat/` |
| Asking the agent | `hub_setup_plan`, `hub_setup`, `hub_setup_test`, `hub_enable_service`, the skill | `utils/tools/hub_setup_tools.py`, `utils/tools/hub_tools.py`, `services/agent/harness/skills/turning-things-on/` |
| Search | yours found and used, or GAIFA's own container on its own port | `services/searxng/managed.py`, `searx.py`, both setup docs and pages |
| Chat's model | a direct OpenAI-compatible endpoint with a key, the setup question, "no model" said plainly | `services/agent/agent/llm.py`, `server.py`, `services/agent/setup/agent.md` |
| Models that fit | measured tests, embed's model choice with re-indexing, the decision-model guide | `services/embed/embed/`, `services/decide/`, `docs/embed-models.md` |
| The CLI and guide | the recommended set, the doctor's What works, setup docs to one standard, the guide | `utils/cli_setup.py`, `utils/doctor.py`, `services/*/setup/`, `docs/turning-things-on.md` |
| The eval | missing-mod cases, baseline and after | `services/agent/evals/missing.py`, `docs/agent-eval.md` |
| Tests | small, fast tests with fake mods, a fake setup runner, a fake container runtime and fake models | `utils/tests/core/`, `utils/tests/services/`, `utils/tests/tools/`, `utils/tests/routes/`, `utils/tests/docs/`, `utils/tests/web/`, `services/agent/tests/`, `services/web/tests/`, `services/searxng/tests/`, `services/embed/tests/`, `services/decide/tests/` |
