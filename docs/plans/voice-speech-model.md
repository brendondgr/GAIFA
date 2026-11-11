# Plan: voice mode on a speech-to-speech model (LFM3-Omni-2B), with a switch back to the pipeline

**Asked for:** 2026-11-11 · **Status:** In progress

## 1. Introduction

Voice mode today (plan [chat-cards](chat-cards.md) 49.2) is a pipeline run by the page: the stt mod writes down what you said, the chat's model answers as text, and the tts mod reads the answer. It works with any chat model and all its tools, but every turn waits for three models in a row, and with a cloud chat model the words leave the machine. The user asked (2026-11-11) for a second engine: a speech-to-speech model that hears and speaks itself, running locally, chosen with a switch in Settings. The model is [LiquidAI/LFM3-Omni-2B](https://huggingface.co/LiquidAI/LFM3-Omni-2B) from its [GGUF repository](https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF), tried at both Q4_K_M and Q8_0.

What the model's pages say (read 2026-11-11; Phase 1 checks each on this machine): 2.17 B parameters; 16 kHz audio, text, images and video in; text, 24 kHz speech, or text and speech interleaved out; 32K context; speech in 19 languages; two voices (female, male); tool calls; no reasoning (`--reasoning off`); LFM Open License v1.0. It runs in llama.cpp **v0.8.0 (b11960) or newer**, whose server has a realtime WebSocket, `/v1/realtime`, in OpenAI's realtime schema (PCM16 mono in and out, `output_modalities`, `response.cancel`, tool calls), and `POST /tts`. GGUF sizes: Q4_K_M 1.1 GB, Q8_0 1.85 GB, plus `mmproj-LFM3-Omni-2B-Q8_0.gguf`. Liquid's own numbers put its tool calling below Gemma 4 E4B (52 against 72), so it is a small model that talks, not a replacement for the chat agent.

**The approach: a new mod, `voice`, not a part of lcpp.** The reasons:

- lcpp's llama.cpp is b11445, older than the model needs. Upgrading it changes the build under every chat model; a mod with its own pinned build can't break them, and is removed by deleting its folder.
- lcpp's models are chat models: one instance each, published to the relay, reached as `/v1/chat/completions`. A voice session is a WebSocket with audio both ways. The hub proxies WebSockets to a mod (`utils/proxy.py` `proxy_ws`), not to lcpp's instances on 7071–7199.
- Voice needs things lcpp has no place for: finding the end of your turn, writing the conversation into the chat, a tool allow list, an idle unload, the Q4/Q8 comparison.
- lcpp is its own repository (two commits per change); the voice mod is GAIFA's.

Using Omni as a small chat or vision model in lcpp stays possible later (a catalog entry once lcpp's build is new enough) and is not part of this plan.

Phase 1 proves the model on this machine before anything is built. Phase 2 builds the mod. Phase 3 wires it into the Chat page and adds the switch. Phase 4 compares Q4_K_M and Q8_0. Phase 5 (optional) gives it tools and a hand-off to the chat's own model. Touches architecture §2 (ports), §9 (`[voice_mode]`), §14.1 (speech), the brief §4.5, §6.4, §11.13, [chat-cards](chat-cards.md) Phase 49 (today's voice mode, which stays), backend-plan Phase 29 (stt) and [llm-servers](llm-servers.md) (lcpp, unchanged).

## 2. Gaps & unanswered questions

