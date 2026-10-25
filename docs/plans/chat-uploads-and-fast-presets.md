# Plan: fast presets the agent can use, and uploading images in Chat

Asked for on 2026-10-10. There are three wants:

1. Every Qwen-Image 2.1 Turbo workflow has the same speed presets.
2. The agent can use those presets, and does so when you ask in plain words ("a quick draft of…").
3. You can upload an image from your computer in Chat and ask the agent to edit it.

Today Chat attaches only existing GAIFA outputs (the 📎 picker; the agent sees `output:<id>`), and the agent's task tools take only shared inputs, so `preset` is refused.

The approach is to make an uploaded file an ordinary GAIFA output. The picker, the agent's context, the edit tools and `output:<id>` resolution then work unchanged. The comfy task tools get one new argument, `preset`.

It touches the comfy mod (architecture §11, [workflows.md](../workflows.md)), the outputs index (§4.7) and a new hub route (§6, UI brief §6), plus the Chat composer (plan 14.1).

## Gaps & answers

- **Which presets?** *Assumption:* two, named the same in every pack. `fast` is about 0.6 MP (t2i `megapixels = 0.6`; edit and remove-bg `resolution = 768`). `draft` is about 0.35 MP (t2i `megapixels = 0.35`; edit and remove-bg `resolution = 576`). Measured trade-offs are in [comfy-transfer-report.md](../comfy-transfer-report.md) ("Speed-ups"): small text breaks below 1 MP.
- **Which packs?** *Assumption:* the three `qwen21-turbo-*` packs. A task tool's `preset` takes any preset name; a pack without that preset gets an error naming the presets it has.
- **Where do uploads go?** *Assumption:* `outputs/uploads/<YYYY-MM-DD>/<HHMMSS>-<slug>.<ext>`, with a sidecar (`title` = the original file name, `source.service = "upload"`). They show on the Outputs page under "uploads" and can be deleted like any output. Images, video and audio only (by extension), and at most 64 MB.
- **Upload transport.** *Assumption:* the raw file as the request body (`POST /api/outputs/upload?name=<file name>`), not multipart, so the hub needs no new dependency.

## Steps

- [x] **U.1 Presets: `services/comfy/workflows/qwen21-turbo-*/workflow.toml`.**
  - `[presets.fast]` and `[presets.draft]` on all three packs (t2i through the derived `megapixels`).
  *Done when:* `comfyui workflows check` reports the packs `ready`, and `test_packs.py::test_qwen21_turbo_packs` asserts both presets.

- [x] **U.2 Task tools take `preset`: `services/comfy/comfy/tools.py`, `api_run.py`.**
  - `catalog()` adds `preset` (an enum of every preset among the task's ready packs) to each task tool, and each pack's line in the description lists its presets.
  - `call_tool` pops `preset` and passes it to `runner.submit`. An unknown preset for the picked pack is an `InputError` that names the presets it has.
  *Done when:* `tests/test_tools.py` covers the schema, a call with a preset, and an unknown preset.
  - *As built:* the presets also went on `zimage-turbo` and `zimage-intorealism` (the text-to-image default), through `megapixels`. That found a bug: `resolve` ran the aspect/megapixels → width/height step only for the caller's values, so a preset that set `megapixels` did nothing on a width/height pack. It now follows the preset too (`test_run.py::test_a_preset_drives_derived_sizes`). `image-edit` and `remove-background` had no default pack, so a plain "edit this" needed a workflow named. Their defaults are now `qwen21-turbo-edit-multi` and `qwen21-turbo-remove-bg` (`PUT /v1/defaults`; runtime state in comfy.db).

- [x] **U.3 Plain-words requests: `services/comfy/skills/choosing-a-workflow/SKILL.md`.**
  - "quick", "fast", "rough", "preview" map to `fast`, "draft" or "thumbnail" to `draft`, and "final" or "high quality" to no preset. Small text needs no preset.
  *Done when:* a live chat turn ("a quick draft of …") shows an approval card with `preset: "fast"` or `"draft"` (U.6).

- [x] **U.4 Uploads: `POST /api/outputs/upload` in `utils/routes/outputs.py`; `utils/outputs/upload.py`.**
  - `save_upload(paths, name, data) -> rel`: check the extension and size, slug the name, write `.part` then rename, and write the sidecar. The route calls `Outputs.sync("uploads/<date>")` and returns the new `Output`.
  - Errors use the envelope: `upload_type` (415), `upload_too_large` (413), `upload_empty` (400).
  - `web/api.js`: `uploadOutput(file)`. Docs: architecture §6 (hub routes), UI brief §6 (the method table), §4.7 (the `uploads` folder).
  *Done when:* `utils/tests/outputs/test_upload.py` (saved, indexed, sidecar title, the three errors), `api.test.mjs`, and the contract test pass.

- [x] **U.5 Chat composer: `web/chat/chat-composer.js`, `web/chat/chat.js`.**
  - An "Upload" button (a file picker, several files allowed), dropping files on the composer, and pasting images. Each file uploads and is added as an attachment chip with its preview, and a failed upload shows the error.
  *Done when:* `chat.test.mjs` covers the upload helper, and in the browser an uploaded image appears as a chip and in the sent message.

- [x] **U.6 Live check.**
  - In Chat: upload a photo, ask "make this a night scene, quick draft", and check the card shows `edit_image` with `image: output:<id>` and the preset. Approve it; the result appears. Then "remove the background of it" works on the same upload.
  *Done when:* both runs finish, recorded below.
  - *As built (2026-10-10, local Gemma 4 26B):*
    - **The quick edit worked as asked.** "Turn this into a snowy winter night. Just a quick one" with a dropped upload gave a card with `qwen21-turbo-edit-multi`, `image: output:<upload>` and `preset: fast`, and made a 928×640 result. Pasting an image works the same way.
    - **Two pictures ended the chat (fixed).** The agent counted a `view_output` picture by its base64 length (~50k tokens), so the upload plus its result hit `context_full`. A picture now counts 1,100 tokens.
    - **"Full quality" picked the base model (fixed).** The guide called the base packs "full quality". It now says that means no preset on the default, and the base packs are only for when the user names them.
    - **A scene cut-out left out what to keep.** The model guesses the subject, and on a frame-filling storefront it kept only the window frames. A bare noun as the instruction returns the photo unchanged. So the remove-bg packs have a `template` on `prompt` ("the storefront" → "Extract the storefront in <image1> and remove everything else. Output a PNG image."), and `[tasks.remove-background.inputs]` tells the agent what `prompt` means there.
    - **This model still often omits `prompt` for remove-bg.** The card shows the field with that hint, and typing "the storefront" there gave a clean cut-out in 69 s.

Commits: one per step once its tests pass, `GAIFA (chat/comfy U.k): <sentence>`.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Presets | `fast` / `draft` on the Turbo packs | `services/comfy/workflows/qwen21-turbo-*/workflow.toml` |
| Preset argument | task tools take `preset` | `services/comfy/comfy/tools.py`, `api_run.py` |
| Agent guide | plain words → preset | `services/comfy/skills/choosing-a-workflow/SKILL.md` |
| Upload route | a file → a GAIFA output | `utils/outputs/upload.py`, `utils/routes/outputs.py`, `web/api.js` |
| Composer upload | button, drop, paste | `web/chat/chat-composer.js`, `web/chat/chat.js` |
| Tests | presets, tool schema and calls, uploads, the UI helper | `services/comfy/tests/`, `utils/tests/outputs/test_upload.py`, `utils/tests/web/` |
