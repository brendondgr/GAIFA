# Plan: cards mods ship for the chat (Stage P, Phases 44–49)

Asked for on 2026-10-22: make the Chat page easier to extend, and nicer to use. A mod should be able to bring its own look into the chat (a live card while its job runs, its own result card), and the agent should have better ways to show things. The user's picks from that day's discussion:
- **Mods ship chat cards** (`[ui] chat = "ui/chat.js"`), and jobs report their progress in one standard shape, including a **preview frame**, so any mod can draw a live card.
- **Live cards for image, video, 3D and speech**, after the prototype the user approved: [reference/live-cards-2026-10/prototype.html](../reference/live-cards-2026-10/prototype.html). Serve the repo root over HTTP to open it; its pictures and voice are this machine's outputs, kept local (the folder's `.gitignore`).
- **Status cards** instead of raw JSON (memory, services, model loads, "and other things too"), and **fix-it cards** when a tool fails.
- **Charts, tables and pictures in replies**, all of it, in the site's own theme: a `show` tool with a strict schema, three data sources, default views mods declare for their tools, tables that sort, filter, copy and save.
- **@-mentions** that pin a choice for one message.
- **Save to…** and Copy on every output.
- **Read replies aloud**, and a hands-free **voice mode**.

**Previews for everything** (the user, when starting the build): live image, video and 3D previews are for anything being made, not only what the agent makes. A picture queued from the comfy page, from ComfyUI's own page, over MCP or the API previews the same way, wherever AIHub shows running jobs (the Overview, the mod pages, the chat). So the live shape is part of a mod's status `jobs`, not only of a tool call, and the preview parts are a shared kit in `web/`, not chat code.

Turned down: slash commands for mods' tools ("we don't need"), and side panels of any kind (pinned output, jobs, memory and the rest). The user's one maybe: `/clear-gpu`, which natural language can do too (46.2 has both).

**How it fits:** `chat.js` already exports the registries (`registerCard`, `registerPreview`, `registerAction`, `registerStep`; brief §11.13), but only the hub's own `web/chat/` calls them. Mod UI files are already served at `/ui/services/<id>/…` (`utils/services/views.py`, `page_url`). Job progress already travels mod → hub (`utils/tools/calls.py` `_follow`, polled every 2 s) → `GET /api/tools/calls/{id}` → the agent (`agent/loop.py` `_wait_call`, a transient `progress` event) → the chat (`chat-thread.js` `live.progress`) as `{progress, note}`. This stage widens that pipe and lets mods draw what comes through it. Touches architecture §4.2 (a mod's optional extras), §4.6, §14; brief §11.12–11.13; [mods.md](../mods.md).

**Before 44.1:** the work in progress in `web/chat/` (`chat-activity.js`, `chat-cards.js`, `chat-turn.js`, `chat-settings.js`, from another session) is committed or dropped by its owner. This stage edits those files.

## Gaps

