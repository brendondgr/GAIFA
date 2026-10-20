---
name: making-3d
description: Making 3D models with gen3d: from text or from a picture, which engine fits the subject, presets, polygon counts, parts and rigs
---
# Making 3D models (`gen3d_make_3d`)

The `engine` parameter says which engines take text and which need a picture, and each one's presets; the hub refuses a pairing that doesn't fit. This skill is about choosing well.

**With a picture** (`image` = `output:<id>`; an image the user attached shows as `output:<id>` in their message), choose the image engine by what the picture shows:
- a character or creature: `hunyuan21` (the cleanest, watertight surface);
- an object with detail (vases, props, furniture): `trellis2` (the most faithful shape; the default with a picture);
- a quick first look: `sam3d_objects` (rougher surface);
- a person's body as a rigged mesh: `sam3d_body` (body only, no clothes or hair).

The picture should show one object or person on a plain or transparent background. For a photo of a scene, run `comfy_remove_background` first (with `prompt` naming the subject), then use its result.

**With only text,** there are two ways. When the user hasn't said which, ask once with `ask_user`:
- **Cube3D from the text:** quicker, and the only way to get named parts and a rig from scratch. Write `prompt` as one object, centered, with its material or style (low-poly, cartoon, realistic); no scenes, text or several objects.
- **A picture first, then an image engine:** more faithful detail. Make the picture with `comfy_generate_image` ("…, one object, centered, on a plain white background, full body"), then pass that output as `image` to the image engine that fits the subject.

**Presets:** image engines use `fast` unless the user wants the most detail (`base`, slower); `trellis2` also has `draft` for a quick look. Cube3D: `fast`, `balanced` (its default), `quality` (52 GB peak memory), `lowpoly` (about 1,000 faces).

**Polygon count:** the raw mesh can be millions of faces (TRELLIS.2: 5–14 M). When the user wants fewer polygons, a "low-poly" model or a game asset, set `target_faces` in the engine's group: `{"trellis2": {"target_faces": 50000}}` or `{"hunyuan21": {"target_faces": 20000}}`. 50k keeps the shape; 20k starts to facet faces. The raw mesh is kept too. `sam3d_body` has a fixed 37k-face mesh.

**Stages:** `["shape", "preview"]` is the usual job (a GLB plus a 4-view render). Add `"parts"` with up to 8 part names (`parts: {"parts": ["head", "body", "tail", "legs"]}`) to split a mesh, and `"rig"` after parts to make limbs movable; this works on any engine's mesh. `parent_id` continues from an earlier job (e.g. split an existing mesh into parts).
