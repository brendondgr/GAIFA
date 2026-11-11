# LFM3-Omni-2B on this machine: the spike (plan voice-speech-model, Phase 1)

Measured 2026-11-11 on the Ryzen AI Max+ 395 (Radeon 8060S, Mesa RADV), with llama.cpp **b12292** (`llama-b12292-bin-ubuntu-vulkan-x64.tar.gz`, sha256 `01a6e2a7caa8d6ab6cb2dd906bd7c5c435440849c259440b1c3d3724850fa8e7`). The probe and its outputs are in `data/state/voice-spike/` (local, not tracked): `probe.py`, `out/*.json`, and the reply WAVs `out/q4-vk-c*.wav` and `out/q8-vk-c*.wav` for listening.

## Files

| File (in `data/models/s2s/LFM3-Omni-2B/`) | Size | sha256 starts |
| --- | --- | --- |
| `LFM3-Omni-2B-Q4_K_M.gguf` | 1.10 GB | `9f8d30e9d4fd7a93` |
| `LFM3-Omni-2B-Q8_0.gguf` | 1.85 GB | `59118f661eaacb93` |
| `mmproj-LFM3-Omni-2B-Q8_0.gguf` (vision, audio in, the codec) | 0.51 GB | `8a25f9d193124442` |

No separate codec or vocoder file: the projector file holds it. The tarball's `llama-server` serves `/v1/realtime`, `/tts` and `/props` (`voices: ["female", "male"]`); the server is started with `--mmproj`, `--reasoning off`, `--temp 0`.

## Speed and memory

Three spoken turns (a short question, a long one, a fact to remember) and a follow-up, sent in real time. *First audio* is from the end of your speech to the first reply audio; *speed* is seconds of work per second of speech made (under 1 is faster than real time).

| | Load | First audio | Speed | Memory (process: RAM + GPU) |
| --- | --- | --- | --- | --- |
| Q4_K_M, Vulkan | 1.4 s | 89–93 ms | 0.22 | about 0.3 + 4.0 GB |
| Q8_0, Vulkan | 1.3 s | 116–122 ms (289 ms on the first turn) | 0.27 | about 0.2 + 4.9 GB |
| Q4_K_M, `-ngl 0` | 1.3 s | 169–210 ms | 0.33 | about 1.7 + 1.3 GB |
| Q8_0, `-ngl 0` | 1.3 s | 224–317 ms | 0.45 | about 1.7 + 1.9 GB |

The bar (first audio within 1.5 s, speech faster than real time) is met by every row. Speech output runs on Vulkan. Memory was read from the process's `fdinfo` with the default four slots of 128,000 tokens; the mod runs two slots of 32,768, so its `estimate_gb = 5` is on the safe side.

## The protocol, as found

- **Session:** `session.created` reports `audio.input.format.rate` 16000 and `audio.output.format.rate` 24000. `session.update` takes `type`, `instructions`, `output_modalities`, `tools`, `tool_choice`, `max_output_tokens`, `audio.input.format.rate` (the server resamples 8–192 kHz) and **`audio.output.voice`** (`female` / `male`) and `audio.output.language`. Instructions and tools only before the first audio or message.
- **Turn detection:** none (`turn_detection: null`). The client ends a turn with `response.create`. The mod's bridge has to find the pause.
- **Your words as text:** a conversation session sends no transcript of the input. A second session on the same server with `type: "transcription"` does: the same audio, then `input_audio_buffer.commit`, answers `conversation.item.input_audio_transcription.completed` in 0.2–0.7 s, and its text was right on all three clips ("Brendan" for "Brendon"). No stt mod needed.
- **History:** `conversation.item.create` takes user `input_text` messages and `function_call_output` only; an assistant item is refused. A transcript of the chat inside `instructions` works (it answered from it).
- **Interrupting:** `response.cancel` stopped a reply 30 ms later; `response.done` has `status: "cancelled"` and the text said so far; the next turn in the same session worked.
- **Two sessions at once** work (first audio about 190 ms each, speed 0.4).
- **Tools:** with the model card's tool prompt the model said "Let me check your calendar" and made no call on the one try. Left for Phase 5, which tries `tool_choice` and text-only tool turns.
- **Events of a reply:** `response.created`, `response.output_item.added`, `response.content_part.added`, `response.output_text.delta` and `response.output_audio.delta` (base64 PCM16), the `.done` events, `response.done` (`usage.output_tokens`).

## What it means for the plan

| Assumption in the plan's §2 | Held? |
| --- | --- |
| Speech output runs on Vulkan | Yes |
| The bridge finds the end of your turn | Yes, it must: the server has no turn detection |
| Input transcription from the realtime session | No: a second, transcription session on the same server instead (not the stt mod) |
| Text history can be added | Only as a transcript in the instructions |
| One session at a time | Two work; the mod allows one conversation (plus its transcription session) |
| `estimate_gb = 4` | 5 |
| Voice and language | Session fields `audio.output.voice` and `audio.output.language` |
