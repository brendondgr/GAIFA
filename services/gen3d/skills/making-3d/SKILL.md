---
name: making-3d
description: Making 3D models with gen3d: from text or from a picture, which engine to pick, presets, polygon counts, parts and rigs
---
# Making 3D models (`gen3d_make_3d`)

**From a picture (preferred when there is one):** pass `engine` and `image` (`output:<id>` of the picture; an image the user attached shows as `output:<id>` in their message). Pick the engine by what's in it:
- `hunyuan21`: characters and creatures. The cleanest, watertight surface. About 1.5 min.
- `trellis2`: objects with detail (vases, props, furniture). The most faithful shape. 1.5–4 min: round, bulky objects take longer than thin ones.
- `sam3d_objects`: the quickest full shape (about 1 min), rougher surface. Good for a first look.
- `sam3d_body`: a person's body as a rigged mesh (body only, no clothes or hair). About 10 s.

The picture should show one object or person on a plain or transparent background. For a photo of a scene, run `comfy_remove_background` first (with `prompt` naming the subject), then use its result. A picture made with `comfy_generate_image` works directly: generate it with a plain background ("on a white background, centered, full body").

**Presets:** image engines use `fast` unless asked otherwise; `base` is the slower stock setting (only when the user wants the most detail). `trellis2` also has `draft` (30–60 s, softer: for quick looks).

**Polygon count:** the raw mesh can be millions of faces (TRELLIS.2: 5–14 M). When the user wants fewer polygons, a "low-poly" model or a game asset, set `target_faces` in the engine's group: `{"trellis2": {"target_faces": 50000}}` or `{"hunyuan21": {"target_faces": 20000}}`. 50k keeps the shape; 20k starts to facet faces. The raw mesh is kept too. `sam3d_body` has a fixed 37k-face mesh.

**From text:** Cube3D (`engine` cube3d, the default) makes a mesh from `prompt`: one object, centered, with its material or style (low-poly, cartoon, realistic); no scenes, text or several objects. Presets: `fast` (about 1 min), `balanced` (default, about 1.5 min), `quality` (about 2.5 min, 52 GB peak memory), `lowpoly` (about 1,000 faces). When the user has a picture, prefer an image engine over describing the picture to Cube3D.

**Stages:** `["shape", "preview"]` is the usual job (a GLB plus a 4-view render). Add `"parts"` with up to 8 part names (`parts: {"parts": ["head", "body", "tail", "legs"]}`) to split a mesh, and `"rig"` after parts to make limbs movable; this works on any engine's mesh. `parent_id` continues from an earlier job (e.g. split an existing mesh into parts).
