"""Vendored from ~/Models/3D/CubeArt/scripts/render_blender.py.

Headless Blender preview: 4-view contact sheet (3/4, front, side, top) of one or more GLB/OBJ files.

    blender -b --factory-startup -P scripts/render_blender.py -- out.png in1.glb [in2.glb ...] [--size 512] [--label TEXT]

Uses Workbench (CPU-cheap, no GPU needed). Per-part vertex/face colors from CubePart are shown when
present; plain meshes get a neutral clay color.
"""

import math
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
size = 512
label = None
if "--size" in argv:
    i = argv.index("--size"); size = int(argv[i + 1]); del argv[i:i + 2]
if "--label" in argv:
    i = argv.index("--label"); label = argv[i + 1]; del argv[i:i + 2]
out_png, inputs = argv[0], argv[1:]

bpy.ops.wm.read_factory_settings(use_empty=True)
for f in inputs:
    if f.lower().endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=f)
    elif f.lower().endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=f, forward_axis="NEGATIVE_Z", up_axis="Y")
    elif f.lower().endswith(".ply"):
        bpy.ops.wm.ply_import(filepath=f)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
has_attr = any(len(o.data.color_attributes) for o in meshes)
for o in meshes:
    for p in o.data.polygons:
        p.use_smooth = False

# bounds
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (lo + hi) / 2
rad = (hi - lo).length / 2

scn = bpy.context.scene
scn.render.engine = "BLENDER_WORKBENCH"
scn.render.resolution_x = scn.render.resolution_y = size
scn.render.film_transparent = False
sh = scn.display.shading
sh.light = "STUDIO"
sh.color_type = "VERTEX" if has_attr else "SINGLE"
sh.single_color = (0.72, 0.70, 0.66)
sh.show_cavity = True
sh.cavity_type = "BOTH"
sh.show_shadows = True
sh.shadow_intensity = 0.35
sh.background_type = "VIEWPORT"
sh.background_color = (0.13, 0.14, 0.16)
scn.display.shadow_focus = 0.2
scn.view_settings.view_transform = "Standard"

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = rad * 2.25
cam = bpy.data.objects.new("cam", cam_data)
scn.collection.objects.link(cam)
scn.camera = cam

# Blender is Z-up; glTF +Z forward maps to Blender -Y. "front" looks at the model's face.
views = {
    "3/4": (math.radians(35), math.radians(-40)),
    "front": (0.0, 0.0),
    "side": (0.0, math.radians(-90)),
    "top": (math.radians(89.9), 0.0),
}
tiles = []
for name, (elev, azim) in views.items():
    d = Vector((math.sin(azim) * math.cos(elev), -math.cos(azim) * math.cos(elev), math.sin(elev)))
    cam.location = ctr + d * rad * 4
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    path = out_png.replace(".png", f"_{name.replace('/', '')}.png")
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(size, size, 4)
    tiles.append(px)

top = np.concatenate([tiles[2], tiles[3]], axis=1)  # bottom row in image coords (flipped y)
bot = np.concatenate([tiles[0], tiles[1]], axis=1)
sheet = np.concatenate([top, bot], axis=0)
im = bpy.data.images.new("sheet", sheet.shape[1], sheet.shape[0], alpha=True)
im.pixels = sheet.ravel()
im.filepath_raw = out_png
im.file_format = "PNG"
im.save()
import os
for name in views:
    try:
        os.remove(out_png.replace(".png", f"_{name.replace('/', '')}.png"))
    except OSError:
        pass
print("RENDERED", out_png)
