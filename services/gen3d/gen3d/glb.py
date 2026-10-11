"""Minimal GLB writer for placeholder assets (coloured boxes), used by the fake worker and tests."""

from __future__ import annotations

import json
import struct


def _box(cx, cy, cz, sx, sy, sz):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    faces = [  # (normal, 4 corners)
        ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
        ((-1, 0, 0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
        ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
    ]
    pos, nrm, idx = [], [], []
    for n, quad in faces:
        base = len(pos)
        for x, y, z in quad:
            pos.append((cx + x * hx, cy + y * hy, cz + z * hz))
            nrm.append(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nrm, idx


def boxes_glb(boxes: list[dict]) -> bytes:
    """boxes: [{name, center:(x,y,z), size:(x,y,z), color:(r,g,b) 0-255}] -> GLB bytes (one node each)."""
    bin_parts, views, accessors, meshes, nodes, materials = [], [], [], [], [], []
    offset = 0

    def add(data: bytes, target: int) -> int:
        nonlocal offset
        pad = (-len(data)) % 4
        bin_parts.append(data + b"\0" * pad)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        offset += len(data) + pad
        return len(views) - 1

    for i, b in enumerate(boxes):
        pos, nrm, idx = _box(*b["center"], *b["size"])
        pv = add(b"".join(struct.pack("<3f", *p) for p in pos), 34962)
        nv = add(b"".join(struct.pack("<3f", *n) for n in nrm), 34962)
        iv = add(struct.pack(f"<{len(idx)}H", *idx), 34963)
        xs, ys, zs = zip(*pos)
        accessors += [
            {"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": nv, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
            {"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ]
        r, g, bl = (c / 255 for c in b.get("color", (180, 180, 180)))
        materials.append({"pbrMetallicRoughness": {"baseColorFactor": [r, g, bl, 1], "metallicFactor": 0.1,
                                                   "roughnessFactor": 0.6}})
        meshes.append({"name": b["name"], "primitives": [{"attributes": {"POSITION": 3 * i, "NORMAL": 3 * i + 1},
                                                           "indices": 3 * i + 2, "material": i}]})
        nodes.append({"name": b["name"], "mesh": i})

    blob = b"".join(bin_parts)
    gltf = {"asset": {"version": "2.0", "generator": "3DGenerate placeholder"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
            "materials": materials, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def count_faces(path) -> int | None:
    """Triangles in a GLB, from its JSON chunk (indices / 3, or positions / 3 without indices)."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
            if head[:4] != b"glTF":
                return None
            n = struct.unpack("<I", head[12:16])[0]
            doc = json.loads(f.read(n))
    except (OSError, ValueError, struct.error):
        return None
    acc, total = doc.get("accessors") or [], 0
    for mesh in doc.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            i = prim.get("indices")
            total += (acc[i]["count"] if i is not None else acc[prim["attributes"]["POSITION"]]["count"]) // 3
    return total
