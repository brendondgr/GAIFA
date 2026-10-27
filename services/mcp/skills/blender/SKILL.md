---
name: blender
description: >-
  Working in Blender through its MCP server: building and changing a scene, materials, Python in Blender, renders
  and .blend files. Read it before any Blender work.
metadata:
  mcp-servers: blender
---
# Working in Blender

Reading this skill loads the Blender server's tools (`mcp_blender_*`). If they aren't there, the user hasn't added
or approved the Blender server yet: say so (the MCP servers page has a Blender preset) and stop.

1. **Look first.** `mcp_blender_get_scene_info` before changing anything: what objects there are, their names, where.
2. **Small steps.** Change the scene with `mcp_blender_execute_blender_code`, a few lines of `bpy` at a time
   (add, move, give a material), and check with `mcp_blender_get_scene_info` after each step. Name what you make
   (`obj.name = "Tree trunk"`; the new object is `bpy.context.active_object`) so later steps can find it. Blender
   units are metres. A step that fails stops at the failing line: what came before it ran, so look again before you
   repeat it.
   - Primitives, `bpy.ops.mesh.primitive_<name>_add(...)`, each also taking `location`, `rotation`, `scale`:
     `cube` and `plane` (`size`), `uv_sphere` (`segments`, `ring_count`, `radius`), `ico_sphere` (`subdivisions`,
     `radius`), `cylinder` (`vertices`, `radius`, `depth`), `cone` (`vertices`, `radius1`, `radius2`, `depth`),
     `torus` (`major_radius`, `minor_radius`), `monkey` (`size`). Low-poly: few `vertices` or `subdivisions=1`.
   - A material's colour is its shader's, which is what renders: `m = bpy.data.materials.new("Red")`, then
     `m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 0, 0, 1)` (colours are RGBA),
     then `obj.data.materials.clear(); obj.data.materials.append(m)`.
3. **Code that runs on the user's machine.** Every code step is a card (or, in Auto, the judge decides): keep each
   one short and say what it does. Never touch files outside the outputs folder the tool's description names, never
   import anything but `bpy`, `bmesh`, `mathutils`, `math` and `time`, never reach the network from Blender code.
4. **Renders and files.**
   - A render needs a camera that sees the subject, and light. Keep the scene's camera and light (delete only meshes:
     `for o in list(bpy.data.objects): if o.type == "MESH": bpy.data.objects.remove(o)`), or add them; a new camera
     renders only once it's the scene's (`scene.camera = cam`).
   - Frame everything with this, copied exactly (it fits every mesh, however many parts the subject has):
     ```python
     import bpy
     from mathutils import Vector
     scene = bpy.context.scene
     pts = [o.matrix_world @ Vector(c) for o in scene.objects if o.type == "MESH" for c in o.bound_box]
     lo = Vector([min(p[i] for p in pts) for i in range(3)])
     hi = Vector([max(p[i] for p in pts) for i in range(3)])
     mid, size = (lo + hi) / 2, max(hi - lo)
     cam = scene.camera
     cam.constraints.clear()
     cam.location = mid + Vector((1, -1, 0.7)).normalized() * size * 2.2
     cam.rotation_euler = (mid - cam.location).to_track_quat("-Z", "Y").to_euler()
     ```
   - Set the file before rendering (Blender's default is /tmp, where nobody sees it): under the outputs folder the
     tool's description names, in today's folder, named by the time now so nothing is overwritten:
     `import time; scene.render.filepath = f"{OUTPUTS}/{time.strftime('%Y-%m-%d/%H%M%S')}-tree.png"` (Blender makes
     the folder), then `bpy.ops.render.render(write_still=True)` and `print()` the path: the file becomes an output in
     the chat. `.blend` files go there too.
   - Render small first (`scene.render.resolution_x = scene.render.resolution_y = 512`; Eevee, or Cycles with
     `scene.cycles.samples = 16`); bigger only when asked.
5. **Check what you made.** Look at a render with `view_output` before you say it worked. Empty or black: the camera
   or the light is wrong. The subject cut off at the edges: frame it again (step 4). Fix it and render again.
   `mcp_blender_look` shows the viewport (it works without a window too): it's for you to check the scene, never a
   render; when the user asks for a render or a picture, render (step 4).
6. **A model from gen3d.** To bring in a 3D model GAIFA made, import its GLB by the file's path
   (`bpy.ops.import_scene.gltf(filepath=...)`): `hub_search_outputs` with `service: "gen3d"`, `kind: "model3d"` finds
   them newest first, `hub_get_output` gives an output's files (the `.glb`). Then frame it (step 4) and look.