- **Own mod or lcpp** (the user asked which is better): own mod, for the reasons above.
- **Replace the pipeline, or keep both** (answered in the request): both stay, with a switch. *Assumption:* the default stays the pipeline (`engine = "chat"`) until Phase 3's checks pass; then the user flips it in Settings. The example config keeps `"chat"`, since a new install has no voice mod.
- **Who answers in speech-model voice mode.** *Assumption:* LFM3-Omni answers by itself, whatever model the chat's menu shows; the chat's model and its tools aren't used while voice mode is on (Phase 5 adds a few tools and a hand-off). What was said is written into the chat as normal user and assistant messages, so the chat's model sees it once you type again.
- **What the model knows about the chat.** The last turns of the chat as text (up to 6,000 tokens of the 32K), the memory profile and *Your calendar* from the agent's prompt, and the project's instructions if they fit in 2,000 tokens. *Found in Phase 1:* a session takes no assistant items, so the history goes into the session's instructions as a transcript (the model answered from it).
- **llama.cpp's build.** Pinned at **b12292** (sha256 `01a6e2a7…fa8e7` for `ubuntu-vulkan-x64`). The mod has its own copy in `services/voice/runtime/llama.cpp/` (the Vulkan release tarball, pinned with a sha256, as lcpp does), about 100 MB. `VOICE_LLAMA_BIN` may point at another build. Not shared with lcpp, so either can be updated alone.
- **Does speech output run on Vulkan (RADV, Radeon 8060S)?** *Found in Phase 1:* yes. First audio about 90 ms after you stop (Q4_K_M) and 120 ms (Q8_0), speech made 4–5× faster than real time ([docs/voice-spike.md](../voice-spike.md)).
- **End of your turn.** *Found in Phase 1:* llama.cpp's realtime has no turn detection, so the mod's bridge does it: Silero VAD on the CPU (the mod's own copy of the ONNX model, fetched at install; an energy gate when it is missing), ending a turn after `speech_output.pause_ms` of quiet (the row that exists, default 1200 ms).
- **Your words as text.** The chat needs them. *Found in Phase 1:* a conversation session sends no transcript, but a second session on the same server with `type: "transcription"` writes the same audio down in 0.2–0.7 s, correctly. The bridge keeps one beside each conversation; the stt mod isn't used.
- **Echo.** With speakers, the model hears itself. *Assumption:* the browser's `echoCancellation` (already on in `chat-mic.js`) plus barge-in by level as today (`bargeTracker`); headphones are the documented fix if that isn't enough.
- **Memory.** *Found in Phase 1:* about 4.3 GB (Q4_K_M) and 5.1 GB (Q8_0) with llama.cpp's defaults; the mod runs two slots of 32,768 tokens and declares `estimate_gb = 5`. Idle unload after 300 s, as stt. `[gpu] class = "interactive"`.
- **Voices and languages.** Two voices (female, male), no cloned voices: the tts mod's voices don't apply to this engine, and the Voice row says so. *Assumption:* the language follows `speech_input.language`; empty means English (American).
- **Images and video in.** Not in this plan.
- **Read aloud** (the speaker on a reply, auto-read): stays on the tts mod. Only voice mode changes.
- **Downloading the weights** (about 3 GB for both quants and the projector, from Hugging Face into `data/models/s2s/`) and the llama.cpp tarball: step 1.1 asks the user before fetching. **Needs the user's go-ahead at that step.**
- **The licence** (LFM Open License v1.0): the user's to read before use beyond personal; the setup doc links it. Nothing in GAIFA ships the weights.
- **Tools in voice mode** (Phase 5). *Needs a human answer before Phase 5:* which tools the voice may use without a card. The plan's proposal: read-only ones only (today's and tomorrow's calendar, memory recall, the time, web search), and anything that would ask is refused aloud, never a card mid-sentence. Phases 1–4 don't depend on it.

## Phase 1 — Prove it on this machine (S)

Nothing tracked changes except the report. Work in the scratch folder `data/state/voice-spike/` (gitignored).

- [x] **1.1 Fetch the build and the weights.**
  - Ask the user first (sizes, sources). Then: the llama.cpp release tarball at or after b11960 for `ubuntu-vulkan-x64` from ggml-org/llama.cpp's releases (record the tag and sha256); `LFM3-Omni-2B-Q4_K_M.gguf`, `LFM3-Omni-2B-Q8_0.gguf`, `mmproj-LFM3-Omni-2B-Q8_0.gguf` and anything else the repository's file list shows the server needs (a codec or vocoder file) into `data/models/s2s/LFM3-Omni-2B/`.
  - Note which binaries the tarball has (`llama-server`, `llama`, `llama-tts`) and which one serves `/v1/realtime`.
  *Done when:* the server starts with Q4_K_M, `--reasoning off`, `AMD_VULKAN_ICD=RADV`, and `GET /health` answers; the files and their sizes are listed in the report.
- [x] **1.2 Measure a conversation: `data/state/voice-spike/probe.py`.**
  - A throwaway client (start from llama.cpp's `examples/realtime_client.py`) that sends recorded 16 kHz speech (three clips: a short question, a long one, one in another language; made with the tts mod) and saves the reply audio.
  - Record for Q4_K_M and Q8_0, on Vulkan and with `-ngl 0`: time from end of speech to first audio, the real-time factor of speech out, RSS and GTT while talking, load time.
  - Record the protocol as it is: the events sent and received, the sample rates accepted (is 24 kHz input resampled?), `session.update` fields, whether the server detects turns, whether input transcription arrives and how good it is, whether text items can be added as history, what `response.cancel` does mid-speech, one tool call round trip, what happens at the context limit, and whether two sessions can be open at once.
  *Done when:* `docs/voice-spike.md` holds the table and the protocol notes, and says for each assumption in §2 whether it held. **The bar to go on:** first audio within 1.5 s of the end of speech and speech out faster than real time, on at least one quant. If it isn't met, stop and tell the user with the numbers.
- [x] **1.3 Settle the plan.** Edit this file's §2 and Phases 2–5 for what 1.2 found (turn detection, transcription, history, memory estimate, the pinned tag). Delete the scratch folder's server; the weights stay.
  *Done when:* no assumption in §2 is still unknown, and the user has seen the report. *As built (2026-11-11):* the user said to build the whole plan without stopping, so the report and the WAVs wait for them (`docs/voice-spike.md`, `data/state/voice-spike/out/`); the scratch folder is kept for Phase 4. Tools made no call on the one try (Phase 5).

**Checks & deliverables — Phase 1**
- [ ] The user has listened to one reply from each quant (the saved WAVs).
- [x] Delivered: `docs/voice-spike.md`, this plan updated.

## Phase 2 — The `voice` mod (M)

`gaifa new voice` (port **5110**, the next free in 5100–5199). Python, FastAPI, its own venv. Follow docs/mods.md and the `gaifa-mod` skill; `gaifa check voice` passes at the end.

- [x] **2.1 The manifest and the engine: `services/voice/service.toml`, `voice/engine.py`, `voice/config.py`.**
  - `service.toml`: `id = "voice"`, name "Voice", `[run] port = 5110`, `health = "/health"`, `status = "/v1/status"`; `[run.env]` `VOICE_MODELS_DIR = "{models}/s2s"`, `VOICE_LLAMA_BIN = "{service_dir}/runtime/llama.cpp/bin/current/llama-server"`, `VOICE_QUANT = "q4_k_m"`, `AMD_VULKAN_ICD = "RADV"` (vulkan variant); `[memory] estimate_gb = 5`, `load = "POST /v1/load"`, `unload = "POST /v1/unload"`, `triggers = ["/v1/realtime", "/v1/load"]`, `idle_unload_s = 300`, `idle_unload_env = "VOICE_IDLE_UNLOAD_S"`; `[gpu] class = "interactive"`; `[models] dirs = ["s2s"]`; `[api.responses]` none (the WebSocket isn't in OpenAPI).
  - `engine.py` `Engine`: starts and stops one `llama-server` child on a free loopback port (`--model`, `--mmproj`, `--reasoning off`, `--temp 0`, the context size, `-ngl`), waits for its health, restarts it once if it dies mid-session, and reports `{state, quant, pid, port, rss_bytes, loaded_at}`. Before a load it asks the hub for memory (`POST {GAIFA_URL}/api/memory/acquire`, as lcpp's launch does). `quant` is `q4_k_m` or `q8_0`; changing it unloads and loads.
  - Routes in `voice/server.py`: `GET /health`, `GET /v1/status` (state, quant, the models found with sizes, sessions open, `stats` for charts: turns, first-audio ms), `POST /v1/load {quant?}`, `POST /v1/unload`, `GET /v1/models`.
  *Done when:* `services/voice/tests/test_engine.py` with a fake `llama-server` (a small script answering `/health`): load, unload, a quant change, a child that dies, a missing model file answering `409 model_missing` with the fix (the setup doc's download line). `gaifa check voice` passes its manifest checks.
- [ ] **2.2 The bridge: `services/voice/voice/bridge.py`, `voice/vad.py`, `WS /v1/realtime`.**
  - The browser's protocol is the mod's own and small, so the page never depends on llama.cpp's schema. Client → mod: `{type:"start", thread?, voice, language, pause_ms, sample_rate:16000}`, binary PCM16 frames, `{type:"interrupt"}`, `{type:"stop"}`. Mod → client: `ready {sample_rate_out}`, `listening`, `heard {text}` (your turn as text), `thinking`, binary PCM16 reply frames, `said {text, final}` (the reply's text as it comes), `turn {user, assistant, first_audio_ms}` when a turn ends, `tool {name, state}` (Phase 5), `error {code, detail, fix?}`, `done`. Close codes as stt's: 4400 bad start, 4409 busy (one session at a time unless Phase 1 found more work), 4500.
  - `bridge.py` `Session`: opens llama.cpp's `/v1/realtime`, sends `session.update` (instructions "Respond with interleaved text and audio." plus the context from 2.3, `output_modalities ["audio","text"]`, the voice and language, audio temperature 0.4 and repetition penalty 1.2 where the server takes them), forwards audio, commits a turn when `vad.py` says the pause passed, sends `response.cancel` on `interrupt` (and tells the page what part of the reply was actually played out, so the chat stores what you heard), and maps server events to the mod's. A stuck response is cancelled after 60 s.
  - `vad.py`: Silero VAD (ONNX, CPU) with hysteresis, an energy gate when the model file is missing; `pause_ms` from the start message.
  - `heard {text}` comes from a second llama.cpp session (`type: "transcription"`) fed the same audio and committed at the turn's end.
  *Done when:* `services/voice/tests/test_bridge.py` against a fake realtime server (a `websockets` server in the test that plays a script): a turn end to end, an interrupt mid-reply, a second session refused with 4409, the upstream closing, a bad start. `test_vad.py` on two fixture clips (speech then quiet; noise only).
- [ ] **2.3 The chat's side: `services/agent/agent/api_voice.py`, `voice/hub.py`.**
  - Agent routes: `GET /v1/threads/{tid}/voice-context` → `{instructions, history: [{role, text}], language}` (the profile, *Your calendar*, the project's instructions when short, the last turns as text inside the token budget in §2; built from `prompting.py`/`context.py`'s existing parts, nothing new invented), and `POST /v1/threads/{tid}/voice-turn {user, assistant, model, first_audio_ms, interrupted}` → appends a `user` and an `assistant` event to the thread's log without a model call (the assistant event carries `model: "voice/lfm3-omni-2b"` and `via: "voice"`), names a new chat as any first message does, and feeds the same memory learning a typed turn does. Refused with `409 turn_running` while the chat's own turn runs.
  - `voice/hub.py`: the mod calls both through the hub (`{GAIFA_URL}/api/s/agent/…`), the first at `start` when a `thread` was given, the second on every `turn`. With no thread (the mod's own page), neither.
  *Done when:* `services/agent/tests/test_api_voice.py`: the context's shape and its budget, a voice turn appearing in `/v1/threads/{tid}/events` and in the next typed turn's prompt, the 409. `services/voice/tests/test_hub.py` with a fake hub.
- [ ] **2.4 Setup, page and docs: `services/voice/setup/llama-cpp.md`, `ui/page.js`, `gaifa-install.sh`.**
  - The setup doc with its `gaifa-setup` block: summary, steps (the venv; the pinned llama.cpp tarball with sha256 into `runtime/llama.cpp/bin/llama-<tag>` and the `current` link; variants for vulkan, cuda, mps and cpu, the last three untested), check, and model suggestions (the three files from `LiquidAI/LFM3-Omni-2B-GGUF`, Q4_K_M first, with the licence link). No machine's models in it.
  - `ui/page.js`: status (loaded or not, quant, memory), a quant select, Load / Unload, and a **Try it** box (talk to it with no chat) using Phase 3's client.
  - Docs: architecture §2 (port 5110), §10 (the mod), §14.1; `docs/structure.md`; `docs/platforms.md` (a row, untested off Vulkan); this machine's inventory through `gaifa docs`.
  *Done when:* `gaifa check voice`, `gaifa docs --check --strict` and `uv run pytest` pass; `gaifa setup voice --plan` shows the steps; on the installed hub the mod loads Q4_K_M and Overview shows its memory.

**Wire — Phase 2:** the Voice mod appears in Services and on Overview; its page loads, unloads and switches quant. Chat is unchanged.

**Checks & deliverables — Phase 2**
- [ ] Live: load, talk through the page's Try it box for five turns, interrupt one, leave it 5 minutes and see it unload; `gaifa doctor` clean.
- [ ] Deleting `services/voice/` and `gaifa rescan` leaves the hub and Chat working (voice mode falls back to the pipeline).
- [ ] Delivered: `services/voice/` (manifest, `voice/`, tests, setup doc, page), `services/agent/agent/api_voice.py`.

## Phase 3 — Voice mode uses it, with the switch (M)

- [ ] **3.1 The setting: `utils/config.py`, `utils/api_models.py`, `utils/settings.py`, `config.example.toml`.**
  - A new table, `[voice_mode]`: `engine = "chat" | "speech"` (default `"chat"`), `quant = "q4_k_m" | "q8_0"` (default `"q4_k_m"`), `voice = "female" | "male"` (default `"female"`). `VoiceModeCfg` beside `SpeechOutputCfg`; `VoiceModeSettings` in `Settings` and the PUT patch; `_shape()` and the defaults view. Saving `quant` while the mod is loaded calls its `POST /v1/load` (the hub's settings follow-up, as the judge's model pick does).
  - `speech_output.pause_ms` stays where it is and serves both engines.
  *Done when:* `utils/tests/settings/test_voice_mode.py` (defaults, a save, a bad value 422, a merge with another page's save); the contract test passes with the brief §6.4 type added; architecture §9 and `config.example.toml` updated.
- [ ] **3.2 Settings → Speech → Voice mode: `web/settings/schema.js`, `web/mock.js`.**
  - A new group `voiceMode` in the Speech section, shown when stt and tts, or voice, exist: **Voice mode uses** (segmented: "Chat model, read aloud" / "Speech model (local)"; the second disabled with "Install the Voice mod" when it's missing), and, when the speech model is chosen, **Size** (Q4_K_M "smaller, faster" / Q8_0 "closer to the original"), **Voice** (female / male) and a status line ("LFM3-Omni-2B Q4_K_M, loaded, 3.1 GB"). The hint under the switch says what changes: "The speech model answers itself, on this machine. It doesn't use the chat's model or its tools."
  - The existing Voice group's hint notes its voice and speed apply to read aloud and the chat-model engine.
  *Done when:* `utils/tests/web/settings-schema.test.mjs` (the rows, the keys, the disabled state); browser check on `?mock` and the installed hub, dark and light, 1440 and 375 px.
- [ ] **3.3 The client: `web/chat/chat-voice-live.js`.**
  - `liveVoice({thread, voice, language, pauseMs, onEvent})` → `{interrupt(), stop()}`: the microphone through `chat-mic.js`'s 16 kHz worklet and mic ranking, a WebSocket to `/api/s/voice/v1/realtime`, reply frames into `chat-speak.js`'s `PcmPlayer`, and barge-in (`bargeTracker` on the mic level while the player has audio queued → `player.stop()` and `interrupt`). It reports how much of the reply was played when interrupted.
  - `liveStep(s, ev)`: the pure state machine for this engine (`off`, `connecting`, `listening`, `thinking`, `speaking`, `error`), reusing `voiceStep`'s words where they match.
  *Done when:* `utils/tests/web/chat-voice-live.test.mjs` (the state machine; frames to the player; barge-in sends one interrupt; reconnect once on a dropped socket, then `error`).
- [ ] **3.4 The button: `web/chat/chat-voice.js`, `chat-pane.js`, `chat.js`.**
  - `VoiceButton` reads `voice_mode.engine`. `"chat"`: today's code, untouched. `"speech"` with the voice mod up: `liveVoice`; the status bar reads "Voice mode · LFM3-Omni" and shows your words and the reply's text as they arrive. Turns arrive in the chat through the agent's stream (2.3 wrote them), drawn as normal messages with a small speaker mark from `via: "voice"`.
  - While it is on: the composer's Send is as today (a typed message goes to the chat's model; voice mode pauses for that turn and resumes), auto-read is skipped, and the model menu shows "Voice: LFM3-Omni-2B" beside the chat's model.
  - Falling back: engine `"speech"` with the mod missing, failed or refused for memory starts the pipeline instead and says so once in the status bar ("The speech model isn't available: using the chat model").
  - The button shows when either engine can run (today: stt up and `speech_output` set).
  - Split panes: one voice session at a time; starting it in another pane ends the first.
  *Done when:* `chat-voice.test.mjs` extended (engine choice, the fallback, the pause for a typed turn); browser check on the installed hub: ten turns, an interruption, a typed message in the middle, a reload showing the turns in the chat, Escape ending it; the brief §11.13 (Voice mode), §4.5 and `web/PATCHES.md` updated.

**Wire — Phase 3:** Settings → Speech gains Voice mode; the Chat page's voice button talks to the voice mod when the switch says so.

**Checks & deliverables — Phase 3**
- [ ] Live on the installed hub, with a cloud model chosen in the chat: voice mode on the speech model works with the relay stopped (nothing leaves the machine); switching to "Chat model" in Settings changes an open Chat page without a reload (the `settings` event).
- [ ] Memory: with voice mode on, Overview shows the voice mod loaded and stt and tts not loaded by it.
- [ ] Delivered: `[voice_mode]`, the Settings group, `web/chat/chat-voice-live.js`, the changed `chat-voice.js`.

## Phase 4 — Q4_K_M against Q8_0 (S)

- [ ] **4.1 The comparison: `services/voice/evals/compare.py`, `evals/prompts.json`.**
  - 30 spoken prompts (made once with the tts mod, kept in `outputs/voice/eval/`, gitignored): short questions, long ones, numbers and names, two follow-ups that need the earlier turn, five in other languages, five that should call a tool (Phase 5's, skipped until then).
  - For each quant: first-audio ms (median, p90), real-time factor, memory, the word error rate of its transcription of you (against the prompt's text), how intelligible its own speech is (the stt mod's transcript of the reply against the reply's text), and the reply's text saved for reading. Runs one quant at a time through the mod's own routes; the GPU is used by nothing else during a run.
  - Reply WAVs saved in pairs, `outputs/voice/<date>/<n>-q4.wav` / `-q8.wav`, for listening.
  *Done when:* `services/voice/tests/test_compare.py` (the scoring on fixtures, no model); a real run writes `docs/voice-eval.md` with the table.
- [ ] **4.2 Pick the default.** The user listens to the pairs and reads the table; `VOICE_QUANT`'s default, `[voice_mode] quant`'s default and the setup doc's first suggestion follow their choice. The other file may be deleted from `data/models/s2s/` (the user's call).
  *Done when:* `docs/voice-eval.md` records the choice and why.

**Checks & deliverables — Phase 4**
- [ ] Delivered: `services/voice/evals/`, `docs/voice-eval.md`.

## Phase 5 — Tools and a hand-off (M, optional; after the gap in §2 is answered)

- [ ] **5.1 Tools through the hub: `services/voice/voice/tools.py`, `[voice_mode] tools`.**
  - `[voice_mode] tools`: a list of tool names (the proposal: `calendar_agenda`, `agent_memory_search`, `web_search`, and the time), at most 6, since the model's tool calling is modest. The bridge reads their schemas from `GET /api/tools?names=…&view=model`, gives them to the session, and runs a call with `POST /api/tools/{name}/call` with the chat as origin and `unattended`-style handling: what would ask is refused, and the model is told to say so. No card ever opens in voice mode from this engine.
  - The page shows `tool {name, state}` in the status bar ("Looking at your calendar…"); the call is recorded in the chat as a step under the voice turn.
  *Done when:* `test_tools.py` with a fake hub (a call, a refusal spoken, an unknown tool, the cap); Phase 4's five tool prompts scored for both quants in `docs/voice-eval.md`; architecture §14 updated.
- [ ] **5.2 "Ask the chat's model": the `ask_chat` tool.**
  - A tool only the voice session has: `ask_chat {question}` sends the question as a message to the chat (`POST /v1/threads/{tid}/messages`), waits for the turn, and gives the answer's text (through `speakable`'s rules, capped) back to the speech model to say in its own words. Cards the chat's turn raises pause voice mode as today's `card` state does. Off by default: `[voice_mode] ask_chat = false`, a toggle in the Voice mode group ("Let it ask the chat's model for hard questions").
  *Done when:* a test with a fake agent (the round trip, a turn that fails, a card pausing); a live run: "what's in the file I attached?" answered through the chat's model.

**Checks & deliverables — Phase 5**
- [ ] Live: "what's on my calendar tomorrow" answered from the calendar; a write ("add a meeting") refused aloud with why.
- [ ] Delivered: `services/voice/voice/tools.py`, the settings rows, the eval's tool column.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| The spike report | What LFM3-Omni-2B does on this machine: latency, memory, the protocol as found | `docs/voice-spike.md` |
| The `voice` mod | llama.cpp's server as a child, the realtime bridge, turn detection, load/unload, its page and setup doc | `services/voice/` |
| Voice turns in chats | The context a voice session starts with, and its turns written into the chat | `services/agent/agent/api_voice.py` |
| `[voice_mode]` | The engine switch, the quant and the voice | `utils/config.py`, `utils/api_models.py`, `utils/settings.py`, `config.example.toml` |
| Settings → Speech → Voice mode | The switch and its rows | `web/settings/schema.js` |
| The live client | Microphone to the mod, replies to the speakers, barge-in | `web/chat/chat-voice-live.js`, `web/chat/chat-voice.js` |
| The comparison | Q4_K_M against Q8_0: latency, memory, accuracy, WAV pairs | `services/voice/evals/`, `docs/voice-eval.md` |
| Tools and hand-off (optional) | A few read-only tools and `ask_chat` | `services/voice/voice/tools.py` |
| Tests | Fake llama-server, fake realtime server, fake hub; the state machine and settings | `services/voice/tests/`, `services/agent/tests/test_api_voice.py`, `utils/tests/settings/test_voice_mode.py`, `utils/tests/web/chat-voice-live.test.mjs`, `settings-schema.test.mjs` |
