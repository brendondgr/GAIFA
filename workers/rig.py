"""Turn CubePart part meshes into an articulated, game-ready GLB.

Vendored from ~/Models/3D/CubeArt/scripts/rig.py (CubeArt-only --gt mode removed, callable as rig()).

Hierarchy (every joint node sits at its pivot; local axes: Z = swing axis, Y = extend direction,
X = lift axis — so engine scripts rotate about local Z/X and translate along local Y):

  asset_root
    base                         (pedestal)
    recline_joint                (tilts the whole back assembly, local X)
      back                       (torso / body, plus anything that is not a limb or the head)
      head_joint -> head
      arm_L_joint -> arm_L_slide -> arm_L   (sleeve on the joint; rail + board + strap on the slide)
      arm_R_joint -> arm_R_slide -> arm_R
      leg_L_joint -> leg_L_slide -> leg_L
      leg_R_joint -> leg_R_slide -> leg_R

Roles come from part names ("left arm ...", "head ...", "strap ...", "base ..."; see ROLE_RULES).
Pivots are estimated from geometry (limb end nearest the torso, PCA extension axis).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh

# keyword -> role. First match wins; order matters (specific before generic).
ROLE_RULES = [
    ("strap", "straps"), ("restraint", "straps"), ("belt", "straps"), ("cuff", "straps"),
    ("motor", "motors"), ("servo", "motors"), ("actuator", "motors"),
    ("head", "head"),
    ("left arm", "arm_L"), ("right arm", "arm_R"), ("left leg", "leg_L"), ("right leg", "leg_R"),
    ("torso", "back"), ("back", "back"), ("cushion", "back"), ("seat", "back"),
    ("base", "base"), ("pedestal", "base"), ("column", "base"), ("stand", "base"),
]
LIMBS = ["arm_L", "arm_R", "leg_L", "leg_R"]
COLORS = {"base": [70, 74, 82], "back": [150, 40, 38], "head": [150, 40, 38], "arm_L": [205, 205, 210],
          "arm_R": [205, 205, 210], "leg_L": [205, 205, 210], "leg_R": [205, 205, 210],
          "straps": [35, 30, 28], "motors": [230, 170, 40]}


def role_of(name: str) -> str:
    n = name.lower()
    for k, r in ROLE_RULES:
        if k in n:
            return r
    return "back"


def decimate(m: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
    if len(m.faces) <= target:
        return m
    try:
        import pymeshlab

        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(m.vertices, m.faces))
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target, preservenormal=True,
                                                    preservetopology=True, qualitythr=0.5)
        o = ms.current_mesh()
        return trimesh.Trimesh(o.vertex_matrix(), o.face_matrix())
    except Exception as e:
        print("decimation skipped:", e)
        return m


def load_parts(parts_dir: Path):
    """Return {role: [(name, Trimesh), ...]} in the source mesh's units (CubePart output is normalized)."""
    by_role: dict[str, list] = {}
    man = json.loads((parts_dir / "manifest.json").read_text())
    files = [(p["name"], parts_dir / p["file"]) for p in man["parts"] if p.get("file")]
    c, s = np.array(man.get("center", [0, 0, 0])), man.get("scale", 1.0)
    for name, f in files:
        m = trimesh.load(f, force="mesh")
        m.vertices = np.asarray(m.vertices) / s + c
        by_role.setdefault(role_of(name), []).append((name, m))
    return by_role


def pca_axes(v):
    c = v.mean(0)
    w, U = np.linalg.eigh(np.cov((v - c).T))
    return c, U[:, ::-1], w[::-1]  # descending variance


def frame(z, y):
    z = z / np.linalg.norm(z)
    y = y - z * (y @ z)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    return np.stack([x, y, z], 1)


