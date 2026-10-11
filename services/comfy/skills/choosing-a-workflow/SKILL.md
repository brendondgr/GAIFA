---
name: choosing-a-workflow
description: Which image or video workflow to use, good prompts, aspect ratios and how long each takes
---
# Choosing an image or video workflow

**Text to image** (`comfy_generate_image`):
- `zimage-turbo` (default): fast photoreal images, 8 steps, about 20–40 s. Best for photos, products, people, animals.
- `zimage-intorealism`: painterly, watercolor look. Use when the user asks for art, painting or watercolor.
- `qwen21-turbo-t2i`: Qwen-Image 2.1 Turbo: best at text inside the image (signs, posters, labels) and complex scenes, 8 steps, about 40 s. The Qwen-Image 2.1 base model isn't offered: Turbo is the Qwen model to use.
- Prompts: one or two concrete sentences: subject, setting, light, style, camera. No negative prompt needed.
- Aspect: 16:9 for landscapes and scenes, 9:16 for phone wallpapers and portraits of people, 1:1 for icons and objects.

**Editing an image** (`comfy_edit_image`; `qwen21-turbo-edit-multi`, full quality without a preset): pass the image as `output:<id>` and say the change in plain words ("make it night", "add a red scarf"). Keeps the rest of the image. To use a second image as a reference, pass it as `image_2` and name them `<image1>`, `<image2>` in the prompt. The Turbo edit takes about 2 min.

**Remove background** (`comfy_remove_background`): a transparent PNG of the subject; a good step before turning an object into 3D or a sticker. When the user names what to keep, or the picture is a scene (a building, a room, several things), pass `prompt` with just those words ("the storefront", "the woman on the left"): the workflow turns them into its instruction. Without a prompt the model guesses the subject, and on a picture the subject fills it can remove nearly everything.

**Speed presets** (`preset` on `comfy_generate_image`, `comfy_edit_image` and `comfy_remove_background`; the Z-Image and Qwen 2.1 Turbo workflows have them, and a tool's description lists each workflow's presets):
- No preset (the default): full size and full quality, about 1 MP. "Full quality", "high quality" or "final" means no preset on the default workflow, not the base model. Use it unless the user asks for speed, and always when the image has small text (signs, labels, posters): small text breaks at smaller sizes.
- `fast`: about 0.6 MP and roughly 2–3x quicker. Use it when the user says "quick", "fast", "rough", "try a few", "preview" or "just to see".
- `draft`: about 0.35 MP and quicker still. Use it for "draft", "thumbnail", "tiny" or "lots of variations".
- `megapixels` sets the size directly for the Qwen 2.1 Turbo workflows and Z-Image (1.0 = 1024×1024, up to 4): for prototyping go lower (0.25–0.5), for a final picture leave it out or go higher. With a preset, the caller's `megapixels` wins.
- A preset makes a different, smaller picture, not a shrunk copy, so running a liked draft again at full size gives a new composition: say so if the user asks.
- An upload or output the user attached shows as `output:<id>` in their message: pass it as `image`.

**Video** (each run takes several minutes and a lot of memory; make one at a time):
- `comfy_animate_image` (`wan21-i2v`): animate an existing image into a ~5 s 480p clip. The prompt describes the motion ("the fox turns its head and blinks"), not the scene.
- `comfy_generate_video` (`wan21-t2v`): a ~5 s clip from text alone.

**Memory:** only one image or video model is loaded at a time; switching workflows reloads models (slower first run).
