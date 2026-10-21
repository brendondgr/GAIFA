"""Vendored from ~/Models/3D/CubeArt/scripts/render_blender.py (changed: simplified big meshes, light Workbench, CPU mode).

Headless Blender preview: 4-view contact sheet (3/4, front, side, top) of one or more GLB/OBJ/PLY files.

    blender -b --factory-startup --disable-autoexec -P scripts/render_blender.py -- out.png in1.glb [in2.glb ...]
        [--size 384] [--label TEXT] [--max-faces 300000] [--device gpu|cpu]

Workbench renders through OpenGL, so it runs on the GPU even in background mode. `--device cpu` expects the
caller to have forced Mesa's software rasterizer (LIBGL_ALWAYS_SOFTWARE=1, gen3d/preview.py does) and refuses
to render if the context is anything but llvmpipe/softpipe. Meshes over `--max-faces` are simplified in memory
by vertex clustering (the file on disk is never written). Shadows and cavity are off. Per-part vertex/face
colors from CubePart are shown when present; plain meshes get a neutral clay color.
"""

import math
import os
import sys

IMPORTABLE = (".glb", ".obj", ".ply")   # .gltf can point at files anywhere; never imported here
MAX_SIZE = 512                          # per tile: the sheet is at most 1024 px
FACE_LIMIT = 300_000
SOFTWARE_GL = ("llvmpipe", "softpipe", "swrast")


def parse_args(argv: list[str]) -> dict:
    """The arguments after `--`: out.png, inputs, and the options."""
    argv = list(argv)
    opts = {"size": 384, "label": None, "max_faces": FACE_LIMIT, "device": "gpu"}
    for flag, key, cast in (("--size", "size", int), ("--label", "label", str),
                            ("--max-faces", "max_faces", int), ("--device", "device", str)):
        if flag in argv:
            i = argv.index(flag)
            opts[key] = cast(argv[i + 1])
            del argv[i:i + 2]
    if opts["device"] not in ("gpu", "cpu"):
        raise SystemExit(f"--device must be gpu or cpu, not {opts['device']!r}")
    opts["size"] = max(64, min(MAX_SIZE, opts["size"]))
    if len(argv) < 2:
        raise SystemExit("usage: -- out.png in1.glb [in2.glb ...] [options]")
    bad = [f for f in argv[1:] if not f.lower().endswith(IMPORTABLE)]
    if bad:
        raise SystemExit(f"refusing {bad}: only {', '.join(IMPORTABLE)} are imported")
    return {"out": argv[0], "inputs": argv[1:], **opts}


# Simplification is vertex clustering: a Weld modifier merges vertices closer than diagonal / step. It is fast
# (seconds for 25M triangles) and works on any mesh; Decimate's collapse took 53 s on a 24.7M-triangle TRELLIS
# mesh and removed 1% of it. A tile is about diagonal / 340 per pixel at 384 px, so the coarsest step stays
# near a pixel. Finest first: the first step that fits the limit is kept.
WELD_STEPS = (2000, 1000, 500, 250)


def choose_merge(faces: int, limit: int, diagonal: float, count) -> tuple[float, int] | None:
    """The merge distance to draw with, and the faces left, or None to draw the mesh as it is.
    `count(distance)` returns the faces left after merging at that distance."""
    if limit <= 0 or faces <= limit or diagonal <= 0:
        return None
    for step in WELD_STEPS:
        dist = diagonal / step
        left = count(dist)
        if left <= limit:
            break
    return dist, left


def main() -> None:
    import bpy
    import numpy as np
    from mathutils import Vector

    a = parse_args(sys.argv[sys.argv.index("--") + 1:])
    out_png, inputs, size = a["out"], a["inputs"], a["size"]

    if a["device"] == "cpu":
        import gpu
        gpu.init()
        renderer = gpu.platform.renderer_get()
        if not any(s in renderer.lower() for s in SOFTWARE_GL):
            raise SystemExit(f"--device cpu but the GL context is {renderer!r}: refusing to render on the GPU")
        print("PREVIEW_GL", renderer)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    for f in inputs:
        low = f.lower()
        if low.endswith(".glb"):
            bpy.ops.import_scene.gltf(filepath=f)
        elif low.endswith(".obj"):
            bpy.ops.wm.obj_import(filepath=f, forward_axis="NEGATIVE_Z", up_axis="Y")
        elif low.endswith(".ply"):
            bpy.ops.wm.ply_import(filepath=f)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and len(o.data.polygons)]
    if not meshes:
        raise SystemExit("no mesh with faces in " + ", ".join(inputs))
    has_attr = any(len(o.data.color_attributes) for o in meshes)
    faces = sum(len(o.data.polygons) for o in meshes)

    # bounds
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))

    for o in meshes:
        o.data.shade_flat()                 # one call per mesh, not a Python loop over faces

    def count(dist: float) -> int:
        for o in meshes:
            weld = o.modifiers.get("preview_weld") or o.modifiers.new("preview_weld", "WELD")
            weld.merge_threshold = dist / max(max(o.matrix_world.to_scale()), 1e-9)   # in the object's units
        dg = bpy.context.evaluated_depsgraph_get()
        return sum(len(o.evaluated_get(dg).data.polygons) for o in meshes)

    merge = choose_merge(faces, a["max_faces"], (hi - lo).length, count)
    if merge is not None:   # bake once: each render.render() builds its own depsgraph and would weld again
        dg = bpy.context.evaluated_depsgraph_get()
        for o in meshes:
            o.data = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            o.modifiers.clear()
    print("PREVIEW_FACES", faces, "merge", merge)

    ctr = (lo + hi) / 2
    rad = max((hi - lo).length / 2, 1e-6)

    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.render.resolution_x = scn.render.resolution_y = size
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    scn.display.render_aa = "8"
    sh = scn.display.shading
    sh.light = "STUDIO"
    sh.color_type = "VERTEX" if has_attr else "SINGLE"
    sh.single_color = (0.72, 0.70, 0.66)
    sh.show_cavity = False
    sh.show_shadows = False
    sh.background_type = "VIEWPORT"
    sh.background_color = (0.13, 0.14, 0.16)
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
    for name in views:
        try:
            os.remove(out_png.replace(".png", f"_{name.replace('/', '')}.png"))
        except OSError:
            pass
    print("RENDERED", out_png)


if __name__ == "__main__":
    main()