def rig(parts_dir: Path, out: Path, height: float | None = None, faces_per_part: int = 15000) -> dict:
    """Write <out>.glb and <out>.rig.json; return {"joints": [...], "missing": [...]}."""
    by_role = load_parts(Path(parts_dir))
    if not by_role:
        raise ValueError("no non-empty parts to rig")
    if height:
        allv = np.concatenate([np.asarray(m.vertices) for v in by_role.values() for _, m in v])
        lo, hi = allv.min(0), allv.max(0)
        k = height / (hi[1] - lo[1])
        off = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        for v in by_role.values():
            for _, m in v:
                m.vertices = (np.asarray(m.vertices) - off) * k
    print({r: [n for n, _ in v] for r, v in by_role.items()})
    merged = {r: trimesh.util.concatenate([m for _, m in v]) for r, v in by_role.items()}
    missing = [r for r in LIMBS if r not in merged]
    if missing:
        print("WARNING: no parts for", missing)

    # torso frame: back-plane normal = least-variance axis of torso, oriented toward +Z (front)
    torso = merged["back"] if "back" in merged else trimesh.util.concatenate(list(merged.values()))
    tc, tU, _ = pca_axes(np.asarray(torso.vertices))
    normal = tU[:, 2] * np.sign(tU[2, 2] or 1)

    # straps / motors: split into components and hand each to the nearest limb (or back)
    attach = {r: [] for r in merged}
    for extra in ("straps", "motors"):
        if extra not in merged:
            continue
        for comp in merged.pop(extra).split(only_watertight=False):
            if len(comp.faces) < 20:
                continue
            cc = comp.centroid
            best, bd = "back", np.linalg.norm(cc - tc) * (1.0 if extra == "straps" else 0.8)
            if extra == "straps":  # motors stay on the back frame (they are the joint housing)
                for r in LIMBS:
                    # a strap is small relative to its limb; big pieces (platforms, frames) stay on the body
                    if r in merged and comp.scale < 0.45 * merged[r].scale:
                        d = trimesh.proximity.closest_point(merged[r], [cc])[1][0]
                        if d < bd and d < 0.12 * merged[r].scale:
                            best, bd = r, d
            attach.setdefault(best, []).append((extra, comp))

    spec = {"units": "m" if height else "source mesh units", "frame": "+Y up, +Z forward",
           "joints": {}}
    scene = trimesh.Scene()
    root = "asset_root"
    scene.graph.update(frame_from=scene.graph.base_frame, frame_to=root, matrix=np.eye(4))

    def add_mesh(role, mesh, parent, T_parent_world, color):
        m = decimate(mesh, faces_per_part)
        m.apply_transform(np.linalg.inv(T_parent_world))
        m.visual.face_colors = color + [255]
        scene.add_geometry(m, geom_name=f"{role}_geo_{len(scene.geometry)}", node_name=f"{role}_geo_{len(scene.geometry)}",
                           parent_node_name=parent)

    def add_node(name, parent, T_world, T_parent_world):
        scene.graph.update(frame_from=parent, frame_to=name, matrix=np.linalg.inv(T_parent_world) @ T_world)

    I = np.eye(4)
    if "base" in merged:
        add_node("base", root, I, I)
        add_mesh("base", merged["base"], "base", I, COLORS["base"])

    # recline joint: at the bottom of the back assembly, axis = X
    back_v = np.asarray(torso.vertices)
    rpiv = np.array([tc[0], back_v[:, 1].min(), tc[2]])
    T_rec = np.eye(4); T_rec[:3, 3] = rpiv
    add_node("recline_joint", root, T_rec, I)
    spec["joints"]["recline"] = dict(node="recline_joint", pivot=rpiv.tolist(), rotate_local="X",
                                    limits_deg=[-30, 60])
    add_node("back", "recline_joint", T_rec, T_rec)
    add_mesh("back", torso, "back", T_rec, COLORS["back"])
    for kind, comp in attach.get("back", []):
        add_mesh(kind, comp, "back", T_rec, COLORS[kind])

    if "head" in merged:
        hv = np.asarray(merged["head"].vertices)
        hpiv = np.array([tc[0], hv[:, 1].min(), hv[:, 2].min()])
        T_h = np.eye(4); T_h[:3, 3] = hpiv
        add_node("head_joint", "recline_joint", T_h, T_rec)
        add_mesh("head", merged["head"], "head_joint", T_h, COLORS["head"])
        spec["joints"]["head"] = dict(node="head_joint", pivot=hpiv.tolist(), rotate_local="X",
                                     limits_deg=[-25, 25])

    for r in LIMBS:
        if r not in merged:
            continue
        v = np.asarray(merged[r].vertices)
        c, U, _ = pca_axes(v)
        a = U[:, 0]
        if (c - tc) @ a < 0:
            a = -a  # point away from torso
        proj = (v - c) @ a
        near = v[proj < proj.min() + 0.06 * (proj.max() - proj.min())]
        piv = near.mean(0)
        R = frame(normal, a)  # local Z = back-plane normal (swing), local Y = extend dir
        T_j = np.eye(4); T_j[:3, :3] = R; T_j[:3, 3] = piv
        jn, sn = f"{r}_joint", f"{r}_slide"
        add_node(jn, "recline_joint", T_j, T_rec)
        add_node(sn, jn, T_j, T_j)
        # telescoping split: proximal sleeve stays on the joint, distal board rides the slide,
        # and a steel rail (piston rod) on the slide bridges the gap when extended
        lv = (np.asarray(merged[r].vertices) - piv) @ R  # joint-local coords
        L = float(lv[:, 1].max())
        yc = 0.45 * L
        o_c = piv + R[:, 1] * yc
        try:
            sleeve = trimesh.intersections.slice_mesh_plane(merged[r], -R[:, 1], o_c, cap=True)
            board = trimesh.intersections.slice_mesh_plane(merged[r], R[:, 1], o_c, cap=True)
        except Exception as e:
            print("capped slice failed, using open slice:", e)
            sleeve = trimesh.intersections.slice_mesh_plane(merged[r], -R[:, 1], o_c)
            board = trimesh.intersections.slice_mesh_plane(merged[r], R[:, 1], o_c)
        ext_x, ext_z = np.ptp(lv[:, 0]), np.ptp(lv[:, 2])
        cx, cz = np.median(lv[:, 0]), np.median(lv[:, 2])
        rail = trimesh.creation.box(extents=[0.3 * ext_x, 0.34 * L, 0.35 * ext_z])
        rail.apply_translation([cx, yc - 0.15 * L, cz])
        rail.apply_transform(T_j)  # to world, add_mesh maps back into the slide frame
        add_mesh(r, sleeve, jn, T_j, [120, 124, 132])
        add_mesh(r, rail, sn, T_j, [160, 166, 174])
        add_mesh(r, board, sn, T_j, COLORS[r])
        for kind, comp in attach.get(r, []):
            add_mesh(kind, comp, sn, T_j, COLORS[kind])
        length = float(proj.max() - proj.min())
        spec["joints"][r] = dict(
            joint_node=jn, slide_node=sn, pivot=piv.tolist(), swing_axis_world=R[:, 2].tolist(),
            extend_dir_world=R[:, 1].tolist(), lift_axis_world=R[:, 0].tolist(),
            swing_local="Z", lift_local="X", extend_local="+Y", length=length,
            limits=dict(swing_deg=[-90, 90], lift_deg=[-45, 80], extend=[0.0, round(0.3 * length, 4)]),
        )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    scene.export(str(out) + ".glb")
    (Path(str(out) + ".rig.json")).write_text(json.dumps(spec, indent=2))

    # stamp joint metadata into glTF node extras so engines can read it directly
    try:
        from pygltflib import GLTF2

        g = GLTF2().load(str(out) + ".glb")
        lut = {}
        for jname, j in spec["joints"].items():
            lut[j.get("joint_node", j.get("node"))] = dict(joint=jname, **{k: v for k, v in j.items() if k != "pivot"})
            if "slide_node" in j:
                lut[j["slide_node"]] = dict(joint=jname, role="telescoping_slide", axis="+Y",
                                            range=j["limits"]["extend"])
        for n in g.nodes:
            if n.name in lut:
                n.extras = lut[n.name]
        g.save(str(out) + ".glb")
    except Exception as e:
        print("extras not written:", e)
    print("wrote", str(out) + ".glb", "joints:", list(spec["joints"]))
    return {"joints": list(spec["joints"]), "missing": missing,
            "faces": int(sum(len(g.faces) for g in scene.geometry.values()))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--parts-dir", required=True)
    ap.add_argument("--out", required=True, help="output stem: writes <out>.glb and <out>.rig.json")
    ap.add_argument("--faces-per-part", type=int, default=15000)
    ap.add_argument("--height", type=float, default=None, help="rescale to this height (m), floor at y=0")
    a = ap.parse_args()
    rig(Path(a.parts_dir), Path(a.out), a.height, a.faces_per_part)


if __name__ == "__main__":
    main()
