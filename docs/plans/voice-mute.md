# Plan: a mute button and push to talk for voice mode, and noise that doesn't interrupt it

**Asked for:** 2026-11-11 · **Status:** In progress

## 1. Introduction

In voice mode the microphone stays open. Background noise (a TV, a door, someone else in the room) is taken for the user talking: while the reply is read it counts as an interruption, so the speech stops and, when the chat's agent answers (plan [voice-speech-model](voice-speech-model.md) Phase 6), the agent's turn is cancelled too; while it listens, noise starts a turn that was never said. The user asked for a mute button.

Phase 1 is the button: muted, nothing the microphone picks up reaches the turn detector or the interruption check, and the reply goes on. Phase 2 is push to talk (asked for the same day): the microphone is heard only while a key or the button is held, and letting go sends the turn. Phase 3 makes the unmuted case hold up better: an interruption needs speech, not loudness, and one that turns out to hold no words gives the reply back. Both engines get the button (the speech model, `web/chat/chat-voice-live.js`, and the chat-model loop, `ChatVoiceButton` in `web/chat/chat-voice.js`). Touches architecture §9 (`[voice_mode]`) and §10 (the voice mod), the brief's voice-mode paragraph and Speech section.

## 2. Gaps & unanswered questions

- **What mute does to a reply under way**: *Assumption:* nothing. It keeps speaking; mute only stops the microphone from being heard. Stopping the reply stays the Stop button.
- **Muting in the middle of your own sentence**: *Assumption:* what was heard so far is dropped (no turn is sent), and the bar goes back to waiting.
- **Is mute remembered?** *Assumption:* for the conversation only. Starting voice mode again starts unmuted, unless `[voice_mode] start_muted = true` (a Settings row, off by default).
- **Keyboard:** *Assumption:* `M` toggles mute while voice mode is on and the composer isn't focused; the button has the same tooltip.
- **Where the audio stops**: *Assumption:* in the page (frames aren't sent while muted), and the mod is told (`{type: "mute", on}`) so it resets its detector and the bar's state is the mod's. The browser's microphone indicator stays on while muted (the stream is kept so unmuting is instant); the tooltip says so.
- **Push to talk, hold or tap?** *Assumption:* hold. Heard while Space (or the bar's button, by mouse or touch) is held; letting go ends the turn at once, with no wait for a pause. A press under 250 ms is ignored, so a stray tap sends nothing. A tap-to-start, tap-to-send variant isn't planned.
- **Which key:** *Assumption:* Space, only while voice mode is on and no text field is focused (in the composer Space types a space); `[voice_mode] push_key` changes it.
- **Pressing while it speaks:** *Assumption:* that is an interruption, on purpose: the reply stops and you are heard. Nothing else interrupts in this mode, so noise can't.
- **Mute in push to talk:** *Assumption:* not needed (the microphone is closed unless held); the bar shows the talk button in the mute button's place.
- **How strict "speech, not loudness" should be** is measured in 3.1 before it is fixed; the numbers in Phase 3 are starting points.

## 3. Phases and steps

## Phase 1 — Mute (S)

- [x] **1.1 The mod: `mute` on the socket, `services/voice/voice/bridge.py`.**
  - **Message:** `read_page` takes `{type: "mute", on: bool}`. `Session.muted`; while set, `on_audio` drops frames. Turning it on calls `detector.reset()`, drops a turn being heard (the transcription buffer is cleared, the GPU slot given back through `AgentTurns` / `Gpu.off` when nothing is spoken), and emits `{type: "muted", on}`; the mode goes to `listening`. A reply being spoken is untouched.
  - **Interruptions:** `on_interrupt` is ignored while muted (a page that still sends one is out of date).
  - **Start:** `Start.muted: bool = False`, so a conversation can begin muted; `ready` carries `muted`.
  *Done when:* `services/voice/tests/test_mute.py`: frames while muted start no turn; muting mid-sentence sends nothing to the chat; a reply keeps streaming through a mute; unmuting hears again; `interrupt` while muted changes nothing; both `answers` modes.
- [x] **1.2 The page's client: `web/chat/chat-voice-live.js`.**
  - **`liveVoice`:** returns `{stop(), mute(on)}`; muted, `onFrame` sends nothing and skips the `bargeTracker` check; `mute` sends the message. `liveStep` gains `muted` (from `ready` and `muted` events); `LIVE_WORDS.muted = 'Muted'`, shown instead of Listening…, and `Speaking (muted)` while a reply plays.
  *Done when:* `utils/tests/web/chat-voice-live.test.mjs`: no frames and no `interrupt` while muted, the `mute` message, the words for each state, a reconnect that keeps the mute.
- [x] **1.3 The bar: `web/chat/chat-voice.js`.**
  - **Button:** a microphone / microphone-off button in the voice bar (`bar(...)`), beside the Agent answers switch, for `LiveVoice` and for `ChatVoiceButton` (the chat-model loop: muted, `dictate` is paused and its `bargeTracker` skipped). `M` toggles it. The level meter is flat while muted.
  - **Setting:** `[voice_mode] start_muted` (`utils/config.py` `VoiceModeCfg`, `utils/api_models.py`, `config.example.toml`); row "Start muted" in `web/settings/schema.js` under Speech → Voice mode; `web/mock.js`.
  - **Docs:** architecture §9 and §10, the brief (settings type, Speech section, voice mode), `web/PATCHES.md`, `docs/structure.md`.
  *Done when:* `chat-voice.test.mjs` and `settings-schema.test.mjs` extended; `utils/tests/settings/test_voice_mode.py` (the default, a save); browser check with the fake microphone on a scratch hub: a loud frame during a reply doesn't stop it while muted and does when unmuted, in both `answers` modes and in the chat-model loop.

**Wire — Phase 1:** the voice bar's mute button and the Start muted row are live.

**Checks & deliverables — Phase 1**
- [ ] On the installed hub (`gaifa restart`, `gaifa restart voice`): a spoken turn, mute during the agent's answer with noise played, the answer finishes; unmute, the next turn is heard.
- [ ] The user tries it with a real microphone.
- [ ] Delivered: the `mute` message and `Start.muted`, the client's `mute`, the bar button and shortcut, `start_muted`.

## Phase 2 — Push to talk (S)

- [x] **2.1 The mod: `talk` on the socket, `services/voice/voice/bridge.py`, `vad.py`.**
  - **Start:** `Start.talk: "open" | "push"` (else `[voice_mode] talk`); `ready` carries it. In `push` the detector's VAD decides nothing: frames outside a hold are dropped, as when muted.
  - **Message:** `{type: "talk", on: bool}`. On: an interruption if a reply is under way (today's `on_interrupt` path, with the page's `played_ms`), then `TurnDetector.begin()` so everything after is the turn (`hearing`, the GPU slot as in 1.1). Off: `end_turn()` at once; a hold with under 250 ms of audio or an empty transcription sends nothing and goes back to `listening`. A hold is capped at the detector's `max_s`.
  *Done when:* `services/voice/tests/test_push.py`: frames outside a hold start nothing (loud noise included); a hold sends its words when released without waiting `pause_ms`; a short press sends nothing; a press during a reply interrupts it; both `answers` modes.
- [x] **2.2 The page: `web/chat/chat-voice-live.js`, `chat-voice.js`.**
  - **`liveVoice`:** `talk` in the start message; returns `talk(on)`; in `push` the `bargeTracker` check is off and frames go up only while held (plus the 400 ms before the press, kept in a small ring, so a first syllable isn't lost).
  - **Bar:** in `push` the mute button's place holds a Hold to talk button (pointer down / up, touch included, released on blur or pointer leave) and the key (`push_key`, Space) does the same when no text field is focused; words: "Hold Space to talk", "Listening… (let go to send)". The chat-model loop (`ChatVoiceButton`) gets the same: `dictate` runs only while held and sends on release.
  - **Setting:** `[voice_mode] talk = "open"` and `push_key = "Space"` (`utils/config.py` `VoiceModeCfg`, `utils/api_models.py`, `config.example.toml`); rows "Microphone" (Always listening / Push to talk) and "Key" in Speech → Voice mode (`web/settings/schema.js`); a switch in the bar that saves it, as Agent answers does; `web/mock.js`.
  - **Docs:** architecture §9 and §10, the brief (settings type, Speech section, voice mode), `web/PATCHES.md`, `docs/structure.md`.
  *Done when:* `chat-voice-live.test.mjs` and `chat-voice.test.mjs` (frames only while held, the pre-roll, key and pointer, no key while a field is focused, release on blur), `settings-schema.test.mjs`, `utils/tests/settings/test_voice_mode.py`; browser check with the fake microphone on a scratch hub in both `answers` modes and the chat-model loop.

**Wire — Phase 2:** the Microphone row, the bar's talk button and the key are live.

**Checks & deliverables — Phase 2**
- [ ] On the installed hub: three held turns answered; noise played between them starts nothing and stops no reply; a press during an answer interrupts it.
- [ ] The user tries it with a real microphone.
- [ ] Delivered: the `talk` message and `Start.talk`, the client's `talk`, the bar button and key, `talk` and `push_key`.

## Phase 3 — Noise doesn't interrupt, with the microphone open (M)

- [x] **3.1 Measure: `services/voice/evals/noise.py`.**
  - Play recorded noise (speech-shaped babble, a TV clip, keyboard and door sounds, a cough; a few files kept in `services/voice/evals/noise/`, small, recorded here or synthesized) and real spoken interruptions through the bridge during a reply, and count false and missed interruptions for: today's rule (the page's level over `BARGE_LEVEL` for `BARGE_MS`), Silero's speech probability over a window, and both together. Same for turns started while listening (`enter_ms`).
  *Done when:* a table in `docs/voice-eval.md` (Noise), and the rule chosen from it.
- [ ] **3.2 Interruptions decided by the mod: `services/voice/voice/vad.py`, `bridge.py`.**
  - **Rule:** while a reply plays, the mod runs the frames it already receives through the detector's VAD; an interruption is `barge_ms` of speech (3.1's numbers; a starting point: 300 ms at probability ≥ 0.6). The mod then emits `{type: "interrupted"}` and the page stops playback and answers with `played_ms`. The page's own level check stays only as a pre-filter (quiet frames aren't worth a VAD pass) and for the chat-model loop.
  - **Setting:** `[voice_mode] interrupt = "speech" | "off"`: `off` means only Stop and the mute button end a reply. Row "Talking over it" in Speech → Voice mode.
  *Done when:* `services/voice/tests/test_barge.py` (noise frames don't interrupt, speech frames do, `off`); 3.1's eval rerun shows fewer false interruptions with no more missed ones; web tests for the `interrupted` event.
- [ ] **3.3 A false interruption gives the reply back: `services/voice/voice/agent_turns.py`.**
  - **Agent answers:** an interruption pauses the speech and holds the chat's turn for up to `HOLD_S` (1.5 s) instead of cancelling at once; when the transcription of what interrupted is empty or under two words, the speech resumes from the sentence it stopped in and the turn was never cancelled; with words, today's behavior (cancel, new turn).
  - **Speech model answers:** the reply can't be resumed in llama.cpp's realtime session; the rest of its text is said through `/tts` (`speak.tts_stream`).
  - **Bar:** "Go on…" for the hold.
  *Done when:* `test_agent_turns.py` (noise → resumed, the chat's turn not cancelled; words → cancelled as today); a live run on a scratch hub with a cough clip during a tool-using answer.

**Checks & deliverables — Phase 3**
- [ ] On the installed hub: the noise clips during three answers, none stopped; three spoken interruptions, all taken.
- [ ] Delivered: the noise eval and its table, `interrupt`, the mod-side rule, the hold and resume.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Mute on the socket | `mute` message, `Start.muted`, `muted` event | `services/voice/voice/bridge.py` |
| Client mute | `mute(on)`, no frames or interruptions while muted | `web/chat/chat-voice-live.js` |
| Bar button | mute button and `M` in both engines' bars | `web/chat/chat-voice.js` |
| Push to talk | `talk` message, the hold button and key, heard only while held | `services/voice/voice/bridge.py`, `web/chat/chat-voice-live.js`, `web/chat/chat-voice.js` |
| Settings | `[voice_mode] start_muted`, `talk`, `push_key`, `interrupt` | `utils/config.py`, `utils/api_models.py`, `web/settings/schema.js`, `config.example.toml` |
| Speech-based interruptions | the mod's rule and the hold / resume | `services/voice/voice/vad.py`, `bridge.py`, `agent_turns.py` |
| Noise eval | false and missed interruptions per rule | `services/voice/evals/noise.py`, `docs/voice-eval.md` |
| Tests | fast tests on the fake llama server and Node tests for the page | `services/voice/tests/test_mute.py`, `test_push.py`, `test_barge.py`, `test_agent_turns.py`, `utils/tests/web/chat-voice*.test.mjs`, `utils/tests/settings/test_voice_mode.py` |
