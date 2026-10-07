---
name: making-3d
description: Making 3D models with gen3d: prompts, presets, parts and rigs, and turning an image into 3D
---
# Making 3D models (`gen3d_make_3d`)

- **Text only.** Cube3D makes a mesh from a text prompt; it can't take an image. To make an image into 3D: `view_output` the image, then describe the *object* (not the background): its shape, proportions, pose, key parts and style, e.g. "a low-poly red fox sitting upright, tail curled around its paws, stylized".
- **Prompt tips:** one object, centered; name the material or style (low-poly, cartoon, realistic); avoid scenes, text and multiple objects.
- **Stages:** `["shape", "preview"]` is the usual job (a GLB plus a 4-view render). Add `"parts"` with up to 8 part names (`parts: {"parts": ["head", "body", "tail", "legs"]}`) to split it, and `"rig"` after parts to make limbs movable.
- **Presets:** `fast` (about 1 min), `balanced` (default, about 1.5 min), `quality` (about 2.5 min, 52 GB peak memory), `lowpoly` (about 1,000 faces).
- `parent_id` continues from an earlier job (e.g. add parts to an existing shape).