**Simple gaps (assumed):**
- **Which chat modules load:** every installed mod's that declares one, running or not, so an old chat still draws its cards while the mod is stopped. A module that fails to load is logged and skipped. Its cards then fall back to the generic ones.
- **What a module gets:** one call, `export default function setup(chat)`, with `chat = {version, registerCard, registerPreview, registerAction, registerStep, live, ui, api}`. `ui` is `chat-ui.js`'s parts (h, T, Btn, Badge, Icon…), `live` the live kit (44.3), `api` the page's client. No `registerCommand`, no `registerPanel` (declined).
- **The live shape is optional.** A job without `live` draws as today: the step row and its bar.
- **Preview frames are pulled by whatever shows them** (a card, a thumbnail), not pushed through the agent: the agent's event carries the frame's `seq` and URL, and the card fetches the image from the mod through the hub's proxy. Events stay small, and a chat that isn't open costs nothing.
- **ComfyUI's previews:** `--preview-method auto` (TAESD when its decoders are on disk, latent2rgb otherwise). Core ComfyUI previews one frame of a video. The looping clip of the prototype needs VideoHelperSuite's animated latent preview where a pack uses it; otherwise the video card loops the one frame it has.
- **The 3D card's point cloud is decoration.** gen3d sends no geometry until the shape is done, so the cloud is built in the browser from the cut-out picture's outline. The card says "Shape · n%", never that the cloud is the model.
- **Speech becomes a job** so it can report lines done and stream its audio as it's made. `tts_speak` keeps its arguments; its op moves to the job routes.
- **`hub_free_gpu`** unloads every loaded service that holds memory, or the ones named, except the model the calling chat runs on unless that is named. Same risk level as `hub_unload_service`.
- **`show`'s hub data sources** are a fixed list (46/47 name them), not any hub route, so the model can't fetch arbitrary hub data through a card.
- **Size limits for `show`:** 500 points per series and 200 rows inline; files up to 5 MB or 50,000 rows (a table pages, a chart samples). Over that, the error says how much and suggests a file.
- **Tables saved as outputs** go through `POST /api/outputs/upload` as CSV, so they get a `#n` like any other output.
- **Mentions are per message.** A mention fills that turn's calls (as a preference would, `filled` = `mention`) and is said to the model as text. It is not remembered.
- **Save to a folder** writes only where the chat may: a folder of the chat's environment at Edit or above (Nothing written outside the project root, plan Phase 27). A folder picked outside them gets 34.3's folder card, asking to allow it for this chat. Download (the browser's save dialog) and Copy need no folder.
- **Read aloud and the GPU:** tts takes the GPU slot (class `job`), and a local chat model holds it for the whole reply. So with a local model a reply is read once it's finished; with a remote model (or tts on the CPU) it's read sentence by sentence as it's written.
- **Voice mode's turn end:** 1.2 s of quiet after committed text (from the mic level and the stt stream), changeable in Settings → Agent → Voice.

**Needs a human answer:** none. The user picks the default voice for reading aloud in Settings when 49.1 lands.

---

## Phase 44 — Mod chat modules and live progress

- [x] **44.1 `[ui] chat` and the loader: `utils/manifest.py`, `utils/services/views.py`, `web/chat/chat-mods.js` (new), `chat.js`.**
  - **Manifest:** `UiSpec.chat: str | None`, validated as `page` is (a `.js` file inside `ui/`).
  - **Services view:** `chat_url` next to `page_url` (`/ui/services/<id>/<file>`), in `GET /api/services` (`utils/api_models.py`). `api.js` and the contract test (6.6) learn the field.
  - **Loader:** `loadChatModules(services, chat)` imports each `chat_url` once per page load (with the service's `updated` as a cache-buster), calls its `setup(chat)` inside a try, and keeps what each module registered so a module that throws in `setup` unregisters cleanly. `chat.version = 1`.
  - **Check:** `aihub check <id>` (`utils/services/check.py`) fails when `[ui] chat` names a missing file, and loads nothing else.
  *Done when:* `utils/tests/services/test_chat_module.py` (validation, `chat_url`, the check) and `utils/tests/web/chat-mods.test.mjs` (a module registers a card and a step, a throwing module is skipped and its partial registrations undone, a missing file is skipped).
- [x] **44.2 The live shape: `utils/tools/calls.py`, `utils/tools/api.py`, `services/agent/agent/loop.py`, `web/chat/chat-thread.js`.**
  - **A job's status may carry `live`:**
    `{"stage": "sampling", "stages": [{"id","label","state","eta_s"}], "step": 3, "steps": 8, "eta_s": 6.5, "preview": {"url": "/v1/runs/r-1/preview", "seq": 3, "w": 1184, "h": 896}, "lines": [5, 16], "audio": "/v1/speech/jobs/s-1/audio"}`. Every field is optional; `url` and `audio` are paths on the mod.
  - **The hub** keeps it on the call (`Call.live`), publishes when it changes (by `stage`, `step` and `preview.seq`, not every poll), adds it to `public()` with the mod's paths rewritten to `/api/s/<id>/…`, and caps it at 4 KB.
  - **The agent** passes `live` in its transient `progress` event, and counts it in the change key.
  - **The chat** keeps `live` on the step's `progress`.
  - **Every job, not just tool calls:** a mod's status `jobs[]` entries may carry the same `live`; the hub's status poll (`utils/services/status.py`) keeps it with paths rewritten, and `Job.live` goes out in `/api/events/recent`, `/api/overview` and the `jobs` events.
  - **Docs:** architecture §4.6 (the `live` shape), §14 (the event), brief §11.12 (`GET /api/tools/calls/{id}`), mods.md (a new "Live progress" section).
  *Done when:* `utils/tests/tools/test_live_progress.py` (a fake job's `live` reaches the call's status, paths rewritten, published on change only, capped), `services/agent/tests/test_progress_live.py`, and `utils/tests/web/chat-turn.test.mjs` (the row carries it).
  *As built:* the agent heard a job's progress only every 15 s (its poll waits for the call to end), so `GET /api/tools/calls/{id}` gained `changed=true`: with `wait`, it answers at the call's next change; the agent asks for the state at once, then each change. The status-jobs part is tested in `utils/tests/services/test_routes.py::test_status_jobs_carry_live`, the chat's in `utils/tests/web/live-progress.test.mjs`.
- [x] **44.3 The live kit: `web/live-kit.js` (new), shared by the chat, the Overview and mod pages.**
  - **The parts the prototype's four cards share**, exported to chat modules as `chat.live` and to page modules as `ctx.live`: `LiveCard` (header with icon, title, meta and the pulsing dot; the progress line; the footer with `#n`, title and actions), `Stage` (a box at an aspect ratio, at most 420 px tall, centred), `Waiting` (shimmer and grain; "Waiting for the GPU · 1 ahead · …" from the call's `note`, "Loading <model>" from `stage`), `PreviewLayers` (fetches `preview.url` when `seq` changes, fades the new frame in over the old one, then fades the result in over both), `StageChips` (✓ done · ● running with time left · ○ waiting), `usePreview(live)`, and `LiveThumb` (a small preview with the step, for lists of jobs).
  - **Theme tokens only** (`T`), so both themes work; `prefers-reduced-motion` turns the shimmer and the fades off.
  *Done when:* `utils/tests/web/live-kit.test.mjs` (the wait text from a note, the chips from `stages`, a new `seq` fetches once, reduced motion), and the prototype's look reproduced in `?mock` (44.4).
  *As built:* in Chat, live cards sit under the activity fold (`web/chat/chat-live.js` `LiveCards`, drawn by `ActivityFold`), running or done; a tool with a `live:<tool>` card keeps its outputs out of the strip (`shownLive`); a running tool without one shows `LivePreview` while its job reports a frame. Checked in `?mock` in the built-in browser.
- [ ] **44.5 Running jobs preview everywhere: `web/dashboard.js`, `web/mod-kit.js`.**
  - **The Overview's Jobs** list shows a `LiveThumb` for a running job with a preview, its step and time left; the thumbnail links to the job's route.
  - **Page modules** get `ctx.live` (the kit) and the mod's own running jobs with their `live`, so a mod page draws the same previews for runs started there.
  *Done when:* `utils/tests/web/dashboard-jobs.test.mjs` (a job with a preview, one without) and the mock's comfy job shows a thumbnail on the Overview.
- [ ] **44.4 The template, the mock and the docs: `services/_template/ui/chat.js`, `web/chat/chat-mock.js`, `docs/mods.md`.**
  - **The template** ships a small commented `ui/chat.js` (one step card using `chat.live`) and `[ui] chat` commented out in its `service.toml`.
  - **The mock** (`?mock`) plays a job with `live` (queued → loading → steps with preview frames from a bundled small image → done), so the frame is checkable without a GPU.
  - **mods.md:** "Chat cards": the `setup(chat)` contract, the lookup order (`step:<tool>` → `step`), the `live` shape, and that deleting the mod removes its cards.
  *Done when:* `aihub check _template` passes with `[ui] chat` turned on in a test copy (`utils/tests/services/test_chat_module.py`), and the mock's live card is checked in the built-in browser.

**Wire — Phase 44:** the Chat page loads mods' chat modules; a job's step row can become a live card.

**Checks & deliverables — Phase 44**
- [ ] Live: a fake mod (`utils/tests/fixtures/mods/fake-live/`) with a `ui/chat.js` and a job that reports `live`, run from a chat on a `--dev --demo-mods` hub: the card waits, steps, previews and finishes; stopping the mod leaves the finished card drawn.
- [ ] Delivered: `UiSpec.chat`, `chat_url`, `web/chat/chat-mods.js`, `web/live-kit.js`, `Call.live`, `Job.live`, the Overview's thumbnails, the template's `ui/chat.js`, the tests, mods.md's section.

---

## Phase 45 — Live cards for image, video, 3D and speech

- [ ] **45.1 Preview frames from ComfyUI: `services/comfy/bin/comfyui`, `bin/comfyui-native`, the runtime variants' launch lines, `comfy/run.py`, `comfy/api_run.py`.**
  - **Launch:** `--preview-method auto` on every launch line (`test_runtime.py`'s expected command changes with it). The setup doc says TAESD's decoders are optional and sharpen the previews.
  - **The websocket:** binary messages, event 1 (`PREVIEW_IMAGE`: 4-byte type, 4-byte format, the JPEG or PNG) and event 4 (with metadata: its `prompt_id`). The newest frame **per prompt** is kept in memory with a `seq`, for every prompt ComfyUI runs, including ones queued from ComfyUI's own page, and dropped a minute after it ends. Frames of event 1 go to the prompt that is executing.
  - **`GET /v1/prompts/{prompt_id}/preview?after=`** serves any prompt's frame; the status job of a prompt from ComfyUI's page carries `live` with it.
  - **`GET /v1/runs/{id}/preview?after=<seq>`** → the image (headers `X-Seq`, cache off), 204 when there's none newer after waiting up to 5 s.
  - **`live` on the run's status:** `stage` (queued · loading · sampling · decoding · saving, from the queue, `execution_start`, the sampler node's `progress` and the save node), `step`/`steps` from the sampler's `progress`, `eta_s` from the step rate, `preview`.
  *Done when:* `services/comfy/tests/test_preview.py`, with `fakecomfy.py` sending binary previews (both events, a frame for another prompt ignored, the long poll, 204, dropped at the end, `live` through a run).
- [ ] **45.2 The image and video cards: `services/comfy/ui/chat.js` (new), `[ui] chat` in comfy's `service.toml`.**
  - **Steps** for `comfy_generate_image`, `comfy_edit_image`, `comfy_run_workflow` and the task tools from `tools_source` (image and video tasks), using `chat.live`.
  - **Image:** the box at the call's aspect (from `aspect`/`width`/`height`, else 1:1), waiting and loading text, previews with "Step k of n", "Decoding", then the picture fades in; the footer has `#n`, the title, the workflow's name and size, and the output's actions.
  - **Video:** 16:9 (or the pack's size), the preview looping when frames are animated, a strip of 8 frames under it, "Encoding MP4", then the clip plays in the same box.
  - **The comfy page** draws its running runs with the same image and video stages (`ctx.live`).
  *Done when:* `utils/tests/web/comfy-chat.test.mjs` (aspect from arguments, the stages' words, image vs video by task) and a real run on the installed hub (45.5).
- [ ] **45.3 The 3D card: `services/gen3d/gen3d/` (job status), `services/gen3d/ui/chat.js` (new).**
  - **`live` on a job's status:** `stages` from `eta.py`'s plan (background, shape, parts, rig, preview: each with its state and `eta_s`), `stage`, and `preview` for the background step (the cut-out, `GET /v1/jobs/{jid}/preview`).
  - **The card:** the scan line that turns the input into the cut-out over a checkerboard; during the shape, a point cloud built from the cut-out's outline that turns slowly, with the cut-out small in a corner and "Shape · n%"; the four rendered views appearing one by one; then the finished preview with View in 3D (the existing viewer).
  - **The 3D page** shows a running job the same way (`ctx.live`), and the status job carries `live`.
  *Done when:* `services/gen3d/tests/test_live.py` (stages and their times, the preview route) and `utils/tests/web/gen3d-chat.test.mjs` (the chips, the outline points from a small alpha image).
- [ ] **45.4 Speech as a job, and the speech card: `services/tts/localtts/server.py`, `engines.py`, `services/tts/service.toml`, `services/tts/ui/chat.js` (new).**
  - **`POST /v1/speech/jobs`** (the body of `POST /v1/speech`) → `{id}`; **`GET /v1/speech/jobs/{id}`** with `live.lines` (done, of how many: the text split as the engine splits it) and `live.audio`; **`GET /v1/speech/jobs/{id}/audio`**: a WAV that grows while it's made (chunked), complete when done; cancel. `POST /v1/speech` stays for the Speech page and other callers.
  - **The tool:** `speak` becomes `job = true` on these routes; its arguments and result are unchanged.
  - **The card:** the waveform and the text filling in a line at a time, the line being spoken shimmering; **Play while it speaks** from the first line; finished, a waveform you click to seek with the line playing highlighted, and the output's actions.
  *Done when:* `services/tts/tests/test_speech_jobs.py` (lines, the growing audio, cancel, the old route unchanged) and `utils/tests/web/tts-chat.test.mjs`.
- [ ] **45.5 Docs and the live check.** Brief §11.13 (live cards), architecture §4.6, mods.md, each mod's README. Live on the installed hub, in the built-in browser: a Qwen-Image picture while gen3d holds the GPU (the wait, then the steps), a video pack, a TRELLIS.2 job from that picture, a spoken paragraph played while it's made; each against the prototype.

**Wire — Phase 45:** comfy, gen3d and tts steps in Chat become live cards.

**Checks & deliverables — Phase 45**
- [ ] Live: as 45.5; a mod stopped mid-job leaves an error card, not a broken one.
- [ ] Delivered: comfy's preview frames and `ui/chat.js`, gen3d's `live` and `ui/chat.js`, tts's speech jobs and `ui/chat.js`, the tests.

---

## Phase 46 — Status cards and fix-it cards

- [ ] **46.1 Default views for tools: `utils/manifest.py` (`ToolSpec.view`), `utils/tools/` (the catalog), `web/chat/chat-view.js` (new).**
  - **`view`** on a tool says how its result draws when no card is registered: `{kind = "table", rows = "jobs", columns = ["label", "state", "seconds"]}`, or a chart (`kind = "bar" | "line" | …`, `x`, `y`, `rows`), using `show`'s view names and column rules (47.1). Tools listed at runtime (`tools_source`) may carry it too. Invalid views fail `aihub check`.
  - **The card** draws with 47.2's table and chart parts; the raw JSON stays one click away.
  - **Declared at first:** `gen3d_list_jobs`, `stt_list_models`, `hub_list_models`, `lcpp_list_llms`, `vllm_list_profiles`, `relay_relay_stats`, `searxng_engines`, `hub_list_sessions`.
  *Done when:* `utils/tests/tools/test_tool_view.py` (validation, carried in the catalog) and `utils/tests/web/chat-view.test.mjs`. 46.1 lands after 47.2 if 47 is built first; otherwise 47.2's parts are built here.
- [ ] **46.2 New hub tools: `utils/tools/hub_tools.py`, `web/chat/chat-composer.js`.**
  - **`hub_gpu_status`** (`GET /api/gpu`: the holder, the queue, each wait's time), **`hub_doctor`** (`GET /api/doctor`), **`hub_free_gpu({services?})`** (unloads as in the gaps; the result lists what was freed and how much).
  - **`/clear-gpu [service…]`:** one built-in slash command (the user's maybe) that runs `hub_free_gpu` as a user call.
  *Done when:* `utils/tests/tools/test_hub_status_tools.py` (new: the three tools, the chat's own model kept), `utils/tests/web/chat-composer.test.mjs` (the command).
- [ ] **46.3 The hub's status cards: `web/chat/status/` (new: `memory.js`, `services.js`, `gpu.js`, `jobs.js`, `doctor.js`).**
  - **Memory** (`hub_memory_status`): one bar per pool (Phase 36), what's loaded with its size, **Unload** on each. **Services** (`hub_list_services`): each mod's logo, state colour and memory, **Start**/**Stop**. **GPU** (`hub_gpu_status`): the holder and the queue in order, with times, **Cancel** on waits. **Jobs** (`hub_job_status`): its state, progress and stages. **Doctor** (`hub_doctor`): passes folded, problems open with their fix. **Free GPU** (`hub_free_gpu`): what was freed.
  - **Buttons call the hub's routes directly** (the user is acting, not the agent) and refresh the card; Stop and Unload of something in use ask first.
  *Done when:* `utils/tests/web/status-cards.test.mjs` (each card from a recorded result, the buttons' calls, the confirm).
- [ ] **46.4 The mods' status cards, in their `ui/chat.js`.**
  - **Model loads** (`vllm_load_llm`, `lcpp_start_llm`): a live card through 44.2 (vLLM's stages: starting container, loading weights, compiling, capturing graphs, allocating KV cache, warming up; lcpp's load progress), with the memory it takes. vllm and lcpp report `live` on their load status.
  - **Instances** (`lcpp_list_instances`, `vllm_engine_status`): each with its state, memory, speed and Stop. **Voices** (`tts_list_voices`): each with Play sample. **Workflows** (`comfy_list_workflows`): each pack's task, model and whether its models are on disk. **Git** (`workspace_git`): the branch and the changed files.
  *Done when:* each mod's `utils/tests/web/<mod>-chat.test.mjs`, and vllm's and lcpp's tests for `live` on load.
- [ ] **46.5 Fix-it cards: `utils/tools/fixes.py` (new), `calls.py`, `web/chat/chat-fix.js` (new).**
  - **The hub adds `fixes`** to a tool's error: `[{label, call: {tool, arguments}} | {label, retry: {arguments}}]`, and `log` (the mod's last lines around the failure, from `GET /api/services/{id}/logs`, the lines that name the error marked):
    - `service_not_running` → Start <mod>;
    - `needs_room` → the memory plan's unloads, then Retry;
    - `job_failed` that reads as out of memory → Retry with the lighter preset (from the tool's `preset` choices);
    - `mod_error` / `upstream_error` → Restart <mod>, then Retry;
    - `tool_unavailable` → how to set it up (`aihub setup <mod>`).
  - **The card:** the failed step opens to the cause in a sentence, the log lines, and the fixes as buttons; a fix runs as a user call, then Retry re-runs the call with the same arguments. The agent sees the same `fixes` and may use them.
  *Done when:* `utils/tests/tools/test_fixes.py` (each code's fixes, the log excerpt) and `utils/tests/web/chat-fix.test.mjs`.
- [ ] **46.6 Docs and the live check.** Brief §11.12–11.13 (the new hub tools, `view`, `fixes`), mods.md (`view`), architecture §14. Live: memory and services cards with Unload and Start; a vLLM load card; a job on a stopped mod → Start → Retry; `/clear-gpu`.

**Wire — Phase 46:** status results and errors in Chat draw as cards with actions.

**Checks & deliverables — Phase 46**
- [ ] Live: as 46.6.
- [ ] Delivered: `ToolSpec.view`, `chat-view.js`, the three hub tools and `/clear-gpu`, `web/chat/status/`, the mods' status cards, `utils/tools/fixes.py`, `chat-fix.js`, the tests.

---

## Phase 47 — `show`: charts, tables and pictures in replies

- [ ] **47.1 The `show` tool: `services/agent/agent/show.py` (new), `local.py`, the harness's tool text.**
  - **Arguments:** `view` (`line` · `area` · `bar` · `hbar` · `donut` · `heatmap` · `kpi` · `table` · `image` · `gallery`), `title`, `caption`, and the data, one of:
    - **inline:** `{x: [...], series: [{name, values, unit?}]}` for charts, `{columns, rows}` for tables, `{items: [{label, value}]}` for donut and kpi;
    - **a file:** `source: "#5"` (a CSV or JSON output, or a workspace file the chat may read) with `x`, `y: [columns]` or `columns`;
    - **the hub:** `source: "hub:gpu_memory" | "hub:memory" | "hub:outputs_per_day" | "hub:job_times" | "hub:mod_stat"` with `range` (`1h` · `24h` · `7d` · `30d`) and, for `mod_stat`, `mod` and `stat` (from `/api/metrics/series`, `/api/outputs/stats`, `/api/jobs/stats`);
    - **outputs:** `outputs: ["#1", "#3"]` for `image` and `gallery`.
  - **Checks** before anything shows, each error naming the field and the fix as hub tool errors do: lengths match, numbers are numbers, columns exist (the file is read to check), limits (the gaps), a `#n` is in this chat.
  - **The result** is the checked spec (the event the card draws) and, for the model, a one-line summary ("Shown: a line chart of 3 series, 48 points"), never the data back.
  *Done when:* `services/agent/tests/test_show.py` (each view, each source, each error's field and fix, limits).
- [ ] **47.2 The card: `web/chat/chat-show.js` and `web/chat/chat-table.js` (new).**
  - **Charts** with `web/charts.js` (`LineChart`, `AreaChart`, `BarChart`, `HBarChart`, `Donut`, `Heatmap`, `KpiTile`) and its frame: the site's series colours, tooltips, "View as table", loading and error states. Hub sources load through `api.js` and refresh every 30 s while on screen.
  - **Tables:** sort by a column, a filter box, 50 rows a page, **Copy as CSV**, **Save as output** (a CSV through `POST /api/outputs/upload`; the card then shows its `#n`).
  - **Pictures:** `image` and `gallery` use the preview registry (an image, a video, audio, a 3D model), a gallery as a grid that opens one large.
  *Done when:* `utils/tests/web/chat-show.test.mjs` and `chat-table.test.mjs` (each view from a spec, sorting, filtering, CSV, the save call).
- [ ] **47.3 Pictures inside the reply's text: `web/chat/chat-md.js`.**
  - **`![caption](#n)`** (or `output:<id>`) of an output of this chat draws that output in the reply where it's written, at most 360 px tall, with its caption; any other image source stays as text (no outside images). The output stays in the turn's strip too.
  *Done when:* `utils/tests/web/chat.test.mjs` (a picture, a video, a reference from another chat left as text, an `https:` image left as text), and `quote.test.mjs` (quoting a reply with a picture gives back its markdown).
- [ ] **47.4 Teaching the agent, and the eval: `services/agent/harness/`, `services/agent/evals/`.**
  - **The tool's text and the harness** say when to use it: numbers worth comparing → a chart; a list with several fields → a table; outputs worth seeing together → a gallery or a picture in the text; a file's data → `source`, never copied numbers.
  - **Eval tasks:** chart a CSV output's columns; table of gen3d's jobs; GPU memory over the last day; a gallery of the chat's pictures.
  *Done when:* `services/agent/tests/test_evals.py` covers the new tasks, and a live eval run is recorded in [agent-eval.md](../agent-eval.md).
- [ ] **47.5 Docs and the live check.** Architecture §14 (the local tool), brief §11.13 (the show card, pictures in replies). Live: each view once, a table saved and used as `#n` by the next turn, a picture placed in a reply.

**Wire — Phase 47:** charts, tables and pictures in the agent's replies.

**Checks & deliverables — Phase 47**
- [ ] Live: as 47.5, in both themes.
- [ ] Delivered: `agent/show.py`, `chat-show.js`, `chat-table.js`, pictures in `chat-md.js`, the eval tasks, the tests.

---

## Phase 48 — @-mentions and Save to…

- [ ] **48.1 What can be mentioned: `utils/manifest.py` (`AgentSpec.mentions`), `utils/routes/` (`GET /api/mentions`).**
  - **Mods declare kinds:** `[[agent.mentions]] kind = "voice", list = "GET /v1/voices", label = "name", fills = ["speak.name"]` (tts); `workflow` (comfy: fills the image tools' `workflow`); `engine` (gen3d: `make_3d.engine`).
  - **Built in:** `output` (this chat's `#n`, then the outputs index by name and meaning) and `folder` (the chat's environment's folders).
  - **`GET /api/mentions?q=&kind=&chat=`** → `[{kind, id, label, sub, fills}]`, at most 20, each kind's list cached for 30 s.
  *Done when:* `utils/tests/tools/test_mentions.py` (declared kinds, validation of `fills` against the tool's parameters, the built-ins, the search).
- [ ] **48.2 The picker: `web/chat/chat-mentions.js` (new), `chat-composer.js`.**
  - **`@`** in the message box opens a list grouped by kind, narrowed as you type (`@voice:Bre`, `@#3`); a pick becomes a chip in the text; Backspace removes it whole. The message goes with `mentions: [{kind, id, label, fills}]`.
  *Done when:* `utils/tests/web/chat-mentions.test.mjs` (opening, narrowing by kind, the chip, what's sent).
- [ ] **48.3 Mentions in the turn: `services/agent/agent/server.py`, `loop.py`, `utils/prefs.py`.**
  - **The agent** keeps `mentions` on the user event, says them to the model as one line ("For this message: voice = Brendon for tts_speak"), attaches mentioned outputs as attachments are, and passes the fills with that turn's calls.
  - **The hub** fills them as it fills preferences (`filled` = `mention`) when the model's call leaves them out; a call that sets another value gets a card showing both. The card's badge reads "from your message".
  *Done when:* `services/agent/tests/test_mentions.py` and `utils/tests/prefs/test_prefs.py` (a mention fills, a contradiction asks).
- [ ] **48.4 Save to…, Download and Copy: `web/chat/chat-actions.js`, `services/workspace/` (`POST /v1/save-output`).**
  - **On every output:** **Download** (`/api/outputs/{id}/file`, the browser's save dialog); **Copy** (a picture to the clipboard as PNG; other kinds copy their link); **Save to folder…**: the desktop's chooser (`POST /v1/pick-folder`, plan 43.1), then **`POST /v1/save-output {output_id, folder, name?}`**: the workspace mod fetches the file from the hub and writes it, recorded in the chat's activity with Undo. A folder the chat may not write gets 34.3's folder card.
  *Done when:* `services/workspace/tests/test_save_output.py` (written, refused outside the allowed folders, a name clash numbered, Undo) and `utils/tests/web/chat.test.mjs` (the three actions on each kind).
- [ ] **48.5 Docs and the live check.** Brief (the picker, the actions), mods.md (`[[agent.mentions]]`), the workspace README. Live: `@voice:` picks a voice and the speech uses it; `@#2` in a message; a picture saved to a folder and undone.

**Wire — Phase 48:** the `@` picker in the message box; Save to…, Download and Copy on outputs.

**Checks & deliverables — Phase 48**
- [ ] Live: as 48.5.
- [ ] Delivered: `AgentSpec.mentions`, `/api/mentions`, `chat-mentions.js`, mentions in the agent and prefs, `POST /v1/save-output`, the actions, the tests.

---

## Phase 49 — Read aloud and voice mode

- [ ] **49.1 Read aloud: `web/chat/chat-speak.js` (new), `chat-replybar.js`, `utils/settings.py`, `utils/config.py`, `chat-settings.js`.**
  - **A speaker button** in the reply bar: the reply as plain text (`chat-copy.js`'s Text only: no citations, no code blocks read out, "code block" said instead), streamed from tts (`POST /api/s/tts/v1/speech` with `stream`, not saved) and played through WebAudio as it arrives; clicking again stops. Shown only while the tts mod is installed.
  - **Settings → Agent → Voice:** `speech_output` (voice, engine, speed, read replies aloud automatically), next to `speech_input`.
  - **While a reply is being written**, the reading follows it sentence by sentence when the chat's model isn't on this GPU; otherwise it starts when the reply ends (the gaps).
  *Done when:* `utils/tests/web/chat-speak.test.mjs` (plain text from markdown, sentence splitting, the PCM player's queue, stop) and `utils/tests/settings/test_settings.py` (`speech_output`).
- [ ] **49.2 Voice mode: `web/chat/chat-voice.js` (new), `chat-composer.js`, `chat-mic.js`.**
  - **A button by the microphone** starts it: listen (the stt stream, as dictation) → after the pause the gaps name, send → read the reply aloud → listen again. Speaking while it reads stops the reading (barge-in: the mic stays open with echo cancellation). A bar over the message box shows listening · thinking · speaking, with the words so far; Escape or the button ends it.
  - **Approvals and questions** still wait on screen; voice mode says "Waiting for you on screen" and pauses.
  *Done when:* `utils/tests/web/chat-voice.test.mjs` (the state machine: turn end, barge-in, a waiting card pausing it, ending it).
- [ ] **49.3 Docs and the live check.** Brief (read aloud, voice mode), architecture §14 (`speech_output`). Live: a reply read aloud with the local model and with a remote one; three spoken turns hands-free, one interrupted.

**Wire — Phase 49:** the reply bar's speaker; voice mode in the message box; Settings → Agent → Voice.

**Checks & deliverables — Phase 49**
- [ ] Live: as 49.3.
- [ ] Delivered: `chat-speak.js`, `chat-voice.js`, `speech_output`, the tests.

---

## Order

44 first: everything else draws through it. 45 next (the approved cards). 46–49 depend only on 44 and may go in any order; 46.1 shares 47.2's table and chart parts, so whichever comes first builds them.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Chat modules | `[ui] chat`, `chat_url`, the loader | `utils/manifest.py`, `utils/services/views.py`, `web/chat/chat-mods.js` |
| Live progress | a job's `live` through the hub and the agent | `utils/tools/calls.py`, `services/agent/agent/loop.py`, `web/chat/chat-thread.js` |
| Live kit | the shared parts of a live card and `LiveThumb`, for the chat, the Overview and mod pages | `web/live-kit.js` |
| Live cards | image and video, 3D, speech | `services/comfy/ui/chat.js`, `services/gen3d/ui/chat.js`, `services/tts/ui/chat.js` |
| Preview frames | ComfyUI's previews, gen3d's cut-out, speech jobs | `services/comfy/comfy/run.py`, `services/gen3d/gen3d/`, `services/tts/localtts/` |
| Status cards | the hub's and the mods' | `web/chat/status/`, the mods' `ui/chat.js` |
| Tool views | default table and chart views for tools | `ToolSpec.view`, `web/chat/chat-view.js` |
| Fix-it cards | fixes and log lines on tool errors | `utils/tools/fixes.py`, `web/chat/chat-fix.js` |
| `show` | charts, tables and pictures in replies | `services/agent/agent/show.py`, `web/chat/chat-show.js`, `chat-table.js`, `chat-md.js` |
| Mentions | `@` kinds, the picker, fills per message | `AgentSpec.mentions`, `/api/mentions`, `web/chat/chat-mentions.js` |
| Save to… | Download, Copy, save into a folder | `web/chat/chat-actions.js`, the workspace mod's `POST /v1/save-output` |
| Voice | read aloud, voice mode | `web/chat/chat-speak.js`, `chat-voice.js`, `speech_output` |
| Tests | small, fast tests with fake mods and recorded results | `utils/tests/{services,tools,web}/`, each mod's `tests/` |
