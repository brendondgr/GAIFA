---
name: voices
description: Picking a voice for speech, voice design and cloning, and directing delivery
---
# Voices for speech (`tts_speak`)

- **List voices first** with `tts_list_voices` when the user names a voice: `custom` are saved Breeze voices (cloned or designed, e.g. a person's name), `kokoro` are built-in Kokoro voices such as `af_heart` (US female), `am_adam` (US male), `bf_emma` (UK female).
- **Engine:** a saved (custom) voice uses Breeze automatically; a Kokoro voice uses Kokoro (fast, very clean). Omit `name` for the default voice.
- **Direction:** with Breeze, `instruction` sets the delivery: "slow, warm and reassuring", "excited sports commentator". Without a `name`, `instruction` describes a new voice ("an old man with a deep, gravelly voice").
- **New voices:** `tts_design_voice` invents and saves a voice from a description; `tts_clone_voice` needs a 3–60 s clean reference clip.
- Long text: speak it in one call (up to a few thousand characters); the clip is saved to Outputs.
- To narrate an image: look at it with `view_output`, write 2–4 sentences, then speak them.
