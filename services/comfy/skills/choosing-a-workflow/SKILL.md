---
name: choosing-a-workflow
description: Which image or video workflow to use, good prompts, aspect ratios and how long each takes
---
# Choosing an image or video workflow

**Text to image** (`comfy_generate_image`):
- `zimage-turbo` (default): fast photoreal images, 8 steps, about 20–40 s. Best for photos, products, people, animals.
- `zimage-intorealism`: painterly, watercolor look. Use when the user asks for art, painting or watercolor.
- `qwen21-t2i`: Qwen-Image 2.1: best at text inside the image (signs, posters, labels) and complex scenes; slower (1–2 min).
- `qwen21-turbo-t2i`: Qwen-Image 2.1 Turbo: the same strengths as `qwen21-t2i` in 8 steps, about 45–60 s. Prefer it for text in the image and complex scenes; use `qwen21-t2i` only when the user asks for the best quality and time doesn't matter.
- Prompts: one or two concrete sentences: subject, setting, light, style, camera. No negative prompt needed.
- Aspect: 16:9 for landscapes and scenes, 9:16 for phone wallpapers and portraits of people, 1:1 for icons and objects.

**Editing an image** (`comfy_edit_image`, workflow `qwen21-turbo-edit-multi`, or `qwen21-edit-multi` for the slower full-quality model): pass the image as `output:<id>` and say the change in plain words ("make it night", "add a red scarf"). Keeps the rest of the image. To use a second image as a reference, pass it as `image_2` and name them `<image1>`, `<image2>` in the prompt. The Turbo edit takes about 2 min.

**Remove background** (`comfy_remove_background`): a transparent PNG of the subject; a good step before turning an object into 3D or a sticker. `qwen21-turbo-remove-bg` (about 1 min) is the fast one; `qwen21-remove-bg` the full model (4–5 min).

**Video** (each run takes several minutes and a lot of memory; make one at a time):
- `comfy_animate_image` (`wan21-i2v`): animate an existing image into a ~5 s 480p clip. The prompt describes the motion ("the fox turns its head and blinks"), not the scene.
- `comfy_generate_video` (`wan21-t2v`): a ~5 s clip from text alone.

**Memory:** only one image or video model is loaded at a time; switching workflows reloads models (slower first run).
